import hashlib
import json

from fastapi.testclient import TestClient

from app import sessions_store
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


def record_file(workers_dir, worker, run_id):
    return workers_dir / worker / "runs" / f"{run_id}.json"


def load(workers_dir, worker, run_id):
    return json.loads(record_file(workers_dir, worker, run_id).read_text(encoding="utf-8"))


class TestRecordAtSpawn:
    def test_writes_a_running_record_in_the_workers_folder(self, client, workers_dir):
        create_worker(client, "researcher")

        res = spawn(client, "researcher")

        body = res.json()
        rec = load(workers_dir, "researcher", body["run_id"])
        assert rec["run_id"] == body["run_id"]
        assert rec["run_id"].startswith("researcher-")
        assert rec["run_id"].endswith(f"-{body['session_id']}")
        assert rec["worker"] == "researcher"
        assert rec["session_id"] == body["session_id"]
        assert rec["status"] == "running"
        assert rec["trigger"] == "manual"
        assert rec["attempt"] == 1
        assert rec["ended_at"] is None and rec["result"] is None and rec["error"] is None
        assert rec["metrics"] == {"turns": None, "duration_ms": None, "cost_usd": None}
        assert set(rec["tags"]) == {"worker:researcher", "trigger:manual", "env:local"}

    def test_prompt_version_is_a_hash_of_the_instructions_used(self, client, workers_dir):
        create_worker(client, "researcher")
        instructions = (workers_dir / "researcher" / "CLAUDE.md").read_text(encoding="utf-8")

        run_id = spawn(client, "researcher").json()["run_id"]

        expected = hashlib.sha256(instructions.encode("utf-8")).hexdigest()[:7]
        assert load(workers_dir, "researcher", run_id)["prompt_version"] == expected

    def test_extra_tags_and_trigger_are_recorded(self, client, workers_dir):
        create_worker(client, "researcher")

        run_id = spawn(
            client, "researcher", trigger="schedule", tags=["scope:research", "topic:ai-news"]
        ).json()["run_id"]

        rec = load(workers_dir, "researcher", run_id)
        assert rec["trigger"] == "schedule"
        assert "trigger:schedule" in rec["tags"]
        assert "scope:research" in rec["tags"] and "topic:ai-news" in rec["tags"]

    def test_bad_tag_is_400_and_spawns_nothing(self, client):
        create_worker(client, "researcher")

        unknown_key = spawn(client, "researcher", tags=["mood:happy"])
        bad_value = spawn(client, "researcher", tags=["scope:everything"])
        not_kv = spawn(client, "researcher", tags=["research"])

        for res in (unknown_key, bad_value, not_kv):
            assert res.status_code == 400
            assert res.json()["detail"].startswith("bad_tag")
        assert SPAWNED == []

    def test_bad_trigger_is_400(self, client):
        create_worker(client, "researcher")

        res = spawn(client, "researcher", trigger="cron")

        assert res.status_code == 400
        assert res.json()["detail"] == "bad_trigger"
        assert SPAWNED == []


class TestReportResult:
    def _running(self, client):
        create_worker(client, "researcher")
        body = spawn(client, "researcher").json()
        return body["session_id"], body["run_id"]

    def test_worker_fills_in_its_part(self, client, workers_dir):
        sid, run_id = self._running(client)

        res = client.post(
            f"/sessions/{sid}/result",
            json={
                "status": "success",
                "summary": "5 bullets",
                "tags": ["scope:research", "severity:info"],
                "metrics": {"turns": 6, "cost_usd": 0.07},
            },
            headers=auth(sid),
        )

        assert res.status_code == 200
        rec = load(workers_dir, "researcher", run_id)
        assert rec["status"] == "success"
        assert rec["result"] == {"summary": "5 bullets"}
        assert rec["metrics"]["turns"] == 6 and rec["metrics"]["cost_usd"] == 0.07
        assert rec["metrics"]["duration_ms"] is None  # not ended yet
        assert "scope:research" in rec["tags"] and "severity:info" in rec["tags"]
        assert res.json() == rec

    def test_wrong_token_is_401(self, client):
        sid, _ = self._running(client)

        res = client.post(f"/sessions/{sid}/result", json={"status": "success"})

        assert res.status_code == 401

    def test_unknown_session_is_404(self, client):
        res = client.post("/sessions/nope/result", json={"status": "success"})

        assert res.status_code == 404

    def test_only_a_workers_verdict_is_accepted(self, client):
        sid, _ = self._running(client)

        for status in ("running", "queued", "timeout", "missed", "done"):
            res = client.post(f"/sessions/{sid}/result", json={"status": status}, headers=auth(sid))
            assert res.status_code == 400, status
            assert res.json()["detail"] == "bad_status"

    def test_bad_tag_in_report_is_400_and_changes_nothing(self, client, workers_dir):
        sid, run_id = self._running(client)

        res = client.post(
            f"/sessions/{sid}/result",
            json={"status": "success", "tags": ["mood:great"]},
            headers=auth(sid),
        )

        assert res.status_code == 400
        assert load(workers_dir, "researcher", run_id)["status"] == "running"

    def test_report_after_end_is_409(self, client):
        sid, _ = self._running(client)
        client.post(f"/sessions/{sid}/end")

        res = client.post(f"/sessions/{sid}/result", json={"status": "success"}, headers=auth(sid))

        assert res.status_code == 409


class TestFinalize:
    def test_end_without_a_report_is_failed(self, client, workers_dir):
        create_worker(client, "researcher")
        body = spawn(client, "researcher").json()

        client.post(f"/sessions/{body['session_id']}/end")

        rec = load(workers_dir, "researcher", body["run_id"])
        assert rec["status"] == "failed"
        assert rec["error"] == "ended before reporting a result"
        assert rec["ended_at"] is not None
        assert isinstance(rec["metrics"]["duration_ms"], int) and rec["metrics"]["duration_ms"] >= 0

    def test_end_after_a_report_keeps_the_workers_verdict(self, client, workers_dir):
        create_worker(client, "researcher")
        body = spawn(client, "researcher").json()
        sid = body["session_id"]
        client.post(f"/sessions/{sid}/result", json={"status": "needs_input", "summary": "?"}, headers=auth(sid))

        client.post(f"/sessions/{sid}/end")

        rec = load(workers_dir, "researcher", body["run_id"])
        assert rec["status"] == "needs_input"
        assert rec["error"] is None
        assert rec["ended_at"] is not None and rec["metrics"]["duration_ms"] is not None

    def test_reconciliation_fails_runs_whose_process_vanished(
        self, workers_dir, templates_dir, sessions_db, messages_log
    ):
        first = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log))
        create_worker(first, "researcher")
        body = spawn(first, "researcher").json()

        with TestClient(
            make_app(workers_dir, templates_dir, sessions_db, messages_log, running_ids_fn=lambda: set())
        ):
            pass

        rec = load(workers_dir, "researcher", body["run_id"])
        assert rec["status"] == "failed"
        assert rec["error"] == "process gone before reporting a result"
        assert sessions_store.get_session(sessions_db, body["session_id"])["status"] == "ended"


class TestListRuns:
    def _seed(self, client):
        create_worker(client, "researcher")
        create_worker(client, "writer")
        a = spawn(client, "researcher", tags=["scope:research"]).json()
        b = spawn(client, "researcher", tags=["scope:research"]).json()
        c = spawn(client, "writer", tags=["scope:docs"]).json()
        client.post(f"/sessions/{a['session_id']}/result", json={"status": "failed", "error": "x"}, headers=auth(a["session_id"]))
        client.post(f"/sessions/{b['session_id']}/result", json={"status": "success"}, headers=auth(b["session_id"]))
        return a, b, c

    def test_lists_everything_newest_first_by_default(self, client):
        a, b, c = self._seed(client)

        res = client.get("/runs")

        assert res.status_code == 200
        rows = res.json()
        assert {r["run_id"] for r in rows} == {a["run_id"], b["run_id"], c["run_id"]}
        starts = [r["started_at"] for r in rows]
        assert starts == sorted(starts, reverse=True)

    def test_two_spawns_in_the_same_second_are_distinct_runs(self, client, workers_dir):
        create_worker(client, "researcher")

        first = spawn(client, "researcher").json()
        second = spawn(client, "researcher").json()

        assert first["run_id"] != second["run_id"]
        assert record_file(workers_dir, "researcher", first["run_id"]).is_file()
        assert record_file(workers_dir, "researcher", second["run_id"]).is_file()
        assert len(client.get("/runs", params={"worker": "researcher"}).json()) == 2

    def test_full_returns_whole_records_and_limit_caps_them(self, client):
        a, b, c = self._seed(client)

        rows = client.get("/runs", params={"worker": "researcher"}).json()
        full = client.get("/runs", params={"worker": "researcher", "full": "true"}).json()
        capped = client.get("/runs", params={"full": "true", "limit": 1}).json()

        assert "metrics" not in rows[0]  # the index row
        assert {r["run_id"] for r in full} == {a["run_id"], b["run_id"]}
        assert all("metrics" in r and "result" in r and "tags" in r for r in full)
        assert next(r for r in full if r["run_id"] == a["run_id"])["error"] == "x"
        assert len(capped) == 1 and capped[0]["run_id"] == c["run_id"]
        assert client.get("/runs", params={"limit": 0}).status_code == 422

    def test_filters_narrow(self, client):
        a, b, c = self._seed(client)

        by_worker = client.get("/runs", params={"worker": "writer"}).json()
        failed_research = client.get(
            "/runs", params={"status": "failed", "tag": ["scope:research"]}
        ).json()
        all_research = client.get("/runs", params={"tag": ["scope:research"]}).json()
        none = client.get("/runs", params={"tag": ["scope:research", "scope:docs"]}).json()

        assert [r["run_id"] for r in by_worker] == [c["run_id"]]
        assert [r["run_id"] for r in failed_research] == [a["run_id"]]
        assert {r["run_id"] for r in all_research} == {a["run_id"], b["run_id"]}
        assert none == []

    def test_since_filters_by_start_time(self, client):
        a, _, _ = self._seed(client)

        future = client.get("/runs", params={"since": "2999-01-01T00:00:00Z"}).json()
        past = client.get("/runs", params={"since": "2000-01-01T00:00:00Z"}).json()

        assert future == []
        assert len(past) == 3

    def test_index_rows_point_at_the_files(self, client, workers_dir):
        a, _, _ = self._seed(client)

        row = next(r for r in client.get("/runs").json() if r["run_id"] == a["run_id"])

        assert row["path"] == str(record_file(workers_dir, "researcher", a["run_id"]))
        assert row["status"] == "failed"
        assert row["session_id"] == a["session_id"]
