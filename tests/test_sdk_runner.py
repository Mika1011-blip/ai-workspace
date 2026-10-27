"""The SDK runner against a scripted fake of ClaudeSDKClient: no CLI, no
network. Messages are the SDK's own types, so what the runner reads is what
the real client yields."""

import asyncio
import time
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from app.runner import SpawnSpec
from app.sdk_runner import SdkRunner, context_window, session_env


def spec(tmp_path, worker="researcher", task="look things up"):
    return SpawnSpec(worker, task, "tok", tmp_path / worker, tmp_path / "_shared", "http://api")


def init(session_id, model="claude-opus-5-5"):
    return SystemMessage("init", {"session_id": session_id, "model": model, "tools": ["Read", "Write"]})


def assistant(*blocks, usage=None, model="claude-opus-5-5"):
    return AssistantMessage(list(blocks), model, usage=usage)


def tool_result(tool_use_id="t1"):
    return UserMessage([ToolResultBlock(tool_use_id, "ok", False)])


def result(turns=3, cost=0.05, text="done", error=False, subtype="success"):
    return ResultMessage(
        subtype, 1000, 900, error, turns, "sid", total_cost_usd=cost,
        usage={"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 5},
        result=text,
    )


WAIT = "WAIT"  # the fake blocks here until the next query() arrives


class FakeClient:
    """Yields a script; `WAIT` entries block until the runner sends a query.
    After the script it stays open (like a real idle session) until
    disconnect()."""

    instances: list = []

    def __init__(self, options, script):
        self.options = options
        self.script = list(script)
        self.queries: list[str] = []
        self.interrupted = False
        self.disconnected = False
        self._wake = asyncio.Event()
        self._closed = asyncio.Event()
        FakeClient.instances.append(self)

    async def connect(self):
        pass

    async def query(self, prompt, session_id="default"):
        self.queries.append(prompt)
        self._wake.set()

    async def receive_messages(self):
        await self._wake.wait()  # the first query
        self._wake.clear()
        for item in self.script:
            if item == WAIT:
                await self._wake.wait()
                self._wake.clear()
                continue
            yield item
            await asyncio.sleep(0)
        await self._closed.wait()

    async def interrupt(self):
        self.interrupted = True

    async def disconnect(self):
        self.disconnected = True
        self._closed.set()
        self._wake.set()


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def ended():
    return []


@pytest.fixture
def make_runner(ended):
    FakeClient.instances.clear()

    def factory(script):
        captured = {}

        def build(s, session_id):
            captured["session_id"] = session_id
            return type("Opts", (), {"session_id": session_id})(), f"prompt for {s.worker}: {s.task}"

        runner = SdkRunner(
            build,
            client_factory=lambda options: FakeClient(options, script),
            on_end=lambda sid, info: ended.append((sid, info)),
        )
        return runner, captured

    return factory


class TestStart:
    def test_start_returns_the_chosen_id_once_the_session_has_initialised(self, tmp_path, make_runner):
        runner, captured = make_runner([lambda sid: init(sid)])
        # The fake needs the id the runner chose: resolve the lazy init lazily.
        runner._factory = lambda options: FakeClient(options, [init(options.session_id)])

        sid = runner.start(spec(tmp_path))

        assert sid == captured["session_id"] and len(sid) == 36
        assert FakeClient.instances[-1].queries == ["prompt for researcher: look things up"]
        assert runner.running_ids() == {sid}
        (state,) = runner.state()
        assert state.worker == "researcher" and state.current_task == "look things up"
        assert state.status == "thinking" and state.extra["runner"] == "sdk"

    def test_start_fails_cleanly_when_the_client_cannot_connect(self, tmp_path, make_runner):
        runner, _ = make_runner([])

        class Broken(FakeClient):
            async def connect(self):
                raise OSError("no cli here")

        runner._factory = lambda options: Broken(options, [])

        with pytest.raises(RuntimeError, match="spawn_failed"):
            runner.start(spec(tmp_path))
        assert runner.running_ids() == set() and runner.state() == []


class TestLiveState:
    def test_tool_use_thinking_waiting_and_cost_follow_the_messages(self, tmp_path, make_runner):
        runner, _ = make_runner([])
        runner._factory = lambda options: FakeClient(options, [
            init(options.session_id),
            assistant(ToolUseBlock("t1", "Read", {"file_path": "x"}), usage={"input_tokens": 1000, "cache_read_input_tokens": 199_000}),
            tool_result(),
            assistant(TextBlock("all read"), usage={"input_tokens": 1000, "cache_read_input_tokens": 400_000}),
            result(turns=2, cost=0.07, text="all read"),
            WAIT,
        ])

        sid = runner.start(spec(tmp_path))
        events = runner.subscribe()

        assert wait_for(lambda: runner.state()[0].status == "waiting")
        (state,) = runner.state()
        assert state.tool is None and state.context_used == 0.401  # 401k of a 1M window
        assert state.extra["cost_usd"] == 0.07 and state.extra["turns"] == 2
        statuses = [e["status"] for e in runner.history]
        assert statuses[:4] == ["thinking", "using_tool", "thinking", "thinking"] and statuses[-1] == "waiting"
        assert [e["tool"] for e in runner.history][1] == "Read"
        assert sid in {e["session_id"] for e in runner.history}
        runner.unsubscribe(events)

    def test_an_error_result_shows_as_error(self, tmp_path, make_runner):
        runner, _ = make_runner([])
        runner._factory = lambda options: FakeClient(options, [
            init(options.session_id), result(error=True, subtype="error_max_turns", text="too long"), WAIT,
        ])

        runner.start(spec(tmp_path))

        assert wait_for(lambda: runner.state()[0].status == "error")


class TestMessagesAndEnding:
    def test_send_forwards_a_follow_up_into_the_session(self, tmp_path, make_runner):
        runner, _ = make_runner([])
        runner._factory = lambda options: FakeClient(options, [
            init(options.session_id), result(text="first"), WAIT, assistant(TextBlock("second")), result(text="second"), WAIT,
        ])
        sid = runner.start(spec(tmp_path))
        assert wait_for(lambda: runner.state()[0].status == "waiting")

        assert runner.send(sid, "and now the second thing") is True

        client = FakeClient.instances[-1]
        assert client.queries[-1] == "and now the second thing"
        assert wait_for(lambda: FakeClient.instances[-1].queries[-1] == "and now the second thing" and runner.state()[0].extra["turns"] == 3)
        assert runner.send("nope", "x") is False

    def test_finish_ends_the_session_after_its_turn_and_closes_the_books(self, tmp_path, make_runner, ended):
        runner, _ = make_runner([])
        runner._factory = lambda options: FakeClient(options, [
            init(options.session_id), assistant(TextBlock("reporting")), WAIT, result(turns=4, cost=0.11, text="reported"),
        ])
        sid = runner.start(spec(tmp_path))
        assert wait_for(lambda: len(runner.history) >= 2)

        runner.finish(sid)  # the worker is mid-turn: nothing happens yet
        time.sleep(0.1)
        client = FakeClient.instances[-1]
        assert client.disconnected is False and ended == []
        runner._loop.call_soon_threadsafe(client._wake.set)  # the turn completes

        assert wait_for(lambda: ended)
        (ended_sid, info) = ended[0]
        assert ended_sid == sid and info["outcome"] == "success"
        assert info["cost_usd"] == 0.11 and info["turns"] == 4 and info["result"] == "reported"
        assert info["usage"]["output_tokens"] == 20 and info["model"] == "claude-opus-5-5"
        assert FakeClient.instances[-1].disconnected is True and FakeClient.instances[-1].interrupted is False
        assert runner.running_ids() == set()
        assert runner.state()[0].status == "idle"

    def test_stop_interrupts_a_busy_session_and_reports_it_stopped(self, tmp_path, make_runner, ended):
        runner, _ = make_runner([])
        runner._factory = lambda options: FakeClient(options, [
            init(options.session_id), assistant(ToolUseBlock("t1", "Write", {})), WAIT,
        ])
        sid = runner.start(spec(tmp_path))
        assert wait_for(lambda: runner.state()[0].status == "using_tool")

        runner.stop(sid)

        assert wait_for(lambda: ended)
        assert ended[0][1]["outcome"] == "stopped"
        client = FakeClient.instances[-1]
        assert client.interrupted is True and client.disconnected is True

    def test_a_client_crash_mid_session_still_closes_the_books(self, tmp_path, make_runner, ended):
        class Crashing(FakeClient):
            async def receive_messages(self):
                yield init(self.options.session_id)
                raise ConnectionResetError("cli died")

        runner, _ = make_runner([])
        runner._factory = lambda options: Crashing(options, [])

        sid = runner.start(spec(tmp_path))

        assert wait_for(lambda: ended)
        assert ended[0][1]["outcome"] == "error" and "cli died" in ended[0][1]["error"]
        assert runner.state()[0].status == "error" and runner.running_ids() == set()


class TestHelpers:
    def test_context_window_by_model(self):
        assert context_window("claude-opus-5-5") == 1_000_000
        assert context_window("claude-fable-5-1") == 1_000_000
        assert context_window("claude-haiku-4-5") == 200_000
        assert context_window(None) == 200_000

    def test_session_env_drops_api_keys(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-no")
        monkeypatch.setenv("KEEP_ME", "1")

        env = session_env()

        assert "ANTHROPIC_API_KEY" not in env and env["KEEP_ME"] == "1"
