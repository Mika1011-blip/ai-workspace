from tests.test_projects import (  # noqa: F401 -- fixtures shared with the project tests
    SPAWNED,
    STOPPED,
    _reset_fakes,
    client,
    create,
    messages_log,
    projects_dir,
    put_artifact,
    sessions_db,
    templates_dir,
    workers_dir,
)


def test_gallery_page_is_served(client):
    res = client.get("/gallery")

    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Studio gallery" in res.text
    # Status is never colour alone: every state has an icon + label.
    for label in ("awaiting your decision", "published", "failed", "needs input"):
        assert label in res.text


def test_folder_artifacts_list_their_files(client, projects_dir):
    create(client)
    frames = projects_dir / "first-reel" / "artifacts" / "07-render-frames"
    frames.mkdir()
    for i in (2, 1):
        (frames / f"frame-0{i}.jpg").write_bytes(b"\xff\xd8")
    (frames / "notes.txt").write_text("x", encoding="utf-8")
    put_artifact(projects_dir, "first-reel", "01-script.md", "# s")

    arts = {a["path"]: a for a in client.get("/projects/first-reel").json()["artifacts"]}

    assert arts["07-render-frames"]["files"] == ["frame-01.jpg", "frame-02.jpg", "notes.txt"]
    assert arts["01-script.md"]["files"] is None
