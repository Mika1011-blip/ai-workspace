"""How app sessions are run.

The API talks to a `Runner` and never to a process directly, so the way a
worker is launched can change (today the `claude --bg` CLI, next the
Claude Agent SDK) without the endpoints, the pipeline or the dispatcher
noticing. A runner owns four things: starting a locked-down session for a
`SpawnSpec`, forwarding a message into it, stopping it, and saying which
sessions are running right now.
"""

from __future__ import annotations

import queue
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class SpawnSpec:
    """Everything a runner needs to launch one app session. The paths are
    already resolved and validated; the token is the session's identity."""

    worker: str
    task: str
    token: str
    worker_folder: Path
    shared_dir: Path
    api_url: str
    tools: tuple[str, ...] = ()
    read_from: tuple[Path, ...] = ()
    write_to: tuple[Path, ...] = ()
    # Extra MCP servers from the worker's toolkit, name -> definition
    # (command/args/env or url), already resolved from the catalog.
    mcp_servers: dict = field(default_factory=dict)


@dataclass
class LiveState:
    """What a station on the floor shows for one running session."""

    session_id: str
    worker: str
    status: str  # idle | thinking | using_tool | waiting | error
    current_task: str | None = None
    tool: str | None = None
    context_used: float = 0.0
    updated_at: str = ""
    extra: dict = field(default_factory=dict)


class Runner(Protocol):
    name: str  # "cli" | "sdk"; shows up in records and /workers/state

    def start(self, spec: SpawnSpec) -> str:
        """Launch the session and return its id."""

    def send(self, session_id: str, text: str) -> bool:
        """Forward a message into the session. False = this runner can't."""

    def stop(self, session_id: str) -> None:
        """End the session now, mid-turn if need be."""

    def finish(self, session_id: str) -> None:
        """End the session once its current turn is over (it has reported)."""

    def running_ids(self) -> set[str] | None:
        """Ids running right now, or None when that can't be determined."""

    def state(self) -> list[LiveState]:
        """Live state for every running session this runner knows about."""

    history: deque  # the last state changes, oldest first

    def subscribe(self) -> queue.Queue:
        """A queue that receives every state change from now on."""

    def unsubscribe(self, q: queue.Queue) -> None: ...


class CliRunner:
    """App sessions as `claude --bg` processes (the way it has worked so
    far). It knows nothing about a session after launch: no forwarding, no
    live state; `running_ids` comes from `claude agents --json`."""

    name = "cli"

    def __init__(
        self,
        argv_fn: Callable[[SpawnSpec], list[str]],
        spawn_fn: Callable[[list[str], Path], str],
        stop_fn: Callable[[str], None],
        running_ids_fn: Callable[[], set[str] | None],
        parse_id: Callable[[str], str],
    ) -> None:
        self._argv = argv_fn
        self._spawn = spawn_fn
        self._stop = stop_fn
        self._running = running_ids_fn
        self._parse_id = parse_id

    def start(self, spec: SpawnSpec) -> str:
        # Claude Code assigns the id itself and prints it; it is only known now.
        return self._parse_id(self._spawn(self._argv(spec), spec.worker_folder))

    def send(self, session_id: str, text: str) -> bool:
        return False

    def stop(self, session_id: str) -> None:
        self._stop(session_id)

    def finish(self, session_id: str) -> None:
        # A --bg session cannot be told "after this turn"; it stays until
        # someone stops it (as it always has).
        return None

    def running_ids(self) -> set[str] | None:
        return self._running()

    def state(self) -> list[LiveState]:
        return []

    # A --bg session reports nothing while it runs: no events, ever.
    history: deque = deque(maxlen=1)

    def subscribe(self) -> queue.Queue:
        return queue.Queue()

    def unsubscribe(self, q: queue.Queue) -> None:
        return None
