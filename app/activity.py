"""Per-worker activity log: workers/<name>/activity.jsonl, one JSON object
per line, appended by the API for every event it handles for that worker.
Complements the run records (what a run produced) with a timeline (what
happened, when, with whom)."""

import json
from datetime import datetime, timezone
from pathlib import Path


def path_for(workers_path: Path, worker: str) -> Path:
    return workers_path / worker / "activity.jsonl"


def log(workers_path: Path, worker: str, event: str, fields: dict | None = None) -> None:
    entry = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
        **(fields or {}),
    }
    path = path_for(workers_path, worker)
    # A deleted worker gets no ghost folder: reconciling or ending a session
    # whose worker is gone must not resurrect `workers/<name>/` (seen live).
    if not path.parent.is_dir():
        return
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def tail(workers_path: Path, worker: str, limit: int) -> list[dict]:
    """The last `limit` events, oldest first."""
    path = path_for(workers_path, worker)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:] if line.strip()]
