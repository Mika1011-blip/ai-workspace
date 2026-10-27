import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app import projects
from tests.test_sessions import (  # noqa: F401 -- fixtures and fakes shared with the session tests
    SPAWNED,
    STOPPED,
    _reset_fakes,
    make_app,
    messages_log,
    sessions_db,
    templates_dir,
    workers_dir,
)


@pytest.fixture
def projects_dir(tmp_path):
    return tmp_path / "projects"


@pytest.fixture
def client(workers_dir, templates_dir, sessions_db, messages_log, projects_dir):
    return TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, projects_dir=projects_dir))


def create(client, slug="first-reel", **extra):
    return client.post("/projects", json={"slug": slug, "title": "First reel", "format": "social-short", **extra})


def put_artifact(projects_dir, slug, name, content, sidecar=None):
    path = projects_dir / slug / "artifacts" / name
    path.write_text(content, encoding="utf-8")
    if sidecar is not None:
        (projects_dir / slug / "artifacts" / f"{name}.json").write_text(json.dumps(sidecar), encoding="utf-8")


class TestCreate:
    def test_makes_folder_manifest_and_index_row(self, client, projects_dir, sessions_db):
        res = create(client)

        assert res.status_code == 201
        body = res.json()
        assert body["slug"] == "first-reel" and body["status"] == "created" and body["stage"] is None
        assert body["renderer"] == "ffmpeg" and body["mode"] == "guided" and body["stages"] == []
        folder = projects_dir / "first-reel"
        assert json.loads((folder / "project.json").read_text(encoding="utf-8")) == body
        assert (folder / "artifacts").is_dir()
        row = sqlite3.connect(sessions_db).execute("SELECT slug, status FROM projects").fetchone()
        assert row == ("first-reel", "created")

    @pytest.mark.parametrize("bad", ["Bad Slug", "../x", "", "a" * 41])
    def test_bad_slug_is_400(self, client, projects_dir, bad):
        res = create(client, slug=bad)

        assert res.status_code == 400
        assert list(projects_dir.iterdir()) == []

    def test_bad_renderer_mode_format_title_are_400(self, client):
        assert create(client, renderer="blender").status_code == 400
        assert create(client, mode="manual").status_code == 400
        assert create(client, format="Social Short").status_code == 400
        assert client.post("/projects", json={"slug": "x", "title": "   ", "format": "social-short"}).status_code == 400

    def test_duplicate_is_409(self, client):
        create(client)

        assert create(client).status_code == 409


class TestListAndGet:
    def test_list_shows_gallery_fields(self, client, projects_dir):
        create(client, slug="a")
        create(client, slug="b")
        (projects_dir / "b" / "preview.jpg").write_bytes(b"\xff\xd8")

        rows = client.get("/projects").json()

        by_slug = {r["slug"]: r for r in rows}
        assert set(by_slug) == {"a", "b"}
        assert by_slug["a"]["has_preview"] is False and by_slug["b"]["has_preview"] is True
        assert by_slug["a"]["has_final"] is False
        assert {"title", "format", "renderer", "mode", "status", "stage", "updated_at"} <= set(by_slug["a"])

    def test_get_lists_artifacts_with_sidecars_and_flags_missing_ones(self, client, projects_dir):
        create(client)
        put_artifact(
            projects_dir, "first-reel", "01-script.md", "# script",
            sidecar={"kind": "script", "stage": "script", "run_id": "r1", "worker": "scriptwriter",
                     "description": "Three beats", "created_at": "2026-10-28T08:00:00Z"},
        )
        put_artifact(projects_dir, "first-reel", "02-notes.md", "no sidecar")
        (projects_dir / "first-reel" / "artifacts" / "03-storyboard").mkdir()
        (projects_dir / "first-reel" / "artifacts" / "03-storyboard.json").write_text(
            json.dumps({"kind": "storyboard", "description": "six shots"}), encoding="utf-8"
        )
        (projects_dir / "first-reel" / "decisions.jsonl").write_text(
            '{"decision": "approve", "by": "mika"}\n', encoding="utf-8"
        )

        body = client.get("/projects/first-reel").json()

        arts = {a["path"]: a for a in body["artifacts"]}
        assert set(arts) == {"01-script.md", "02-notes.md", "03-storyboard"}  # sidecars are not artifacts
        assert arts["01-script.md"]["has_sidecar"] and arts["01-script.md"]["description"] == "Three beats"
        assert arts["01-script.md"]["kind"] == "script" and arts["01-script.md"]["size"] == len("# script")
        assert arts["02-notes.md"]["has_sidecar"] is False and arts["02-notes.md"]["description"] is None
        assert arts["03-storyboard"]["is_dir"] and arts["03-storyboard"]["kind"] == "storyboard"
        assert body["decisions"] == [{"decision": "approve", "by": "mika"}]
        assert body["has_final"] is False

    def test_unknown_and_bad_slug(self, client):
        assert client.get("/projects/nope").status_code == 404
        assert client.get("/projects/Bad%20Slug").status_code == 400


class TestPatchAndDelete:
    def test_patch_mode_and_title(self, client, projects_dir):
        create(client)

        res = client.patch("/projects/first-reel", json={"mode": "auto", "title": "Reel one"})

        assert res.status_code == 200
        manifest = json.loads((projects_dir / "first-reel" / "project.json").read_text(encoding="utf-8"))
        assert manifest["mode"] == "auto" and manifest["title"] == "Reel one"
        assert manifest["updated_at"] >= manifest["created_at"]
        assert client.patch("/projects/first-reel", json={"mode": "later"}).status_code == 400

    def test_delete_removes_folder_and_row(self, client, projects_dir, sessions_db):
        create(client)

        assert client.delete("/projects/first-reel").status_code == 204
        assert not (projects_dir / "first-reel").exists()
        assert sqlite3.connect(sessions_db).execute("SELECT count(*) FROM projects").fetchone() == (0,)
        assert client.delete("/projects/first-reel").status_code == 404

    def test_delete_held_folder_is_409(self, client, projects_dir, monkeypatch):
        create(client)
        monkeypatch.setattr(app_main.shutil, "rmtree", lambda p, *a, **k: (_ for _ in ()).throw(PermissionError(32, "busy", str(p))))

        res = client.delete("/projects/first-reel")

        assert res.status_code == 409
        assert (projects_dir / "first-reel" / "project.json").is_file()


class TestArtifactServing:
    def test_serves_an_artifact(self, client, projects_dir):
        create(client)
        put_artifact(projects_dir, "first-reel", "01-script.md", "# script")

        res = client.get("/projects/first-reel/artifacts/01-script.md")

        assert res.status_code == 200
        assert res.text == "# script"

    def test_serves_nested_artifact_files(self, client, projects_dir):
        create(client)
        (projects_dir / "first-reel" / "artifacts" / "03-storyboard").mkdir()
        (projects_dir / "first-reel" / "artifacts" / "03-storyboard" / "shot-1.md").write_text("shot", encoding="utf-8")

        assert client.get("/projects/first-reel/artifacts/03-storyboard/shot-1.md").text == "shot"

    @pytest.mark.parametrize("path", ["missing.md", "../project.json", "../../secret", "03-storyboard"])
    def test_outside_or_missing_is_404(self, client, projects_dir, path):
        create(client)
        (projects_dir / "first-reel" / "artifacts" / "03-storyboard").mkdir()
        (projects_dir.parent / "secret").write_text("x", encoding="utf-8")

        res = client.get(f"/projects/first-reel/artifacts/{path}")

        assert res.status_code == 404, path

    def test_final_and_preview_routes(self, client, projects_dir):
        create(client)
        assert client.get("/projects/first-reel/final.mp4").status_code == 404
        assert client.get("/projects/first-reel/preview.jpg").status_code == 404
        (projects_dir / "first-reel" / "final.mp4").write_bytes(b"\x00\x00\x00\x18ftyp")
        (projects_dir / "first-reel" / "preview.jpg").write_bytes(b"\xff\xd8\xff")

        final = client.get("/projects/first-reel/final.mp4")
        preview = client.get("/projects/first-reel/preview.jpg")

        assert final.status_code == 200 and final.headers["content-type"] == "video/mp4"
        assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"


class TestDownload:
    def test_zip_holds_the_whole_project_under_its_slug(self, client, projects_dir):
        import io
        import zipfile

        create(client)
        put_artifact(projects_dir, "first-reel", "01-script.md", "# script", sidecar={"kind": "script", "description": "d"})
        (projects_dir / "first-reel" / "artifacts" / "07-render").mkdir()
        (projects_dir / "first-reel" / "artifacts" / "07-render" / "plan.json").write_text("{}", encoding="utf-8")
        (projects_dir / "first-reel" / "final.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")

        res = client.get("/projects/first-reel/download")

        assert res.status_code == 200
        assert res.headers["content-type"] == "application/zip"
        assert res.headers["content-disposition"] == 'attachment; filename="first-reel.zip"'
        names = set(zipfile.ZipFile(io.BytesIO(res.content)).namelist())
        assert {"first-reel/project.json", "first-reel/artifacts/01-script.md", "first-reel/artifacts/01-script.md.json",
                "first-reel/artifacts/07-render/plan.json", "first-reel/final.mp4"} <= names
        assert all(n.startswith("first-reel/") for n in names)

    def test_unknown_and_invalid_slugs(self, client):
        assert client.get("/projects/nope/download").status_code == 404
        assert client.get("/projects/Bad%20Name/download").status_code == 400


class TestExport:
    def test_copies_the_whole_folder(self, client, projects_dir, tmp_path):
        create(client)
        put_artifact(projects_dir, "first-reel", "01-script.md", "# script", sidecar={"kind": "script", "description": "d"})
        dest = tmp_path / "Videos"
        dest.mkdir()

        res = client.post("/projects/first-reel/export", json={"dest_dir": str(dest)})

        assert res.status_code == 200
        assert res.json()["exported_to"] == str(dest / "first-reel")
        assert (dest / "first-reel" / "project.json").is_file()
        assert (dest / "first-reel" / "artifacts" / "01-script.md.json").is_file()
        assert client.post("/projects/first-reel/export", json={"dest_dir": str(dest)}).status_code == 409

    def test_bad_destinations_are_400(self, client, projects_dir, tmp_path):
        create(client)

        assert client.post("/projects/first-reel/export", json={"dest_dir": "relative/path"}).status_code == 400
        assert client.post("/projects/first-reel/export", json={"dest_dir": str(tmp_path / "nope")}).status_code == 400
        assert client.post("/projects/first-reel/export", json={"dest_dir": str(projects_dir)}).status_code == 400


class TestReindex:
    def test_startup_picks_up_folders_and_drops_stale_rows(
        self, workers_dir, templates_dir, sessions_db, messages_log, projects_dir
    ):
        first = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, projects_dir=projects_dir))
        create(first, slug="kept")
        create(first, slug="gone")
        import shutil
        shutil.rmtree(projects_dir / "gone")
        (projects_dir / "by-hand").mkdir()
        (projects_dir / "by-hand" / "project.json").write_text(
            json.dumps(projects.new_manifest("by-hand", "By hand", "explainer", "manim", "auto", app_main.datetime.now(app_main.timezone.utc))),
            encoding="utf-8",
        )

        second = TestClient(make_app(workers_dir, templates_dir, sessions_db, messages_log, projects_dir=projects_dir))

        assert {r["slug"] for r in second.get("/projects").json()} == {"kept", "by-hand"}
