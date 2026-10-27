from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import sessions_store
from app.main import create_app

NEXT_ID = {"n": 0}


def fake_spawn_fn(agent, task, agent_folder):
    NEXT_ID["n"] += 1
    return f"sess-{NEXT_ID['n']}"


@pytest.fixture(autouse=True)
def _reset_fake_ids():
    NEXT_ID["n"] = 0


@pytest.fixture
def agents_dir(tmp_path):
    return tmp_path / "agents"


@pytest.fixture
def templates_dir(tmp_path):
    return tmp_path / "agent_templates"


@pytest.fixture
def sessions_db(tmp_path):
    return tmp_path / "sessions.db"


@pytest.fixture
def messages_log(tmp_path):
    return tmp_path / "messages.jsonl"


@pytest.fixture
def client(agents_dir, templates_dir, sessions_db, messages_log):
    app = create_app(
        agents_dir=agents_dir,
        templates_dir=templates_dir,
        sessions_db=sessions_db,
        messages_log=messages_log,
        spawn_fn=fake_spawn_fn,
    )
    return TestClient(app)


def create_agent(client, name):
    return client.post("/agents", json={"name": name})


def spawn(client, agent, task="do something", **extra):
    return client.post("/sessions", json={"agent": agent, "task": task, **extra})


class TestSpawnSession:
    def test_spawns_a_live_session(self, client):
        create_agent(client, "researcher")

        res = spawn(client, "researcher")

        assert res.status_code == 201
        body = res.json()
        assert body["session_id"] == "sess-1"
        assert body["agent"] == "researcher"
        assert body["status"] == "live"
        assert body["ended_at"] is None

    def test_unknown_agent_is_404(self, client):
        res = spawn(client, "does-not-exist")

        assert res.status_code == 404

    def test_invalid_agent_name_is_400(self, client):
        res = spawn(client, "Bad Name")

        assert res.status_code == 400


class TestListSessions:
    def test_unknown_caller_is_404(self, client):
        res = client.get("/sessions", params={"caller": "no-such-id"})

        assert res.status_code == 404

    def test_returns_only_what_caller_may_reach(self, client, sessions_db):
        create_agent(client, "researcher")
        create_agent(client, "writer")
        create_agent(client, "reviewer")

        a = spawn(client, "researcher", may_talk_to=[]).json()["session_id"]
        b = spawn(client, "writer", may_talk_to=[a]).json()["session_id"]
        spawn(client, "reviewer", may_talk_to=[])  # not reachable from b

        res = client.get("/sessions", params={"caller": b})

        assert res.status_code == 200
        ids = {s["session_id"] for s in res.json()}
        assert ids == {b, a}


class TestSendMessage:
    def _two_live_sessions(self, client):
        create_agent(client, "researcher")
        create_agent(client, "writer")
        a = spawn(client, "researcher", may_talk_to=[]).json()["session_id"]
        b = spawn(client, "writer", may_talk_to=[a]).json()["session_id"]
        return a, b

    def test_delivers_when_allowed(self, client):
        a, b = self._two_live_sessions(client)

        res = client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"})

        assert res.status_code == 202
        assert res.json() == {"delivered": True}

    def test_unknown_target_is_404(self, client):
        a, _ = self._two_live_sessions(client)

        res = client.post("/sessions/no-such-id/messages", json={"from": a, "text": "hi"})

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

        res = client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"})

        assert res.status_code == 409
        assert res.json()["detail"] == "session_ended"

    def test_sender_not_in_may_talk_to_is_403(self, client):
        create_agent(client, "researcher")
        create_agent(client, "writer")
        a = spawn(client, "researcher", may_talk_to=[]).json()["session_id"]
        b = spawn(client, "writer", may_talk_to=[]).json()["session_id"]  # doesn't list a

        res = client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"})

        assert res.status_code == 403
        assert res.json()["detail"] == "not_allowed"

    def test_delivered_message_is_logged(self, client, messages_log):
        a, b = self._two_live_sessions(client)

        client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"})

        lines = messages_log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert f'"from": "{a}"' in lines[0]
        assert f'"to": "{b}"' in lines[0]
        assert '"outcome": "delivered"' in lines[0]
