"""App sessions on the Claude Agent SDK (docs/vision-gap.md §2.2).

One `ClaudeSDKClient` per session, all driven from a private asyncio loop
in a daemon thread so the synchronous API can start, message and stop
sessions without becoming async itself. Unlike `claude --bg`, the SDK lets
us pick the session id, streams every event (status, tool in use, cost),
accepts follow-up messages, and the session dies with this process, so
there is nothing to reconcile against on restart.

The runner draws no conclusions about runs or projects: it reports what
happened through `on_end`, and the API closes the books.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from app.runner import LiveState, SpawnSpec

try:  # the SDK is a real dependency, but tests fake the client
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ToolUseBlock,
        UserMessage,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("claude-agent-sdk is not installed (pip install -r requirements.txt)") from exc

START_TIMEOUT_S = 90.0
EVENT_HISTORY = 500


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def context_window(model: str | None) -> int:
    """Tokens of context the model has; the gauge is tokens-in-use / this."""
    if not model:
        return 200_000
    if any(tag in model for tag in ("-5", "fable", "mythos")) and "haiku-4" not in model:
        return 1_000_000
    return 200_000


def session_env() -> dict[str, str]:
    """The spawned CLI's environment: ours, minus any API key, so app sessions
    always run on the login this machine already has (no API spend)."""
    return {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}


@dataclass
class _Session:
    id: str
    spec: SpawnSpec
    state: LiveState
    client: Any = None
    model: str | None = None
    cost_usd: float | None = None
    turns: int = 0
    usage: dict = field(default_factory=dict)
    last_text: str = ""
    error: str | None = None
    outcome: str | None = None  # success | error | stopped
    end_after_turn: bool = False
    busy: bool = False  # between a query and its ResultMessage
    started: asyncio.Future | None = None
    task: asyncio.Task | None = None


class SdkRunner:
    name = "sdk"

    def __init__(
        self,
        build: Callable[[SpawnSpec, str], tuple[Any, str]],
        client_factory: Callable[[Any], Any] | None = None,
        on_end: Callable[[str, dict], None] | None = None,
    ) -> None:
        """`build(spec, session_id)` returns the SDK options and the first
        prompt; `client_factory(options)` returns a ClaudeSDKClient-like
        object (tests pass a fake); `on_end(session_id, info)` is called from
        the runner thread once the session is over."""
        self._build = build
        self._factory = client_factory or (lambda options: ClaudeSDKClient(options=options))
        self.on_end = on_end
        self._sessions: dict[str, _Session] = {}
        self._last: dict[str, LiveState] = {}  # a worker's final state after its session ended
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._subscribers: list[queue.Queue] = []
        self.history: deque[dict] = deque(maxlen=EVENT_HISTORY)

    # ----- the loop thread -------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._loop.run_forever, name="sdk-runner", daemon=True)
                self._thread.start()
            return self._loop

    def _call(self, coro, timeout: float | None = None):
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)

    # ----- Runner interface ------------------------------------------------

    def start(self, spec: SpawnSpec) -> str:
        session_id = str(uuid.uuid4())
        options, prompt = self._build(spec, session_id)
        state = LiveState(session_id, spec.worker, "thinking", spec.task, None, 0.0, now_iso())
        session = _Session(session_id, spec, state)
        with self._lock:
            self._sessions[session_id] = session
        loop = self._ensure_loop()

        async def launch() -> None:
            session.started = loop.create_future()
            session.task = loop.create_task(self._run(session, options, prompt))

        self._call(launch())
        try:
            asyncio.run_coroutine_threadsafe(self._wait_started(session), loop).result(START_TIMEOUT_S)
        except Exception as exc:
            with self._lock:
                self._sessions.pop(session_id, None)
            raise RuntimeError(f"spawn_failed: {exc}") from exc
        return session_id

    async def _wait_started(self, session: _Session) -> None:
        await session.started

    def send(self, session_id: str, text: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None or session.client is None or session.outcome is not None:
            return False

        async def go() -> None:
            session.busy = True
            self._set(session, "thinking", tool=None)
            await session.client.query(text)

        self._call(go(), timeout=30)
        return True

    def finish(self, session_id: str) -> None:
        """End the session once its current turn is over (after it has
        reported, say) -- never mid-tool-call."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.end_after_turn = True
        if not session.busy:
            self.stop(session_id)

    def stop(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.client is None:
            return

        async def go() -> None:
            if session.outcome is None:
                session.outcome = "stopped"
            try:
                if session.busy:
                    await session.client.interrupt()
            except Exception:  # noqa: BLE001 -- best effort; disconnect is what matters
                pass
            await session.client.disconnect()

        try:
            self._call(go(), timeout=30)
        except Exception:  # noqa: BLE001 -- the task's finally still closes the books
            pass

    def running_ids(self) -> set[str] | None:
        with self._lock:
            return set(self._sessions)

    def state(self) -> list[LiveState]:
        """Live sessions first; then the last known state of every worker
        whose session has ended, so a station keeps showing its error."""
        with self._lock:
            live = [s.state for s in self._sessions.values()]
            busy = {st.worker for st in live}
            return live + [st for w, st in self._last.items() if w not in busy]

    # ----- events (for the floor) ------------------------------------------

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _publish(self, event: dict) -> None:
        with self._lock:
            self.history.append(event)
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(event)

    def _set(self, session: _Session, status: str, tool: str | None = None, text: str | None = None) -> None:
        st = session.state
        st.status, st.tool, st.updated_at = status, tool, now_iso()
        st.extra = {"cost_usd": session.cost_usd, "turns": session.turns, "model": session.model, "runner": self.name}
        event = {
            "at": st.updated_at, "session_id": session.id, "worker": session.spec.worker, "status": status,
            "tool": tool, "context_used": st.context_used, "cost_usd": session.cost_usd, "turns": session.turns,
        }
        if text:
            event["text"] = text[:500]
        self._publish(event)

    # ----- the session itself ----------------------------------------------

    async def _run(self, session: _Session, options: Any, prompt: str) -> None:
        info: dict = {}
        try:
            client = self._factory(options)
            await client.connect()
            session.client = client
            session.busy = True
            await client.query(prompt)
            async for message in client.receive_messages():
                self._observe(session, message)
                if isinstance(message, SystemMessage) and message.subtype == "init" and not session.started.done():
                    session.started.set_result(None)
                if isinstance(message, ResultMessage) and session.end_after_turn:
                    if session.outcome is None:
                        session.outcome = "success" if not message.is_error else "error"
                    await client.disconnect()
                    break
            if session.outcome is None:
                session.outcome = "stopped"
        except Exception as exc:  # noqa: BLE001 -- whatever broke, the books must close
            session.error = f"{type(exc).__name__}: {exc}"
            session.outcome = session.outcome or "error"
            if not session.started.done():
                session.started.set_exception(RuntimeError(session.error))
        finally:
            if not session.started.done():
                session.started.set_exception(RuntimeError("session ended before it started"))
            self._set(session, "idle" if session.outcome != "error" else "error")
            info = {
                "session_id": session.id, "worker": session.spec.worker, "outcome": session.outcome,
                "cost_usd": session.cost_usd, "turns": session.turns, "usage": session.usage,
                "model": session.model, "result": session.last_text, "error": session.error,
            }
            if self.on_end is not None:
                try:
                    await asyncio.to_thread(self.on_end, session.id, info)
                except Exception:  # noqa: BLE001 -- a bookkeeping failure must not take the loop down
                    pass
            with self._lock:
                self._sessions.pop(session.id, None)
                if session.started.exception() is None:  # never-started sessions leave no trace
                    self._last[session.spec.worker] = session.state

    def _observe(self, session: _Session, message: Any) -> None:
        if isinstance(message, SystemMessage):
            if message.subtype == "init":
                session.model = message.data.get("model")
                self._set(session, "thinking")
            elif message.subtype == "permission_denied":
                self._set(session, "thinking", text=f"denied: {message.data.get('tool_name')}")
        elif isinstance(message, AssistantMessage):
            if message.usage:
                used = sum(int(message.usage.get(k) or 0) for k in
                           ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                session.state.context_used = round(min(1.0, used / context_window(session.model or message.model)), 3)
            tool = next((b.name for b in message.content if isinstance(b, ToolUseBlock)), None)
            text = next((b.text for b in message.content if isinstance(b, TextBlock)), None)
            if text:
                session.last_text = text
            self._set(session, "using_tool" if tool else "thinking", tool=tool, text=text)
        elif isinstance(message, UserMessage):
            # A tool result came back; the worker is thinking about it.
            if session.busy:
                self._set(session, "thinking")
        elif isinstance(message, ResultMessage):
            session.busy = False
            session.turns = message.num_turns or session.turns
            if message.total_cost_usd is not None:
                session.cost_usd = message.total_cost_usd
            if message.usage:
                session.usage = {k: message.usage.get(k) for k in
                                 ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
            if message.result:
                session.last_text = message.result
            if message.is_error:
                session.error = message.subtype
                self._set(session, "error", text=message.result)
            else:
                self._set(session, "waiting", text=message.result)


def dump_options(options: Any) -> dict:
    """What a spawn looked like, for the activity log (no secrets)."""
    return {
        "cwd": str(options.cwd), "tools": options.tools, "add_dirs": [str(d) for d in options.add_dirs],
        "permission_mode": options.permission_mode, "session_id": options.session_id,
        "extra_args": options.extra_args, "settings": json.loads(options.settings) if options.settings else None,
    }
