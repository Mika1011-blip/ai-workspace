import json

import pytest
from fastapi.testclient import TestClient

from app import pipeline, projects
from tests.test_sessions import (  # noqa: F401 -- fixtures and fakes shared with the session tests
    SPAWNED,
    SPAWNED_IDS,
    STOPPED,
    _reset_fakes,
    auth,
    create_worker,
    make_app,
    messages_log,
    sessions_db,
    templates_dir,
    workers_dir,
)

STAGE_WORKERS = pipeline.workers_needed()


@pytest.fixture
def projects_dir(tmp_path):
    return tmp_path / "projects"


@pytest.fixture
def client(workers_dir, templates_dir, sessions_db, messages_log, projects_dir):
    c = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, projects_dir=projects_dir))
    for w in STAGE_WORKERS:
        create_worker(c, w)
    return c


def make_project(client, slug="first-reel", mode="auto"):
    res = client.post("/projects", json={"slug": slug, "title": "First reel", "format": "social-short", "mode": mode})
    assert res.status_code == 201, res.json()
    return res.json()


def manifest(projects_dir, slug="first-reel"):
    return json.loads((projects_dir / slug / "project.json").read_text(encoding="utf-8"))


def current_session(projects_dir, slug="first-reel"):
    m = manifest(projects_dir, slug)
    return m["stages"][-1]["session_id"]


def report(client, projects_dir, status, summary=None, slug="first-reel"):
    sid = current_session(projects_dir, slug)
    res = client.post("/sessions/me/result", json={"status": status, "summary": summary}, headers=auth(sid))
    assert res.status_code == 200, res.json()
    return manifest(projects_dir, slug)


def last_spawn_argv():
    return SPAWNED[-1][0]


class TestStart:
    def test_runs_the_first_stage(self, client, projects_dir, sessions_db):
        make_project(client)

        res = client.post("/projects/first-reel/start")

        assert res.status_code == 200
        m = manifest(projects_dir)
        assert m["status"] == "running" and m["stage"] == "script"
        (entry,) = m["stages"]
        assert entry["name"] == "script" and entry["worker"] == "scriptwriter" and entry["attempt"] == 1
        assert entry["session_id"] == SPAWNED_IDS[-1] and entry["status"] == "running"
        assert projects.stage_for_session(sessions_db, entry["session_id"]) == ("first-reel", "script")

    def test_stage_session_is_a_locked_down_worker_with_the_project_artifacts_granted(self, client, projects_dir):
        make_project(client)
        client.post("/projects/first-reel/start")

        argv, cwd = SPAWNED[-1]
        assert cwd.name == "scriptwriter"
        assert str((projects_dir / "first-reel" / "artifacts").resolve()) in argv
        task = argv[-1]
        assert "first-reel" in task and "social-short" in task and "stage 'script'" in task
        assert "report_result" in task and "sidecar" in task
        assert "REVISION" not in task

    def test_stage_run_is_tagged_with_the_project(self, client, projects_dir, workers_dir):
        make_project(client)
        client.post("/projects/first-reel/start")

        runs = client.get("/runs", params={"tag": ["project:first-reel"]}).json()

        assert [r["worker"] for r in runs] == ["scriptwriter"]
        assert runs[0]["trigger"] == "event"

    def test_missing_stage_worker_is_400(self, client, workers_dir):
        make_project(client)
        client.delete("/workers/renderer")

        res = client.post("/projects/first-reel/start")

        assert res.status_code == 400
        assert "renderer" in res.json()["detail"]
        assert SPAWNED == []

    def test_start_while_running_is_409_and_unknown_is_404(self, client):
        make_project(client)
        client.post("/projects/first-reel/start")

        assert client.post("/projects/first-reel/start").status_code == 409
        assert client.post("/projects/nope/start").status_code == 404


class TestGates:
    def test_maker_success_spawns_the_reviewer(self, client, projects_dir):
        make_project(client)
        client.post("/projects/first-reel/start")

        m = report(client, projects_dir, "success", "wrote the script")

        assert m["stage"] == "script-review" and m["status"] == "running"
        assert [e["name"] for e in m["stages"]] == ["script", "script-review"]
        assert m["stages"][0]["status"] == "success" and m["stages"][0]["summary"] == "wrote the script"
        assert "Project 'first-reel'" in last_spawn_argv()[-1] and "stage 'script-review'" in last_spawn_argv()[-1]

    def test_reviewer_needs_input_reruns_the_maker_once_with_notes(self, client, projects_dir):
        make_project(client)
        client.post("/projects/first-reel/start")
        report(client, projects_dir, "success")

        m = report(client, projects_dir, "needs_input", "hook comes too late")

        assert m["stage"] == "script" and m["status"] == "running"
        assert [e["name"] for e in m["stages"]] == ["script", "script-review", "script"]
        assert m["stages"][-1]["attempt"] == 2 and m["stages"][-1]["notes"] == "hook comes too late"
        assert "REVISION REQUESTED" in last_spawn_argv()[-1] and "hook comes too late" in last_spawn_argv()[-1]

    def test_second_needs_input_stops_the_project(self, client, projects_dir):
        make_project(client)
        client.post("/projects/first-reel/start")
        report(client, projects_dir, "success")
        report(client, projects_dir, "needs_input", "too slow")
        report(client, projects_dir, "success")  # revised script
        spawned_before = len(SPAWNED)

        m = report(client, projects_dir, "needs_input", "still too slow")

        assert m["status"] == "needs_input" and m["stage"] == "script-review"
        assert "2 attempts" in m["error"]
        assert len(SPAWNED) == spawned_before

    def test_maker_failure_fails_the_project(self, client, projects_dir):
        make_project(client)
        client.post("/projects/first-reel/start")

        m = report(client, projects_dir, "failed", "could not")

        assert m["status"] == "failed" and "script" in m["error"]

    def test_session_gone_without_report_fails_the_project(self, client, projects_dir):
        make_project(client)
        client.post("/projects/first-reel/start")
        sid = current_session(projects_dir)

        client.post(f"/sessions/{sid}/end")

        m = manifest(projects_dir)
        assert m["status"] == "failed" and "ended before reporting" in m["error"]
        assert m["stages"][-1]["status"] == "failed"

    def test_unrelated_session_report_does_not_touch_projects(self, client, projects_dir, workers_dir):
        make_project(client)
        client.post("/projects/first-reel/start")
        create_worker(client, "bystander")
        sid = client.post("/sessions", json={"worker": "bystander", "task": "x"}).json()["session_id"]

        client.post("/sessions/me/result", json={"status": "success"}, headers=auth(sid))

        assert manifest(projects_dir)["stage"] == "script"


class TestAutoModeEndToEnd:
    def test_walks_every_gate_to_the_publish_step(self, client, projects_dir):
        make_project(client, mode="auto")
        client.post("/projects/first-reel/start")

        seen = []
        for _ in range(8):
            m = manifest(projects_dir)
            seen.append(m["stage"])
            m = report(client, projects_dir, "success", f"{m['stage']} ok")

        assert seen == [
            "script", "script-review", "storyboard", "storyboard-review",
            "assets", "asset-review", "render", "render-review",
        ]
        # Eight worker stages plus the API's render step and publish.
        assert m["stage"] is None and m["status"] == "published"
        assert [e["name"] for e in m["stages"]] == seen[:7] + ["render-step", "render-review", "publish"]
        assert [e["status"] for e in m["stages"]] == ["success"] * 10
        assert len(SPAWNED) == 8

    def test_workers_alternate_maker_and_reviewer(self, client, projects_dir):
        make_project(client, mode="auto")
        client.post("/projects/first-reel/start")
        for _ in range(8):
            report(client, projects_dir, "success")

        workers = [e["worker"] for e in manifest(projects_dir)["stages"] if e["worker"] != "api"]
        assert workers == STAGE_WORKERS


class TestGuidedMode:
    def test_stops_after_each_review_for_a_decision(self, client, projects_dir):
        make_project(client, mode="guided")
        client.post("/projects/first-reel/start")
        report(client, projects_dir, "success")
        spawned_before = len(SPAWNED)

        m = report(client, projects_dir, "success", "looks good")

        assert m["status"] == "awaiting_approval" and m["stage"] == "script-review"
        assert m["next_stage"] == "storyboard"
        assert len(SPAWNED) == spawned_before  # nothing spawned until someone decides

    def test_needs_input_still_revises_in_guided_mode(self, client, projects_dir):
        make_project(client, mode="guided")
        client.post("/projects/first-reel/start")
        report(client, projects_dir, "success")

        m = report(client, projects_dir, "needs_input", "shorter")

        assert m["status"] == "running" and m["stage"] == "script" and m["stages"][-1]["attempt"] == 2
