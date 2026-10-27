"""The studio pipeline as a state machine (docs/animation-studio.md §2, §4).

project.json carries the state; this module decides what happens next when
a stage's worker reports, and asks the API to spawn the next stage. No LLM
is involved between stages. Review gates, the one-revision rule and the
guided-mode checkpoints live here.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app import projects

# (stage, worker, kind). Makers produce artifacts, reviewers judge them with
# the same format skill, "api" stages are performed by the API itself.
STAGES: list[tuple[str, str | None, str]] = [
    ("script", "scriptwriter", "maker"),
    ("script-review", "script-reviewer", "reviewer"),
    ("storyboard", "storyboarder", "maker"),
    ("storyboard-review", "storyboard-reviewer", "reviewer"),
    ("assets", "asset-maker", "maker"),
    ("asset-review", "asset-reviewer", "reviewer"),
    ("render", "renderer", "maker"),
    ("render-review", "render-reviewer", "reviewer"),
    ("publish", None, "api"),
]
STAGE_INDEX = {name: i for i, (name, _, _) in enumerate(STAGES)}
MAX_ATTEMPTS = 2  # a maker runs at most twice per gate: first try, one revision

SCOPE = {
    "script": "docs", "script-review": "docs",
    "storyboard": "docs", "storyboard-review": "docs",
    "assets": "ops", "asset-review": "ops",
    "render": "ops", "render-review": "ops",
}

STAGE_BRIEF = {
    "script": "Write the script as artifacts/01-script.md.",
    "script-review": "Review artifacts/01-script.md against the format skill. Write your review as artifacts/02-script-review.md.",
    "storyboard": "Turn the approved script into a storyboard under artifacts/03-storyboard/ (one shot per file, with timing).",
    "storyboard-review": "Review artifacts/03-storyboard/ against the script and the format skill. Write artifacts/04-storyboard-review.md.",
    "assets": "Produce the assets the storyboard calls for (voice, music, images) as artifacts/05-*.",
    "asset-review": "Review the assets against the storyboard. Write artifacts/06-asset-review.md.",
    "render": "Write the renderer input under artifacts/07-render/ for the project's renderer, from the storyboard and assets.",
    "render-review": "Review the render candidate against the storyboard. Write artifacts/08-render-review.md.",
}


class PipelineError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def workers_needed() -> list[str]:
    return [w for _, w, _ in STAGES if w]


class Pipeline:
    def __init__(
        self,
        projects_path: Path,
        db_path: Path,
        workers_path: Path,
        start_session: Callable[..., dict],
        now: Callable[[], datetime] | None = None,
    ):
        self.projects_path = projects_path
        self.db_path = db_path
        self.workers_path = workers_path
        self.start_session = start_session
        self.now = now or (lambda: datetime.now(timezone.utc))

    # -- entry points ----------------------------------------------------------

    def start(self, slug: str) -> dict:
        folder = self.projects_path / slug
        manifest = projects.read_manifest(folder)
        if manifest is None:
            raise PipelineError(404, f"Project '{slug}' not found")
        if manifest["status"] in ("running", "awaiting_approval"):
            raise PipelineError(409, f"project is {manifest['status']}")
        missing = [w for w in workers_needed() if not (self.workers_path / w / "CLAUDE.md").is_file()]
        if missing:
            raise PipelineError(400, f"missing_workers: {missing}")
        manifest["stages"] = []
        manifest["error"] = None
        manifest["next_stage"] = None
        self._run_stage(folder, manifest, "script")
        return manifest

    def on_report(self, session_id: str, status: str, summary: str | None) -> dict | None:
        """A stage worker reported. Returns the updated manifest, or None if
        the session isn't a stage of any project."""
        mapping = projects.stage_for_session(self.db_path, session_id)
        if mapping is None:
            return None
        slug, stage = mapping
        folder = self.projects_path / slug
        manifest = projects.read_manifest(folder)
        if manifest is None:
            return None
        entry = self._entry_for(manifest, session_id)
        if entry is None or entry["status"] != "running":
            return manifest  # a stale or duplicate report; the record keeps it, the project ignores it
        entry["status"] = status
        entry["summary"] = summary
        entry["ended_at"] = stamp(self.now())

        _, _, kind = STAGES[STAGE_INDEX[stage]]
        if kind == "maker":
            if status == "success":
                self._advance(folder, manifest, stage)
            else:
                self._fail(folder, manifest, f"{stage}: worker reported {status}")
        elif kind == "reviewer":
            if status == "success":
                if manifest["mode"] == "guided":
                    manifest["status"] = "awaiting_approval"
                    manifest["next_stage"] = self._next_name(stage)
                    self._save(folder, manifest)
                else:
                    self._advance(folder, manifest, stage)
            elif status == "needs_input":
                self._revise_or_stop(folder, manifest, stage, summary)
            else:
                self._fail(folder, manifest, f"{stage}: reviewer reported {status}")
        return manifest

    def on_session_failed(self, session_id: str, error: str) -> dict | None:
        """A stage's session ended or vanished without reporting."""
        mapping = projects.stage_for_session(self.db_path, session_id)
        if mapping is None:
            return None
        slug, stage = mapping
        folder = self.projects_path / slug
        manifest = projects.read_manifest(folder)
        if manifest is None:
            return None
        entry = self._entry_for(manifest, session_id)
        if entry is None or entry["status"] != "running":
            return manifest
        entry["status"] = "failed"
        entry["ended_at"] = stamp(self.now())
        self._fail(folder, manifest, f"{stage}: {error}")
        return manifest

    # -- transitions -----------------------------------------------------------

    def _advance(self, folder: Path, manifest: dict, done_stage: str) -> None:
        nxt = self._next_name(done_stage)
        manifest["next_stage"] = None
        if nxt is None:
            manifest["stage"] = None
            manifest["status"] = "published"
            self._save(folder, manifest)
            return
        _, worker, kind = STAGES[STAGE_INDEX[nxt]]
        if kind == "api":
            # Performed by the API (render step, publish) -- wired in a later PR.
            # Until then the project waits here, visibly, instead of pretending.
            manifest["stage"] = nxt
            manifest["status"] = "running"
            self._save(folder, manifest)
            return
        self._run_stage(folder, manifest, nxt)

    def _revise_or_stop(self, folder: Path, manifest: dict, review_stage: str, notes: str | None) -> None:
        maker = STAGES[STAGE_INDEX[review_stage] - 1][0]
        attempts = sum(1 for e in manifest["stages"] if e["name"] == maker)
        if attempts >= MAX_ATTEMPTS:
            manifest["stage"] = review_stage
            manifest["status"] = "needs_input"
            manifest["error"] = f"{review_stage}: still needs input after {attempts} attempts of {maker}"
            self._save(folder, manifest)
            return
        self._run_stage(folder, manifest, maker, notes=notes)

    def _fail(self, folder: Path, manifest: dict, error: str) -> None:
        manifest["status"] = "failed"
        manifest["error"] = error
        self._save(folder, manifest)

    def _run_stage(self, folder: Path, manifest: dict, stage: str, notes: str | None = None) -> None:
        _, worker, _ = STAGES[STAGE_INDEX[stage]]
        attempt = 1 + sum(1 for e in manifest["stages"] if e["name"] == stage)
        task = self._task(manifest, stage, notes)
        session = self.start_session(
            worker=worker,
            task=task,
            trigger="event",
            tags=[f"project:{manifest['slug']}", f"topic:{manifest['slug']}", f"scope:{SCOPE[stage]}"],
            write_to=[folder / "artifacts"],
        )
        manifest["stages"].append(
            {
                "name": stage,
                "worker": worker,
                "attempt": attempt,
                "session_id": session["session_id"],
                "run_id": session["run_id"],
                "status": "running",
                "started_at": stamp(self.now()),
                "ended_at": None,
                "summary": None,
                "notes": notes,
            }
        )
        manifest["stage"] = stage
        manifest["status"] = "running"
        manifest["next_stage"] = None
        self._save(folder, manifest)
        projects.map_stage_session(self.db_path, session["session_id"], manifest["slug"], stage)

    # -- helpers -----------------------------------------------------------------

    def _task(self, manifest: dict, stage: str, notes: str | None) -> str:
        artifacts = (self.projects_path / manifest["slug"] / "artifacts").resolve()
        lines = [
            f"Project '{manifest['slug']}' ({manifest['title']}), format '{manifest['format']}', stage '{stage}'.",
            f"Use the skill '{manifest['format']}' for the structure and rules of this format.",
            f"The project's working files are in {artifacts} (read and write; everything you need is there).",
            STAGE_BRIEF[stage],
            "Next to every file or folder you produce, write a sidecar <name>.json with: kind, stage, "
            "run_id, worker, description (one line, mandatory), created_at.",
            "When finished, call report_result once: status 'success' with a one-line summary; "
            "a reviewer that wants changes reports 'needs_input' with its notes as the summary.",
        ]
        if notes:
            lines.append(f"REVISION REQUESTED. The reviewer's notes: {notes}")
        return "\n".join(lines)

    def _save(self, folder: Path, manifest: dict) -> None:
        projects.write_manifest(folder, manifest, self.now())
        projects.upsert(self.db_path, manifest, folder)

    @staticmethod
    def _next_name(stage: str) -> str | None:
        i = STAGE_INDEX[stage] + 1
        return STAGES[i][0] if i < len(STAGES) else None

    @staticmethod
    def _entry_for(manifest: dict, session_id: str) -> dict | None:
        for entry in reversed(manifest["stages"]):
            if entry["session_id"] == session_id:
                return entry
        return None
