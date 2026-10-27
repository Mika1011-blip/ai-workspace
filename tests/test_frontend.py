"""Serving the React app (frontend/dist) at /app."""

from fastapi.testclient import TestClient

from tests.test_sessions import (  # noqa: F401 -- fixtures shared with the session tests
    SPAWNED,
    STOPPED,
    _reset_fakes,
    make_app,
    messages_log,
    sessions_db,
    templates_dir,
    workers_dir,
)


def built(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>AI office</title><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log('app')", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    return dist


def test_serves_the_built_app_and_its_assets(workers_dir, templates_dir, sessions_db, messages_log, tmp_path):
    c = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, frontend_dist=built(tmp_path)))

    assert "AI office" in c.get("/app").text
    assert c.get("/app/assets/index-abc.js").text == "console.log('app')"
    assert c.get("/app/assets/index-abc.js").headers["content-type"].startswith(("text/javascript", "application/javascript"))


def test_unknown_paths_fall_back_to_the_app_and_cannot_escape_dist(workers_dir, templates_dir, sessions_db, messages_log, tmp_path):
    c = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, frontend_dist=built(tmp_path)))

    assert "AI office" in c.get("/app/workers/renderer").text  # the app owns its routes
    res = c.get("/app/../secret.txt")
    assert "nope" not in res.text
    res = c.get("/app/%2e%2e/secret.txt")
    assert "nope" not in res.text


def test_503_until_built(workers_dir, templates_dir, sessions_db, messages_log, tmp_path):
    c = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, frontend_dist=tmp_path / "missing"))

    res = c.get("/app")

    assert res.status_code == 503
    assert res.json()["detail"].startswith("frontend_not_built")
