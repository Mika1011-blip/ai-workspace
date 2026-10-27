import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import sessions_store
from app.main import create_app

SPAWNED = []      # (argv, cwd) per spawn, in order
SPAWNED_IDS = []  # the id the fake CLI printed for each, same order
STOPPED = []


def fake_spawn_fn(argv, cwd):
    # Stands in for `claude --bg ...`: records the command and prints what
    # the real CLI prints. Like the real one, it picks the id itself.
    SPAWNED.append((argv, cwd))
    sid = f"{len(SPAWNED):08x}"
    SPAWNED_IDS.append(sid)
    return f"backgrounded · {sid} · {argv[argv.index('--name') + 1]}\n"


def fake_stop_fn(session_id):
    STOPPED.append(session_id)


@pytest.fixture(autouse=True)
def _reset_fakes():
    SPAWNED.clear()
    SPAWNED_IDS.clear()
    STOPPED.clear()


@pytest.fixture
def workers_dir(tmp_path):
    return tmp_path / "workers"


@pytest.fixture
def templates_dir(tmp_path):
    return tmp_path / "worker_templates"


@pytest.fixture
def sessions_db(tmp_path):
    return tmp_path / "sessions.db"


@pytest.fixture
def messages_log(tmp_path):
    return tmp_path / "messages.jsonl"


def fake_render_run(argv):
    # Stands in for `docker run` on a renderer image: produces the files the
    # real images would, so pipelines can reach `published` in tests.
    from pathlib import Path

    if argv[:2] == ["docker", "image"]:
        return 0, ""
    project = Path(argv[argv.index("-v") + 1].split(":/project")[0])
    cmd = argv[-1]
    if cmd == "render":
        (project / "artifacts" / "final-candidate.mp4").write_bytes(b"candidate")
    elif cmd == "frames":
        (project / "artifacts" / "07-render-frames").mkdir(exist_ok=True)
    elif cmd == "publish":
        (project / "final.mp4").write_bytes(b"final")
        (project / "preview.jpg").write_bytes(b"\xff\xd8")
    return 0, f"{cmd} ok"


def make_app(workers_dir, templates_dir, sessions_db, messages_log, **overrides):
    kwargs = dict(
        workers_dir=workers_dir,
        templates_dir=templates_dir,
        sessions_db=sessions_db,
        messages_log=messages_log,
        spawn_fn=fake_spawn_fn,
        stop_fn=fake_stop_fn,
        running_ids_fn=lambda: set(),
        render_run=fake_render_run,
    )
    kwargs.update(overrides)
    return create_app(**kwargs)


@pytest.fixture
def client(workers_dir, templates_dir, sessions_db, messages_log):
    return TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log))


def create_worker(client, name):
    return client.post("/workers", json={"name": name})


def spawn(client, worker, task="do something", **extra):
    return client.post("/sessions", json={"worker": worker, "task": task, **extra})


def mcp_env_of(session_id):
    argv, _ = SPAWNED[SPAWNED_IDS.index(session_id)]
    mcp = json.loads(argv[argv.index("--mcp-config") + 1])
    return mcp["mcpServers"]["ai-workspace"]["env"]


def auth(session_id):
    # What the spawned session's MCP server sends: the token the API put in
    # its env, and nowhere else.
    return {"X-Session-Token": mcp_env_of(session_id)["SESSION_TOKEN"]}


class TestSpawnSession:
    def test_spawns_a_live_session(self, client):
        create_worker(client, "researcher")

        res = spawn(client, "researcher")

        assert res.status_code == 201
        body = res.json()
        # The id is whatever Claude Code printed -- it assigns its own.
        assert body["session_id"] == SPAWNED_IDS[0]
        assert "--session-id" not in SPAWNED[0][0]
        assert body["worker"] == "researcher"
        assert body["status"] == "live"
        assert body["ended_at"] is None

    def test_unknown_worker_is_404(self, client):
        res = spawn(client, "does-not-exist")

        assert res.status_code == 404

    def test_invalid_worker_name_is_400(self, client):
        res = spawn(client, "Bad Name")

        assert res.status_code == 400

    def test_disabled_spawning_is_503_and_registers_nothing(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        # What Docker runs: the image has no `claude` CLI, so compose sets
        # SPAWN_ENABLED=false and the endpoint must refuse cleanly.
        app = make_app(workers_dir, templates_dir, sessions_db, messages_log, spawn_enabled=False)
        client = TestClient(app)
        create_worker(client, "researcher")

        res = spawn(client, "researcher")

        assert res.status_code == 503
        assert res.json()["detail"] == "spawning_disabled"
        assert SPAWNED == []


class TestSpawnLockdown:
    """The wall (docs/comms-protocol.md §5), as the API puts it on the
    command line of every app session it starts."""

    def _spawn_argv(self, client, workers_dir):
        create_worker(client, "researcher")
        res = spawn(client, "researcher", task="summarize")
        assert res.status_code == 201
        argv, cwd = SPAWNED[0]
        return res.json()["session_id"], argv, cwd

    def test_runs_in_the_workers_own_folder(self, client, workers_dir):
        _, argv, cwd = self._spawn_argv(client, workers_dir)

        assert cwd == workers_dir / "researcher"
        assert argv[-1] == "Read CLAUDE.md and ../_shared/COMMS.md, then: summarize"

    def test_restricted_strict_mcp_and_no_prompts(self, client, workers_dir):
        _, argv, _ = self._spawn_argv(client, workers_dir)

        assert "--bg" in argv
        assert "--restricted" in argv
        assert "--strict-mcp-config" in argv
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert "bypassPermissions" not in argv

    def test_claude_code_messaging_is_closed(self, client, workers_dir):
        _, argv, _ = self._spawn_argv(client, workers_dir)
        settings = json.loads(argv[argv.index("--settings") + 1])

        for tool in ("SendMessage", "ListAgents", "Bash"):
            assert tool in settings["permissions"]["deny"]
        assert settings["crossSessionInbound"] == "refuse"
        assert "mcp__ai-workspace__*" in settings["permissions"]["allow"]

    def test_may_write_in_its_own_folder_but_not_in_shared(self, client, workers_dir):
        _, argv, _ = self._spawn_argv(client, workers_dir)
        settings = json.loads(argv[argv.index("--settings") + 1])
        shared = "//" + (workers_dir / "_shared").resolve().as_posix().lstrip("/")

        # --restricted already confines the file tools to cwd + --add-dir; this
        # grants writing there, then takes _shared back out of the writable set.
        assert "Edit" in settings["permissions"]["allow"]
        assert "Write" in settings["permissions"]["allow"]
        assert f"Edit({shared}/**)" in settings["permissions"]["deny"]
        assert f"Write({shared}/**)" in settings["permissions"]["deny"]
        assert "Edit" not in settings["permissions"]["deny"]
        assert "Write" not in settings["permissions"]["deny"]
        # Without this, a background session in a git repo refuses every
        # write until EnterWorktree -- a tool it doesn't have. Verified live.
        assert settings["worktree"] == {"bgIsolation": "none"}

        # The spec's on-disk settings.json says the same thing.
        written = json.loads(
            (workers_dir / "researcher" / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        assert written == settings

    def test_only_our_mcp_server_identified_by_token_alone(self, client, workers_dir):
        sid, argv, _ = self._spawn_argv(client, workers_dir)
        mcp = json.loads(argv[argv.index("--mcp-config") + 1])

        assert list(mcp["mcpServers"]) == ["ai-workspace"]
        server = mcp["mcpServers"]["ai-workspace"]
        # No SESSION_ID: the id isn't known before launch, the token is the identity.
        assert set(server["env"]) == {"SESSION_TOKEN", "WORKSPACE_API_URL"}
        assert server["env"]["WORKSPACE_API_URL"].startswith("http")
        assert server["args"][0].endswith("workspace_server.py")

    def test_token_goes_only_to_the_sessions_mcp_env(self, client, workers_dir, sessions_db):
        sid, argv, _ = self._spawn_argv(client, workers_dir)
        token = mcp_env_of(sid)["SESSION_TOKEN"]

        assert len(token) >= 32
        # Not in the API response, and only its hash in the registry.
        assert "token" not in client.get("/sessions", params={"caller": sid}, headers=auth(sid)).json()[0]
        stored = sessions_store.get_session(sessions_db, sid)["token_hash"]
        assert stored != token and len(stored) == 64

    def test_every_session_gets_its_own_token(self, client, workers_dir):
        create_worker(client, "researcher")
        a = spawn(client, "researcher").json()["session_id"]
        b = spawn(client, "researcher").json()["session_id"]

        assert mcp_env_of(a)["SESSION_TOKEN"] != mcp_env_of(b)["SESSION_TOKEN"]

    def test_shared_folder_is_the_only_extra_directory(self, client, workers_dir):
        _, argv, _ = self._spawn_argv(client, workers_dir)

        assert argv.count("--add-dir") == 1
        assert argv[argv.index("--add-dir") + 1] == str(workers_dir / "_shared")
        assert (workers_dir / "_shared").is_dir()

    def test_writes_the_specs_settings_file_once(self, client, workers_dir):
        self._spawn_argv(client, workers_dir)
        settings_file = workers_dir / "researcher" / ".claude" / "settings.json"
        assert settings_file.is_file()
        written = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "SendMessage" in written["permissions"]["deny"]

        # A hand-curated file (app-master's case) is never clobbered.
        settings_file.write_text('{"permissions": {"allow": ["Task"]}}', encoding="utf-8")
        spawn(client, "researcher")

        assert json.loads(settings_file.read_text(encoding="utf-8")) == {
            "permissions": {"allow": ["Task"]}
        }

    def test_unparsable_claude_output_is_500_and_registers_nothing(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        def garbled_spawn(argv, cwd):
            return "something went wrong\n"

        client = TestClient(
            make_app(workers_dir, templates_dir, sessions_db, messages_log, spawn_fn=garbled_spawn),
            raise_server_exceptions=False,
        )
        create_worker(client, "researcher")

        res = spawn(client, "researcher")

        assert res.status_code == 500
        assert client.get("/runs").json() == []


class TestIdentityByToken:
    """A worker never knows its own id; the token alone says who it is."""

    def _two(self, client):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        a = spawn(client, "researcher", may_talk_to=[]).json()["session_id"]
        b = spawn(client, "writer", may_talk_to=[a]).json()["session_id"]
        return a, b

    def test_list_sessions_without_caller(self, client):
        a, b = self._two(client)

        res = client.get("/sessions", headers=auth(b))

        assert res.status_code == 200
        assert {s["session_id"] for s in res.json()} == {a, b}

    def test_list_sessions_with_no_or_unknown_token_is_401(self, client):
        self._two(client)

        assert client.get("/sessions").status_code == 401
        assert client.get("/sessions", headers={"X-Session-Token": "nope"}).status_code == 401

    def test_caller_that_disagrees_with_token_is_401(self, client):
        a, b = self._two(client)

        res = client.get("/sessions", params={"caller": a}, headers=auth(b))

        assert res.status_code == 401

    def test_send_without_from(self, client, messages_log):
        a, b = self._two(client)

        res = client.post(f"/sessions/{b}/messages", json={"text": "hi"}, headers=auth(a))

        assert res.status_code == 202
        assert f'"from": "{a}"' in messages_log.read_text(encoding="utf-8")

    def test_from_that_disagrees_with_token_is_401(self, client):
        a, b = self._two(client)

        res = client.post(f"/sessions/{b}/messages", json={"from": b, "text": "hi"}, headers=auth(a))

        assert res.status_code == 401

    def test_report_as_me(self, client, workers_dir):
        a, _ = self._two(client)

        res = client.post("/sessions/me/result", json={"status": "success", "summary": "ok"}, headers=auth(a))

        assert res.status_code == 200
        assert res.json()["session_id"] == a and res.json()["status"] == "success"

    def test_report_as_me_without_token_is_401(self, client):
        self._two(client)

        assert client.post("/sessions/me/result", json={"status": "success"}).status_code == 401

    def test_spawner_is_recorded_from_its_token(self, client):
        create_worker(client, "producer")
        create_worker(client, "scriptwriter")
        producer = spawn(client, "producer").json()["session_id"]

        child = client.post(
            "/sessions", json={"worker": "scriptwriter", "task": "write"}, headers=auth(producer)
        ).json()

        assert child["spawned_by"] == producer


class TestListSessions:
    def test_unknown_caller_is_404(self, client):
        res = client.get("/sessions", params={"caller": "no-such-id"})

        assert res.status_code == 404

    def test_returns_only_what_caller_may_reach(self, client, sessions_db):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        create_worker(client, "reviewer")

        a = spawn(client, "researcher", may_talk_to=[]).json()["session_id"]
        b = spawn(client, "writer", may_talk_to=[a]).json()["session_id"]
        spawn(client, "reviewer", may_talk_to=[])  # not reachable from b

        res = client.get("/sessions", params={"caller": b}, headers=auth(b))

        assert res.status_code == 200
        ids = {s["session_id"] for s in res.json()}
        assert ids == {b, a}
        assert all("token_hash" not in s and "token" not in s for s in res.json())

    def test_wrong_or_missing_token_is_401(self, client):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        a = spawn(client, "researcher").json()["session_id"]
        b = spawn(client, "writer").json()["session_id"]

        missing = client.get("/sessions", params={"caller": b})
        someone_elses = client.get("/sessions", params={"caller": b}, headers=auth(a))

        assert missing.status_code == 401
        assert someone_elses.status_code == 401
        assert someone_elses.json()["detail"] == "bad_token"


class TestSendMessage:
    def _two_live_sessions(self, client):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        a = spawn(client, "researcher", may_talk_to=[]).json()["session_id"]
        b = spawn(client, "writer", may_talk_to=[a]).json()["session_id"]
        return a, b

    def test_delivers_when_allowed(self, client):
        a, b = self._two_live_sessions(client)

        res = client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"}, headers=auth(a))

        assert res.status_code == 202
        assert res.json() == {"accepted": True}

    def test_impersonating_a_sender_is_401_and_logged(self, client, messages_log):
        # `from` says "a", but the token is b's (or nobody's): the whole point
        # of the token is that `from` is otherwise just a claim.
        a, b = self._two_live_sessions(client)

        with_b = client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"}, headers=auth(b))
        with_none = client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"})

        assert with_b.status_code == 401
        assert with_none.status_code == 401
        assert with_b.json()["detail"] == "bad_token"
        assert messages_log.read_text(encoding="utf-8").count('"outcome": "bad_token"') == 2

    def test_unknown_target_is_404(self, client):
        a, _ = self._two_live_sessions(client)

        res = client.post("/sessions/no-such-id/messages", json={"from": a, "text": "hi"}, headers=auth(a))

        assert res.status_code == 404
        assert res.json()["detail"] == "unknown_session"

    def test_unknown_sender_is_404(self, client):
        _, b = self._two_live_sessions(client)

        res = client.post(f"/sessions/{b}/messages", json={"from": "no-such-id", "text": "hi"})

        assert res.status_code == 404
        assert res.json()["detail"] == "unknown_session"

    def test_crew_session_id_is_unknown_to_the_app(self, client):
        # Crew and app registries are entirely separate -- a crew session id
        # was never inserted here, so it's indistinguishable from any other
        # unknown id. This *is* the crew/app wall: there's nothing special
        # to refuse, because there's nothing to find.
        _, b = self._two_live_sessions(client)

        res = client.post(f"/sessions/{b}/messages", json={"from": "7c5dcf5d", "text": "hi"})

        assert res.status_code == 404
        assert res.json()["detail"] == "unknown_session"

    def test_ended_session_is_409(self, client, sessions_db):
        a, b = self._two_live_sessions(client)
        sessions_store.mark_ended(sessions_db, b, datetime.now(timezone.utc).isoformat())

        res = client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"}, headers=auth(a))

        assert res.status_code == 409
        assert res.json()["detail"] == "session_ended"

    def test_sender_not_in_may_talk_to_is_403(self, client):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        a = spawn(client, "researcher", may_talk_to=[]).json()["session_id"]
        b = spawn(client, "writer", may_talk_to=[]).json()["session_id"]  # doesn't list a

        res = client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"}, headers=auth(a))

        assert res.status_code == 403
        assert res.json()["detail"] == "not_allowed"

    def test_accepted_message_is_logged(self, client, messages_log):
        a, b = self._two_live_sessions(client)

        client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"}, headers=auth(a))

        lines = messages_log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert f'"from": "{a}"' in lines[0]
        assert f'"to": "{b}"' in lines[0]
        assert '"outcome": "accepted"' in lines[0]


class TestEndSession:
    def test_ends_a_live_session_and_stops_its_process(self, client):
        create_worker(client, "researcher")
        sid = spawn(client, "researcher").json()["session_id"]

        res = client.post(f"/sessions/{sid}/end")

        assert res.status_code == 200
        assert res.json()["status"] == "ended"
        assert res.json()["ended_at"] is not None
        assert STOPPED == [sid]

    def test_unknown_session_is_404(self, client):
        res = client.post("/sessions/no-such-id/end")

        assert res.status_code == 404
        assert res.json()["detail"] == "unknown_session"

    def test_already_ended_is_409_and_not_stopped_twice(self, client):
        create_worker(client, "researcher")
        sid = spawn(client, "researcher").json()["session_id"]
        client.post(f"/sessions/{sid}/end")

        res = client.post(f"/sessions/{sid}/end")

        assert res.status_code == 409
        assert res.json()["detail"] == "session_ended"
        assert STOPPED == [sid]

    def test_ended_session_can_no_longer_be_messaged(self, client):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        a = spawn(client, "researcher", may_talk_to=[]).json()["session_id"]
        b = spawn(client, "writer", may_talk_to=[a]).json()["session_id"]
        client.post(f"/sessions/{b}/end")

        res = client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"}, headers=auth(a))

        assert res.status_code == 409

    def test_disabled_spawning_still_marks_ended_without_stopping(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        # Seed a live row with a host-side app, then end it from a
        # Docker-like app that has no claude CLI to stop the process.
        host = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log))
        create_worker(host, "researcher")
        sid = spawn(host, "researcher").json()["session_id"]
        docker = TestClient(
            make_app(workers_dir, templates_dir, sessions_db, messages_log, spawn_enabled=False)
        )

        res = docker.post(f"/sessions/{sid}/end")

        assert res.status_code == 200
        assert STOPPED == []


class TestSchemaMigration:
    def test_old_agent_column_is_renamed_to_worker(self, tmp_path):
        import sqlite3

        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, agent TEXT NOT NULL, "
            "status TEXT NOT NULL, spawned_by TEXT, started_at TEXT NOT NULL, "
            "ended_at TEXT, may_talk_to TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO sessions VALUES ('abc12345', 'researcher', 'live', NULL, 't0', NULL, '[]')"
        )
        conn.commit()
        conn.close()

        sessions_store.init_db(db)

        columns = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(sessions)")]
        assert "worker" in columns and "agent" not in columns and "token_hash" in columns
        assert sessions_store.get_session(db, "abc12345")["worker"] == "researcher"


class TestStartupReconciliation:
    def test_live_rows_not_running_anymore_are_closed(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        first = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log))
        create_worker(first, "researcher")
        create_worker(first, "writer")
        keep = spawn(first, "researcher").json()["session_id"]
        gone = spawn(first, "writer").json()["session_id"]

        # New machine / restart: only `keep` is still running. Entering the
        # client runs the app's startup, which is where reconciliation lives.
        with TestClient(
            make_app(workers_dir, templates_dir, sessions_db, messages_log, running_ids_fn=lambda: {keep})
        ):
            pass

        assert sessions_store.get_session(sessions_db, keep)["status"] == "live"
        assert sessions_store.get_session(sessions_db, gone)["status"] == "ended"
        assert sessions_store.get_session(sessions_db, gone)["ended_at"] is not None

    def test_skipped_when_running_set_is_unknown(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        # No claude CLI / command failed -> None. Must NOT be treated as
        # "nothing is running", or every live session would be closed.
        first = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log))
        create_worker(first, "researcher")
        sid = spawn(first, "researcher").json()["session_id"]

        with TestClient(
            make_app(workers_dir, templates_dir, sessions_db, messages_log, running_ids_fn=lambda: None)
        ):
            pass

        assert sessions_store.get_session(sessions_db, sid)["status"] == "live"

    def test_skipped_when_spawning_is_disabled(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        first = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log))
        create_worker(first, "researcher")
        sid = spawn(first, "researcher").json()["session_id"]

        with TestClient(
            make_app(
                workers_dir, templates_dir, sessions_db, messages_log,
                spawn_enabled=False, running_ids_fn=lambda: set(),
            )
        ):
            pass

        assert sessions_store.get_session(sessions_db, sid)["status"] == "live"
