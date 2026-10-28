import json

import pytest
from fastapi.testclient import TestClient

from tests.test_pipeline import (  # noqa: F401 -- fixtures shared with the pipeline tests
    SPAWNED,
    SPAWNED_IDS,
    STOPPED,
    _reset_fakes,
    auth,
    client,
    create_worker,
    make_project,
    manifest,
    messages_log,
    projects_dir,
    sessions_db,
    templates_dir,
    workers_dir,
)


def assign(client, worker="scriptwriter", task="write a 20 s script about cats", **extra):
    return client.post("/projects/first-reel/tasks", json={"worker": worker, "task": task, **extra})


class TestAssignTask:
    def test_spawns_the_worker_in_the_project_and_logs_the_handoff(self, client, projects_dir):
        make_project(client, mode="auto")

        res = assign(client)

        assert res.status_code == 201, res.json()
        body = res.json()
        argv, cwd = SPAWNED[-1]
        assert cwd.name == "scriptwriter"
        assert str((projects_dir / "first-reel" / "artifacts").resolve()) in argv
        prompt = argv[-1]
        assert "Task from the master: write a 20 s script about cats" in prompt
        assert "sidecar" in prompt and "report_result" in prompt
        m = manifest(projects_dir)
        (h,) = m["handoffs"]
        assert h["worker"] == "scriptwriter" and h["task"] == "write a 20 s script about cats"
        assert h["session_id"] == body["session_id"] and h["run_id"] == body["run_id"]
        assert h["status"] == "running" and h["by"] == "app-master"
        assert m["status"] == "running"
        assert m["stages"] == []  # a hand-off is not a pipeline stage

    def test_run_is_tagged_with_the_project_and_triggered_by_event(self, client):
        make_project(client)
        run_id = assign(client).json()["run_id"]

        run = client.get(f"/runs/{run_id}").json()

        assert run["trigger"] == "event"
        assert {"project:first-reel", "topic:first-reel", "worker:scriptwriter"} <= set(run["tags"])

    def test_report_closes_the_handoff_with_the_summary(self, client, projects_dir):
        make_project(client)
        sid = assign(client).json()["session_id"]

        client.post("/sessions/me/result", json={"status": "success", "summary": "01-script.md, 7 cards"}, headers=auth(sid))

        (h,) = manifest(projects_dir)["handoffs"]
        assert h["status"] == "success" and h["summary"] == "01-script.md, 7 cards" and h["ended_at"] is not None

    def test_session_gone_marks_the_handoff_failed(self, client, projects_dir):
        make_project(client)
        sid = assign(client).json()["session_id"]

        client.post(f"/sessions/{sid}/end")

        (h,) = manifest(projects_dir)["handoffs"]
        assert h["status"] == "failed" and "ended before reporting" in h["summary"]

    def test_spawner_is_the_calling_session(self, client, projects_dir):
        make_project(client)
        create_worker(client, "app-master")
        master = client.post("/sessions", json={"worker": "app-master", "task": "run"}).json()["session_id"]

        res = client.post(
            "/projects/first-reel/tasks", json={"worker": "scriptwriter", "task": "x", "by": "ignored"}, headers=auth(master)
        )

        assert res.status_code == 201
        assert res.json()["spawned_by"] == master
        assert manifest(projects_dir)["handoffs"][-1]["by"] == master

    def test_tool_grants_pass_through(self, client):
        # Directory grants are covered in test_grants.py (they need a repo-relative path).
        make_project(client)

        res = assign(client, tools=["WebFetch"])

        assert res.status_code == 201, res.json()
        argv = SPAWNED[-1][0]
        assert argv[argv.index("--tools") + 1].endswith(",WebFetch")

    def test_unknown_project_or_worker_and_bad_tool(self, client):
        make_project(client)

        assert client.post("/projects/nope/tasks", json={"worker": "scriptwriter", "task": "x"}).status_code == 404
        assert assign(client, worker="nobody").status_code == 404
        assert assign(client, tools=["Bash"]).status_code == 400
        assert SPAWNED == []

    def test_master_can_assign_itself(self, client, projects_dir):
        make_project(client)
        create_worker(client, "app-master")

        res = assign(client, worker="app-master", task="nobody else fits; do it")

        assert res.status_code == 201
        assert SPAWNED[-1][1].name == "app-master"


class TestGetRun:
    def test_returns_the_record_and_404_for_unknown(self, client):
        make_project(client)
        run_id = assign(client).json()["run_id"]

        assert client.get(f"/runs/{run_id}").json()["run_id"] == run_id
        assert client.get("/runs/nope").status_code == 404

    def test_wait_returns_when_the_run_finishes(self, client):
        make_project(client)
        body = assign(client).json()
        client.post("/sessions/me/result", json={"status": "success", "summary": "done"}, headers=auth(body["session_id"]))

        res = client.get(f"/runs/{body['run_id']}", params={"wait": 30})

        assert res.json()["status"] == "success"

    def test_wait_times_out_with_the_running_record(self, client):
        make_project(client)
        body = assign(client).json()

        res = client.get(f"/runs/{body['run_id']}", params={"wait": 0.6})

        assert res.json()["status"] == "running"


class TestRenderProject:
    def test_renders_and_publishes_from_the_render_folder(self, client, projects_dir):
        make_project(client)
        (projects_dir / "first-reel" / "artifacts" / "07-render").mkdir()

        res = client.post("/projects/first-reel/render")

        assert res.status_code == 200, res.json()
        m = res.json()
        assert m["status"] == "published" and m["stage"] is None
        assert [(h["worker"], h["task"], h["status"]) for h in m["handoffs"]] == [
            ("api", "render", "success"), ("api", "publish", "success"),
        ]
        folder = projects_dir / "first-reel"
        assert (folder / "final.mp4").is_file() and (folder / "preview.jpg").is_file()
        assert client.get("/projects").json()[0]["has_final"] is True

    def test_html_renderer_takes_the_explainer_page(self, client, projects_dir):
        make_project(client)
        (projects_dir / "first-reel" / "artifacts" / "explainer.html").write_text("<canvas></canvas>", encoding="utf-8")

        res = client.post("/projects/first-reel/render", params={"renderer": "html"})

        assert res.status_code == 200, res.json()
        m = res.json()
        assert m["renderer"] == "html" and m["status"] == "published"
        assert manifest(projects_dir)["renderer"] == "html"

    def test_html_renderer_with_nothing_to_play_is_409_and_bad_renderer_is_400(self, client):
        make_project(client)

        res = client.post("/projects/first-reel/render", params={"renderer": "html"})
        assert res.status_code == 409 and "explainer.html" in res.json()["detail"]
        assert client.post("/projects/first-reel/render", params={"renderer": "flash"}).status_code == 400

    def test_nothing_to_render_is_409(self, client):
        make_project(client)

        res = client.post("/projects/first-reel/render")

        assert res.status_code == 409
        assert res.json()["detail"].startswith("nothing_to_render")

    def test_render_failure_fails_the_project(self, workers_dir, templates_dir, sessions_db, messages_log, projects_dir):
        from tests.test_sessions import make_app

        def broken(argv):
            return (1, "ffmpeg: plan has no shots") if argv[-1] == "render" else (0, "")

        c = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, projects_dir=projects_dir, render_run=broken))
        make_project(c)
        (projects_dir / "first-reel" / "artifacts" / "07-render").mkdir()

        res = c.post("/projects/first-reel/render")

        assert res.status_code == 502
        m = manifest(projects_dir)
        assert m["status"] == "failed" and "plan has no shots" in m["error"]
        assert m["handoffs"][-1]["task"] == "render" and m["handoffs"][-1]["status"] == "failed"


class TestProtectedMaster:
    def test_app_master_cannot_be_deleted(self, client, workers_dir):
        create_worker(client, "app-master")

        res = client.delete("/workers/app-master")

        assert res.status_code == 403
        assert res.json()["detail"].startswith("protected")
        assert (workers_dir / "app-master" / "CLAUDE.md").is_file()
