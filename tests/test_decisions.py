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
    report,
    sessions_db,
    templates_dir,
    workers_dir,
)


def at_first_checkpoint(client, projects_dir):
    make_project(client, mode="guided")
    client.post("/projects/first-reel/start")
    report(client, projects_dir, "success", "script written")
    m = report(client, projects_dir, "success", "hook is fine")
    assert m["status"] == "awaiting_approval"
    return m


def decide(client, decision, **extra):
    return client.post("/projects/first-reel/decision", json={"decision": decision, **extra})


class TestDecisions:
    def test_approve_moves_to_the_next_stage(self, client, projects_dir):
        at_first_checkpoint(client, projects_dir)
        spawned_before = len(SPAWNED)

        res = decide(client, "approve")

        assert res.status_code == 200
        m = manifest(projects_dir)
        assert m["status"] == "running" and m["stage"] == "storyboard" and m["next_stage"] is None
        assert len(SPAWNED) == spawned_before + 1
        assert m["stages"][-1]["worker"] == "storyboarder"

    def test_revise_reruns_the_maker_with_reviewer_and_mika_notes(self, client, projects_dir):
        at_first_checkpoint(client, projects_dir)

        res = decide(client, "revise", notes="make the hook a question")

        assert res.status_code == 200
        m = manifest(projects_dir)
        assert m["status"] == "running" and m["stage"] == "script"
        assert m["stages"][-1]["attempt"] == 2
        assert m["stages"][-1]["notes"] == "hook is fine / make the hook a question"
        assert "make the hook a question" in SPAWNED[-1][0][-1]

    def test_mika_can_revise_more_than_once(self, client, projects_dir):
        at_first_checkpoint(client, projects_dir)
        decide(client, "revise", notes="again")
        report(client, projects_dir, "success")           # script attempt 2
        report(client, projects_dir, "success")           # review -> checkpoint again

        res = decide(client, "revise", notes="and again")

        assert res.status_code == 200
        assert manifest(projects_dir)["stages"][-1]["attempt"] == 3

    def test_skip_moves_on_regardless(self, client, projects_dir):
        make_project(client, mode="guided")
        client.post("/projects/first-reel/start")
        report(client, projects_dir, "success")
        report(client, projects_dir, "needs_input", "not great")   # reviewer unhappy -> script attempt 2
        report(client, projects_dir, "success")
        m = report(client, projects_dir, "success", "ok now")
        assert m["status"] == "awaiting_approval"

        decide(client, "skip")

        assert manifest(projects_dir)["stage"] == "storyboard"

    def test_decisions_are_recorded_with_who_and_what_they_triggered(self, client, projects_dir):
        at_first_checkpoint(client, projects_dir)
        decide(client, "revise", notes="shorter", by="mika")
        report(client, projects_dir, "success")
        report(client, projects_dir, "success")
        decide(client, "approve")

        trail = client.get("/projects/first-reel").json()["decisions"]

        assert [d["decision"] for d in trail] == ["revise", "approve"]
        assert trail[0]["by"] == "mika" and trail[0]["stage"] == "script-review"
        assert trail[0]["notes"] == "shorter" and trail[0]["triggered"] == "script attempt 2"
        assert trail[1]["triggered"] == "storyboard" and trail[1]["at"].endswith("Z")

    def test_a_session_decides_under_its_own_identity(self, client, projects_dir):
        at_first_checkpoint(client, projects_dir)
        create_worker(client, "producer")
        producer = client.post("/sessions", json={"worker": "producer", "task": "run the show"}).json()["session_id"]

        res = client.post(
            "/projects/first-reel/decision", json={"decision": "approve", "by": "someone-else"}, headers=auth(producer)
        )

        assert res.status_code == 200
        assert client.get("/projects/first-reel").json()["decisions"][-1]["by"] == producer

    def test_nothing_to_decide_is_409_and_bad_decision_is_400(self, client, projects_dir):
        make_project(client, mode="guided")

        assert decide(client, "approve").status_code == 409
        client.post("/projects/first-reel/start")
        assert decide(client, "approve").status_code == 409       # a maker is running, no checkpoint yet
        at_first_checkpoint_m = report(client, projects_dir, "success")
        report(client, projects_dir, "success")
        assert decide(client, "maybe").status_code == 400
        assert client.post("/projects/nope/decision", json={"decision": "approve"}).status_code == 404

    def test_switching_to_auto_while_waiting_approves(self, client, projects_dir):
        at_first_checkpoint(client, projects_dir)

        res = client.patch("/projects/first-reel", json={"mode": "auto"})

        assert res.status_code == 200
        m = manifest(projects_dir)
        assert m["mode"] == "auto" and m["status"] == "running" and m["stage"] == "storyboard"
        assert client.get("/projects/first-reel").json()["decisions"][-1]["by"] == "auto"

    def test_auto_mode_then_walks_through_without_stopping(self, client, projects_dir):
        at_first_checkpoint(client, projects_dir)
        client.patch("/projects/first-reel", json={"mode": "auto"})

        for _ in range(6):
            report(client, projects_dir, "success")

        m = manifest(projects_dir)
        assert m["stage"] is None and m["status"] == "published"
