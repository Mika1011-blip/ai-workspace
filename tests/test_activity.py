import json

from fastapi.testclient import TestClient

from tests.test_sessions import (  # noqa: F401 -- fixtures and fakes shared with the session tests
    SPAWNED,
    STOPPED,
    _reset_fakes,
    auth,
    client,
    create_worker,
    make_app,
    messages_log,
    sessions_db,
    spawn,
    templates_dir,
    workers_dir,
)


def events(workers_dir, worker):
    path = workers_dir / worker / "activity.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def kinds(workers_dir, worker):
    return [e["event"] for e in events(workers_dir, worker)]


class TestTimeline:
    def test_spawn_is_the_first_event(self, client, workers_dir):
        create_worker(client, "researcher")

        body = spawn(client, "researcher", task="summarize", trigger="schedule").json()

        (first,) = events(workers_dir, "researcher")
        assert first["event"] == "spawned"
        assert first["session_id"] == body["session_id"]
        assert first["run_id"] == body["run_id"]
        assert first["trigger"] == "schedule"
        assert first["task"] == "summarize"
        assert first["at"].endswith("Z")

    def test_report_and_end_are_logged_with_the_runs_status(self, client, workers_dir):
        create_worker(client, "researcher")
        body = spawn(client, "researcher").json()
        sid = body["session_id"]

        client.post(f"/sessions/{sid}/result", json={"status": "success"}, headers=auth(sid))
        client.post(f"/sessions/{sid}/end")

        evs = events(workers_dir, "researcher")
        assert [e["event"] for e in evs] == ["spawned", "result_reported", "ended"]
        assert evs[1]["status"] == "success" and evs[1]["run_id"] == body["run_id"]
        assert evs[2]["status"] == "success" and evs[2]["session_id"] == sid

    def test_end_without_report_logs_failed(self, client, workers_dir):
        create_worker(client, "researcher")
        sid = spawn(client, "researcher").json()["session_id"]

        client.post(f"/sessions/{sid}/end")

        assert events(workers_dir, "researcher")[-1]["status"] == "failed"

    def test_reconciliation_is_logged(self, workers_dir, templates_dir, sessions_db, messages_log):
        first = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log))
        create_worker(first, "researcher")
        sid = spawn(first, "researcher").json()["session_id"]

        with TestClient(
            make_app(workers_dir, templates_dir, sessions_db, messages_log, running_ids_fn=lambda: set())
        ):
            pass

        last = events(workers_dir, "researcher")[-1]
        assert last["event"] == "reconciled"
        assert last["session_id"] == sid
        assert last["status"] == "failed"
        assert last["reason"] == "process gone"


class TestMessages:
    def _pair(self, client):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        a = spawn(client, "researcher", may_talk_to=[]).json()["session_id"]
        b = spawn(client, "writer", may_talk_to=[a]).json()["session_id"]
        return a, b

    def test_accepted_message_appears_on_both_sides(self, client, workers_dir):
        a, b = self._pair(client)

        client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"}, headers=auth(a))

        out = events(workers_dir, "researcher")[-1]
        inc = events(workers_dir, "writer")[-1]
        assert out == {**out, "event": "message_out", "to": b, "outcome": "accepted"}
        assert inc == {**inc, "event": "message_in", "from": a, "outcome": "accepted"}

    def test_refusals_are_logged_too(self, client, workers_dir):
        a, b = self._pair(client)

        client.post(f"/sessions/{a}/messages", json={"from": b, "text": "hi"}, headers=auth(b))  # a doesn't list b
        client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"})  # no token

        researcher = [e for e in events(workers_dir, "researcher") if e["event"].startswith("message")]
        assert [e["outcome"] for e in researcher] == ["not_allowed", "bad_token"]
        assert researcher[0]["event"] == "message_in" and researcher[0]["from"] == b
        assert researcher[1]["event"] == "message_out" and researcher[1]["to"] == b

    def test_messages_still_go_to_the_global_log(self, client, messages_log):
        a, b = self._pair(client)

        client.post(f"/sessions/{b}/messages", json={"from": a, "text": "hi"}, headers=auth(a))

        assert '"outcome": "accepted"' in messages_log.read_text(encoding="utf-8")


class TestReadEndpoint:
    def test_returns_oldest_first_with_limit(self, client):
        create_worker(client, "researcher")
        sid = spawn(client, "researcher").json()["session_id"]
        client.post(f"/sessions/{sid}/result", json={"status": "success"}, headers=auth(sid))
        client.post(f"/sessions/{sid}/end")

        full = client.get("/workers/researcher/activity").json()
        last_two = client.get("/workers/researcher/activity", params={"limit": 2}).json()

        assert [e["event"] for e in full] == ["spawned", "result_reported", "ended"]
        assert [e["event"] for e in last_two] == ["result_reported", "ended"]

    def test_empty_for_a_worker_that_never_ran(self, client):
        create_worker(client, "researcher")

        assert client.get("/workers/researcher/activity").json() == []

    def test_unknown_worker_is_404_and_bad_name_is_400(self, client):
        assert client.get("/workers/nope/activity").status_code == 404
        assert client.get("/workers/Bad%20Name/activity").status_code == 400
