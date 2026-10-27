"""The API side of the SDK runner: the options it builds, the books it closes
when a session ends, and /workers/state."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import sessions_store
from app.main import create_app, sdk_options
from app.runner import LiveState, SpawnSpec
from tests.test_sessions import (  # noqa: F401 -- fixtures shared with the session tests
    STOPPED,
    _reset_fakes,
    create_worker,
    messages_log,
    sessions_db,
    templates_dir,
    workers_dir,
)


class FakeSdkRunner:
    """Behaves like SdkRunner from the API's point of view: ids are chosen
    up front, `finish` is remembered, `on_end` is wired by create_app."""

    name = "sdk"

    def __init__(self):
        self.on_end = None
        self.started: list[SpawnSpec] = []
        self.finished: list[str] = []
        self.stopped: list[str] = []
        self.live: list[LiveState] = []
        self.sent: list[tuple[str, str]] = []

    def start(self, spec):
        self.started.append(spec)
        return f"sid-{len(self.started)}"

    def send(self, session_id, text):
        self.sent.append((session_id, text))
        return True

    def stop(self, session_id):
        self.stopped.append(session_id)

    def finish(self, session_id):
        self.finished.append(session_id)

    def running_ids(self):
        return {f"sid-{i + 1}" for i in range(len(self.started))} - set(self.stopped)

    def state(self):
        return list(self.live)

    # events, like SdkRunner: a history plus live queues
    def __post_init__(self):
        pass

    @property
    def history(self):
        if not hasattr(self, "_history"):
            self._history = []
        return self._history

    def subscribe(self):
        import queue

        q = queue.Queue()
        self.subscribers = getattr(self, "subscribers", [])
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.remove(q)

    def publish(self, event):
        self.history.append(event)
        for q in getattr(self, "subscribers", []):
            q.put(event)


def auth(runner):
    # The fake runner saw the token in its SpawnSpec; that is the session's identity.
    return {"X-Session-Token": runner.started[-1].token}


def make(workers_dir, templates_dir, sessions_db, messages_log, runner):
    return TestClient(create_app(
        workers_dir=workers_dir, templates_dir=templates_dir, sessions_db=sessions_db,
        messages_log=messages_log, runner=runner, render_run=lambda argv: (0, ""),
    ))


class TestSdkOptions:
    def test_same_wall_as_the_cli_spawn(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-leak")
        (tmp_path / "projects" / "p" / "artifacts").mkdir(parents=True)
        spec = SpawnSpec(
            "scriptwriter", "write it", "tok123", tmp_path / "workers" / "scriptwriter", tmp_path / "workers" / "_shared",
            "http://localhost:8000", ("WebFetch",), (), (tmp_path / "projects" / "p" / "artifacts",),
        )

        options, prompt = sdk_options(spec, "11111111-2222-3333-4444-555555555555")

        assert prompt == "Read CLAUDE.md and ../_shared/COMMS.md, then: write it"
        assert options.cwd == str(tmp_path / "workers" / "scriptwriter")
        assert options.tools == ["Read", "Glob", "Grep", "Edit", "Write", "WebFetch"]
        assert options.permission_mode == "dontAsk" and options.extra_args == {"restricted": None}
        assert options.session_id == "11111111-2222-3333-4444-555555555555"
        assert options.setting_sources == ["project"] and options.strict_mcp_config is True
        assert [Path(d) for d in options.add_dirs] == [
            (tmp_path / "workers" / "_shared").resolve(), (tmp_path / "projects" / "p" / "artifacts").resolve(),
        ]
        settings = json.loads(options.settings)
        assert "Bash" in settings["permissions"]["deny"] and "WebFetch" in settings["permissions"]["allow"]
        assert any(d.startswith("Write(//") and d.endswith("_shared/**)") for d in settings["permissions"]["deny"])
        server = options.mcp_servers["ai-workspace"]
        assert server["env"] == {"SESSION_TOKEN": "tok123", "WORKSPACE_API_URL": "http://localhost:8000"}
        assert "ANTHROPIC_API_KEY" not in options.env


class TestSessionLifecycle:
    def test_report_finishes_the_session_and_its_end_adds_cost_to_the_record(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        create_worker(c, "researcher")
        body = c.post("/sessions", json={"worker": "researcher", "task": "x"}).json()
        sid, run_id = body["session_id"], body["run_id"]
        assert sid == "sid-1" and runner.on_end is not None

        c.post("/sessions/me/result", json={"status": "success", "summary": "found it"}, headers=auth(runner))
        assert runner.finished == [sid]

        runner.on_end(sid, {"outcome": "success", "cost_usd": 0.42, "turns": 7,
                            "usage": {"input_tokens": 10, "output_tokens": 20}, "error": None})

        rec = c.get(f"/runs/{run_id}").json()
        assert rec["status"] == "success" and rec["result"]["summary"] == "found it"  # the verdict stands
        assert rec["metrics"]["cost_usd"] == 0.42 and rec["metrics"]["turns"] == 7
        assert rec["metrics"]["tokens"] == {"input_tokens": 10, "output_tokens": 20}
        assert sessions_store.get_session(sessions_db, sid)["status"] == "ended"
        events = [json.loads(l)["event"] for l in (workers_dir / "researcher" / "activity.jsonl").read_text().splitlines()]
        assert events[-1] == "session_over"

    def test_a_session_that_dies_unreported_fails_its_run(self, workers_dir, templates_dir, sessions_db, messages_log):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        create_worker(c, "researcher")
        body = c.post("/sessions", json={"worker": "researcher", "task": "x"}).json()

        runner.on_end(body["session_id"], {"outcome": "error", "cost_usd": 0.01, "turns": 1, "error": "ProcessError: cli died"})

        rec = c.get(f"/runs/{body['run_id']}").json()
        assert rec["status"] == "failed" and "cli died" in rec["error"]
        assert rec["metrics"]["cost_usd"] == 0.01

    def test_end_session_then_runner_end_is_harmless(self, workers_dir, templates_dir, sessions_db, messages_log):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        create_worker(c, "researcher")
        body = c.post("/sessions", json={"worker": "researcher", "task": "x"}).json()
        sid = body["session_id"]

        assert c.post(f"/sessions/{sid}/end").status_code == 200
        runner.on_end(sid, {"outcome": "stopped", "cost_usd": 0.02, "turns": 1, "error": None})

        rec = c.get(f"/runs/{body['run_id']}").json()
        assert rec["status"] == "failed" and rec["error"] == "ended before reporting a result"
        assert rec["metrics"]["cost_usd"] == 0.02
        assert runner.on_end("unknown-session", {"outcome": "stopped"}) is None


class TestWorkersState:
    def test_one_entry_per_worker_with_live_state_where_there_is_one(self, workers_dir, templates_dir, sessions_db, messages_log):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        create_worker(c, "researcher")
        create_worker(c, "writer")
        runner.live = [LiveState("sid-9", "writer", "using_tool", "draft the intro", "Write", 0.12, "2026-10-27T20:00:00+00:00",
                                 {"cost_usd": 0.3, "turns": 4})]

        res = c.get("/workers/state")

        assert res.status_code == 200
        entries = {e["id"]: e for e in res.json()}
        assert set(entries) == {"researcher", "writer"}
        assert entries["researcher"]["status"] == "idle" and entries["researcher"]["session_id"] is None
        w = entries["writer"]
        assert w["status"] == "using_tool" and w["tool"] == "Write" and w["current_task"] == "draft the intro"
        assert w["context_used"] == 0.12 and w["cost_usd"] == 0.3 and w["session_id"] == "sid-9"
        assert all(e["simulated"] is False for e in entries.values())
        assert all(e["status"] in {"idle", "thinking", "using_tool", "waiting", "error"} for e in entries.values())

    def test_state_is_not_shadowed_by_the_worker_route(self, workers_dir, templates_dir, sessions_db, messages_log):
        c = make(workers_dir, templates_dir, sessions_db, messages_log, FakeSdkRunner())

        assert c.get("/workers/state").json() == []
        assert c.get("/workers/nope").status_code == 404


class TestMessageForwarding:
    def _two(self, c, runner):
        create_worker(c, "a")
        create_worker(c, "b")
        a = c.post("/sessions", json={"worker": "a", "task": "x"}).json()["session_id"]
        tok_a = runner.started[-1].token
        b = c.post("/sessions", json={"worker": "b", "task": "y", "may_talk_to": [a]}).json()["session_id"]
        return a, tok_a, b

    def test_a_session_message_is_handed_to_the_target_with_its_sender(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        a, tok_a, b = self._two(c, runner)

        res = c.post(f"/sessions/{b}/messages", json={"text": "storyboard is ready"}, headers={"X-Session-Token": tok_a})

        assert res.status_code == 202 and res.json() == {"accepted": True, "delivered": True}
        assert runner.sent == [(b, f"Message from session {a} (a): storyboard is ready")]
        log = (workers_dir / "b" / "activity.jsonl").read_text(encoding="utf-8")
        assert '"event": "message_in"' in log and '"outcome": "delivered"' in log

    def test_the_host_may_message_any_session_without_a_token(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        _, _, b = self._two(c, runner)

        res = c.post(f"/sessions/{b}/messages", json={"text": "make it shorter"})

        assert res.status_code == 202 and res.json()["delivered"] is True
        assert runner.sent[-1] == (b, "Message from the host: make it shorter")
        assert '"from": "host"' in messages_log.read_text(encoding="utf-8")

    def test_a_session_still_needs_permission_and_a_valid_token(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        a, tok_a, b = self._two(c, runner)
        tok_b = runner.started[-1].token

        # b may not talk to a (a never listed b), a bad token is refused, an unknown target is 404.
        assert c.post(f"/sessions/{a}/messages", json={"text": "hi"}, headers={"X-Session-Token": tok_b}).status_code == 403
        assert c.post(f"/sessions/{b}/messages", json={"text": "hi"}, headers={"X-Session-Token": "nope"}).status_code == 401
        assert c.post("/sessions/ghost/messages", json={"text": "hi"}).status_code == 404
        assert runner.sent == []

    def test_messages_to_an_ended_session_are_409(self, workers_dir, templates_dir, sessions_db, messages_log):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        _, _, b = self._two(c, runner)
        c.post(f"/sessions/{b}/end")

        assert c.post(f"/sessions/{b}/messages", json={"text": "hi"}).status_code == 409
        assert runner.sent == []


class TestEndSessionAuthorisation:
    def test_host_self_and_spawner_may_end_but_nobody_else(self, workers_dir, templates_dir, sessions_db, messages_log):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        create_worker(c, "master")
        create_worker(c, "child")
        create_worker(c, "bystander")
        master = c.post("/sessions", json={"worker": "master", "task": "run"}).json()["session_id"]
        tok_master = runner.started[-1].token
        child = c.post("/sessions", json={"worker": "child", "task": "do"}, headers={"X-Session-Token": tok_master}).json()["session_id"]
        tok_child = runner.started[-1].token
        c.post("/sessions", json={"worker": "bystander", "task": "watch"})
        tok_by = runner.started[-1].token

        assert c.post(f"/sessions/{child}/end", headers={"X-Session-Token": tok_by}).status_code == 403
        assert c.post(f"/sessions/{child}/end", headers={"X-Session-Token": "nope"}).status_code == 401
        assert c.post(f"/sessions/{master}/end", headers={"X-Session-Token": tok_child}).status_code == 403
        assert c.post(f"/sessions/{child}/end", headers={"X-Session-Token": tok_master}).status_code == 200  # spawner
        assert runner.stopped == [child]
        assert c.post(f"/sessions/{master}/end", headers={"X-Session-Token": tok_master}).status_code == 200  # itself
        assert c.post(f"/sessions/{master}/end").status_code == 409  # the host, but it is already over


class TestEventsStream:
    def _events(self, text):
        return [json.loads(line[len("data: "):]) for line in text.splitlines() if line.startswith("data: ")]

    def test_replays_recent_events_then_streams_live_ones(self, workers_dir, templates_dir, sessions_db, messages_log):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        runner.publish({"session_id": "s1", "worker": "writer", "status": "thinking", "tool": None})
        runner.publish({"session_id": "s1", "worker": "writer", "status": "using_tool", "tool": "Write"})

        with c.stream("GET", "/events", params={"limit": 3}) as res:
            assert res.status_code == 200
            assert res.headers["content-type"].startswith("text/event-stream")
            lines = iter(res.iter_lines())
            first = [next(lines) for _ in range(6)]
            runner.publish({"session_id": "s1", "worker": "writer", "status": "waiting", "tool": None})
            rest = list(lines)

        events = self._events("\n".join(first + rest))
        assert [e["status"] for e in events] == ["thinking", "using_tool", "waiting"]
        assert all(line.startswith(("event: state", "data: ", "")) for line in first + rest)
        assert runner.subscribers == []  # unsubscribed when the stream ended

    def test_replay_can_be_turned_off(self, workers_dir, templates_dir, sessions_db, messages_log):
        runner = FakeSdkRunner()
        c = make(workers_dir, templates_dir, sessions_db, messages_log, runner)
        runner.publish({"session_id": "s1", "worker": "writer", "status": "thinking"})

        with c.stream("GET", "/events", params={"limit": 1, "replay": 0}) as res:
            lines = iter(res.iter_lines())
            runner.publish({"session_id": "s2", "worker": "writer", "status": "waiting"})
            text = "\n".join(list(lines))

        assert [e["session_id"] for e in self._events(text)] == ["s2"]

    def test_the_cli_runner_has_an_empty_feed(self):
        from app.runner import CliRunner

        runner = CliRunner(lambda s: [], lambda a, c: "", lambda s: None, lambda: set(), lambda o: o)

        q = runner.subscribe()

        assert list(runner.history) == [] and q.empty()
        runner.unsubscribe(q)  # harmless
