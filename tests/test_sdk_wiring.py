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
