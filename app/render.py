"""The API side of rendering and publishing (docs/animation-studio.md §6).

No Claude in Docker: the renderer worker writes the renderer's input into
artifacts/07-render/, and the API runs the renderer image on the project
folder. The ffmpeg image doubles as the media utility: frames for the
reviewer, probing, and the browser-safe publish step.
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

IMAGE_PREFIX = "ai-workspace/renderer-"
UTILITY = "ffmpeg"

RunFn = Callable[[list[str]], tuple[int, str]]


def docker_argv(renderer: str, project_dir: Path, *cmd: str) -> list[str]:
    return [
        "docker", "run", "--rm",
        "-v", f"{project_dir.resolve()}:/project",
        f"{IMAGE_PREFIX}{renderer}",
        *cmd,
    ]


def default_run(argv: list[str]) -> tuple[int, str]:
    result = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace")
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def image_available(renderer: str, run: RunFn = default_run) -> bool:
    code, _ = run(["docker", "image", "inspect", f"{IMAGE_PREFIX}{renderer}"])
    return code == 0


def _sidecar(project_dir: Path, name: str, kind: str, stage: str, description: str) -> None:
    (project_dir / "artifacts" / f"{name}.json").write_text(
        json.dumps(
            {
                "kind": kind,
                "stage": stage,
                "run_id": None,
                "worker": "api",
                "description": description,
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class Renderer:
    def __init__(self, run: RunFn = default_run):
        self.run = run

    def _step(self, project_dir: Path, image: str, cmd: str, log_name: str, stage: str) -> tuple[bool, str]:
        code, output = self.run(docker_argv(image, project_dir, cmd))
        log = project_dir / "artifacts" / log_name
        with log.open("a", encoding="utf-8") as f:
            f.write(f"--- api: docker {cmd} ({image}) exit {code}\n{output}\n")
        _sidecar(project_dir, log_name, "log", stage, f"What the {image} renderer printed for `{cmd}`.")
        return code == 0, output

    def render(self, project_dir: Path, renderer: str) -> tuple[bool, str]:
        """artifacts/07-render/ -> artifacts/final-candidate.mp4, then frames
        for the reviewer. Returns (ok, output)."""
        ok, output = self._step(project_dir, renderer, "render", "07-render.log", "render")
        if not ok or not (project_dir / "artifacts" / "final-candidate.mp4").is_file():
            return False, output or "renderer produced no final-candidate.mp4"
        _sidecar(project_dir, "final-candidate.mp4", "video", "render", "Render candidate, before the publish check.")
        ok, out2 = self._step(project_dir, UTILITY, "frames", "07-frames.log", "render")
        if ok:
            _sidecar(project_dir, "07-render-frames", "image", "render", "Six frames of the candidate, for the render review.")
        return ok, output + out2

    def publish(self, project_dir: Path) -> tuple[bool, str]:
        """artifacts/final-candidate.mp4 -> final.mp4 (H.264/AAC/yuv420p/
        faststart, re-muxed or transcoded as needed) + preview.jpg."""
        ok, output = self._step(project_dir, UTILITY, "publish", "08-publish.log", "publish")
        if not ok:
            return False, output
        if not (project_dir / "final.mp4").is_file() or not (project_dir / "preview.jpg").is_file():
            return False, output or "publish produced no final.mp4 / preview.jpg"
        return True, output
