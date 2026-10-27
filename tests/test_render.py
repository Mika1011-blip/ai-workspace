import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import render
from tests.test_pipeline import (  # noqa: F401 -- fixtures shared with the pipeline tests
    SPAWNED,
    SPAWNED_IDS,
    STAGE_WORKERS,
    STOPPED,
    _reset_fakes,
    auth,
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
from tests.test_sessions import make_app


class FakeDocker:
    """Stands in for `docker run`: records every call and does what the real
    images would do to the mounted project folder."""

    def __init__(self, fail: set[str] = ()):
        self.calls = []
        self.fail = set(fail)

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:2] == ["docker", "image"]:
            return 0, ""
        project = Path(argv[argv.index("-v") + 1].split(":/project")[0])
        cmd = argv[-1]
        if cmd in self.fail:
            return 1, f"{cmd} exploded"
        arts = project / "artifacts"
        if cmd == "render":
            (arts / "final-candidate.mp4").write_bytes(b"candidate")
        elif cmd == "frames":
            (arts / "07-render-frames").mkdir(exist_ok=True)
            (arts / "07-render-frames" / "frame-01.jpg").write_bytes(b"\xff\xd8")
        elif cmd == "publish":
            (project / "final.mp4").write_bytes(b"final")
            (project / "preview.jpg").write_bytes(b"\xff\xd8")
        return 0, f"{cmd} ok"


@pytest.fixture
def docker():
    return FakeDocker()


@pytest.fixture
def client(workers_dir, templates_dir, sessions_db, messages_log, projects_dir, docker):
    c = TestClient(
        make_app(workers_dir, templates_dir, sessions_db, messages_log, projects_dir=projects_dir, render_run=docker)
    )
    for w in STAGE_WORKERS:
        create_worker(c, w)
    return c


def run_to_render(client, projects_dir):
    make_project(client, mode="auto")
    client.post("/projects/first-reel/start")
    for _ in range(6):  # script .. asset-review
        report(client, projects_dir, "success")
    (projects_dir / "first-reel" / "artifacts" / "07-render").mkdir()
    (projects_dir / "first-reel" / "artifacts" / "07-render" / "plan.json").write_text("{}", encoding="utf-8")
    assert manifest(projects_dir)["stage"] == "render"


class TestDockerArgv:
    def test_mounts_the_project_and_names_the_image(self, tmp_path):
        argv = render.docker_argv("remotion", tmp_path / "p", "render")

        assert argv[:3] == ["docker", "run", "--rm"]
        assert argv[argv.index("-v") + 1] == f"{(tmp_path / 'p').resolve()}:/project"
        assert argv[-2:] == ["ai-workspace/renderer-remotion", "render"]


class TestRenderStep:
    def test_render_then_frames_then_reviewer(self, client, projects_dir, docker):
        run_to_render(client, projects_dir)

        m = report(client, projects_dir, "success", "wrote the plan")

        cmds = [c[-1] for c in docker.calls]
        assert cmds == ["render", "frames"]
        assert docker.calls[0][-2] == "ai-workspace/renderer-ffmpeg"  # the project's renderer (default)
        arts = projects_dir / "first-reel" / "artifacts"
        assert (arts / "final-candidate.mp4").is_file() and (arts / "final-candidate.mp4.json").is_file()
        assert (arts / "07-render-frames" / "frame-01.jpg").is_file() and (arts / "07-render-frames.json").is_file()
        assert "render ok" in (arts / "07-render.log").read_text(encoding="utf-8")
        assert m["stage"] == "render-review" and m["status"] == "running"
        assert [e["name"] for e in m["stages"][-3:]] == ["render", "render-step", "render-review"]
        assert m["stages"][-2]["worker"] == "api" and m["stages"][-2]["status"] == "success"

    def test_render_failure_fails_the_project_with_the_log(self, client, projects_dir, docker):
        docker.fail = {"render"}
        run_to_render(client, projects_dir)

        m = report(client, projects_dir, "success")

        assert m["status"] == "failed" and "render-step" in m["error"] and "exploded" in m["error"]
        log = (projects_dir / "first-reel" / "artifacts" / "07-render.log").read_text(encoding="utf-8")
        assert "exit 1" in log and "render exploded" in log
        assert m["stages"][-1]["name"] == "render-step" and m["stages"][-1]["status"] == "failed"

    def test_uses_the_projects_renderer_image(self, client, projects_dir, docker):
        res = client.post("/projects", json={"slug": "manim-one", "title": "M", "format": "explainer", "renderer": "manim", "mode": "auto"})
        assert res.status_code == 201
        client.post("/projects/manim-one/start")
        for _ in range(6):
            report(client, projects_dir, "success", slug="manim-one")

        report(client, projects_dir, "success", slug="manim-one")

        assert docker.calls[0][-2] == "ai-workspace/renderer-manim"
        assert docker.calls[1][-2] == "ai-workspace/renderer-ffmpeg"  # frames always via the utility image


class TestPublishStep:
    def test_review_success_publishes(self, client, projects_dir, docker):
        run_to_render(client, projects_dir)
        report(client, projects_dir, "success")           # render -> render-step -> render-review

        m = report(client, projects_dir, "success", "matches the storyboard")

        assert [c[-1] for c in docker.calls] == ["render", "frames", "publish"]
        folder = projects_dir / "first-reel"
        assert (folder / "final.mp4").is_file() and (folder / "preview.jpg").is_file()
        assert m["status"] == "published" and m["stage"] is None
        assert m["stages"][-1]["name"] == "publish" and m["stages"][-1]["status"] == "success"
        listing = client.get("/projects").json()[0]
        assert listing["status"] == "published" and listing["has_final"] and listing["has_preview"]
        assert client.get("/projects/first-reel/final.mp4").status_code == 200

    def test_publish_failure_fails_the_project(self, client, projects_dir, docker):
        docker.fail = {"publish"}
        run_to_render(client, projects_dir)
        report(client, projects_dir, "success")

        m = report(client, projects_dir, "success")

        assert m["status"] == "failed" and "publish" in m["error"]
        assert not (projects_dir / "first-reel" / "final.mp4").exists()

    def test_guided_mode_publishes_only_after_approval(self, client, projects_dir, docker):
        make_project(client, mode="guided")
        client.post("/projects/first-reel/start")
        # script, storyboard, assets: maker reports, reviewer reports, Mika approves.
        for _ in range(3):
            report(client, projects_dir, "success")
            assert report(client, projects_dir, "success")["status"] == "awaiting_approval"
            client.post("/projects/first-reel/decision", json={"decision": "approve"})
        assert manifest(projects_dir)["stage"] == "render"
        (projects_dir / "first-reel" / "artifacts" / "07-render").mkdir()
        report(client, projects_dir, "success")           # render -> render-step -> render-review
        m = report(client, projects_dir, "success", "fine")
        assert m["status"] == "awaiting_approval"
        assert [c[-1] for c in docker.calls] == ["render", "frames"]   # not published yet

        client.post("/projects/first-reel/decision", json={"decision": "approve"})

        assert manifest(projects_dir)["status"] == "published"
        assert [c[-1] for c in docker.calls] == ["render", "frames", "publish"]


# --- the renderer script itself (pure functions, no docker) --------------------

def load_render_script():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "docker" / "renderers" / "ffmpeg" / "render.py"
    spec = importlib.util.spec_from_file_location("ffmpeg_render", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCaptionWrapping:
    # The first real render cut "Why does your cat purr?" off at both edges:
    # drawtext never wraps, so the script has to.

    def test_long_caption_is_wrapped_to_the_frame_width(self):
        script = load_render_script()
        fontsize = script.caption_fontsize(1920)
        text = "3. Healing: 25-150 Hz vibrations may help bones and tissue mend"

        lines = script.wrap_caption(text, 1080, fontsize).split("\n")

        assert len(lines) >= 2
        per_line = int(1080 * 0.9 / (fontsize * 0.6))
        assert all(len(line) <= per_line for line in lines)
        assert " ".join(lines) == text  # nothing lost, only broken at spaces

    def test_short_caption_stays_on_one_line(self):
        script = load_render_script()

        assert script.wrap_caption("Why?", 1080, script.caption_fontsize(1920)) == "Why?"

    def test_filter_centres_lines_and_writes_the_wrapped_textfile(self, tmp_path):
        script = load_render_script()

        vf = script.caption_filter("Why does your cat purr? Four reasons in twenty seconds", 1080, 1920, tmp_path, 3)

        assert "text_align=C" in vf and "line_spacing=" in vf
        assert f"fontsize={script.caption_fontsize(1920)}" in vf
        written = (tmp_path / "caption-03.txt").read_text(encoding="utf-8")
        assert "\n" in written

    def test_empty_caption_draws_nothing(self, tmp_path):
        script = load_render_script()

        assert script.caption_filter("", 1080, 1920, tmp_path, 0) == "null"


# --- the real image, when it exists on this machine ---------------------------

def real_image_present() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return render.image_available("ffmpeg")
    except OSError:
        return False


@pytest.mark.skipif(not real_image_present(), reason="ai-workspace/renderer-ffmpeg image not built on this machine")
def test_ffmpeg_image_renders_a_plan_and_publishes_browser_safe(tmp_path):
    project = tmp_path / "smoke"
    (project / "artifacts" / "07-render").mkdir(parents=True)
    (project / "artifacts" / "07-render" / "plan.json").write_text(json.dumps({
        "width": 360, "height": 640, "fps": 24,
        "shots": [
            {"text": "Why do cats purr?", "duration": 1.0, "color": "#1b1b2f"},
            # Long enough to need wrapping even at 360 px wide.
            {"text": "Three reasons, and the third one will surprise you more than the first", "duration": 1.0, "color": "#2f1b1b"},
        ],
    }), encoding="utf-8")
    r = render.Renderer()

    ok, out = r.render(project, "ffmpeg")
    assert ok, out
    ok, out = r.publish(project)
    assert ok, out

    assert (project / "final.mp4").stat().st_size > 1000
    assert (project / "preview.jpg").stat().st_size > 100
    assert len(list((project / "artifacts" / "07-render-frames").glob("*.jpg"))) == 6
    info = json.loads(subprocess.run(
        render.docker_argv("ffmpeg", project, "probe", "/project/final.mp4"),
        capture_output=True, text=True, check=True,
    ).stdout)
    assert info["video_codec"] == "h264" and info["pix_fmt"] == "yuv420p" and info["audio_codec"] is None
    assert info["width"] == 360 and info["height"] == 640 and 1.8 < info["duration"] < 2.3
