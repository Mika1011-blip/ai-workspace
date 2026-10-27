"""One JSON record per worker run, plus a SQLite index over them.

The file under workers/<name>/runs/ is the truth; the `runs` table is built in
the same code path so it can always be rebuilt from the files. Schema and
vocabulary: docs/run-record.md.
"""

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

TRIGGERS = {"manual", "schedule", "event", "loop"}
SCOPES = {"research", "code", "docs", "ops"}
SEVERITIES = {"info", "warn", "error"}
ENVS = {"local", "cloud", "ci"}
STATUSES = {"queued", "running", "success", "failed", "timeout", "skipped", "missed", "needs_input"}
# What a worker may say about its own run; the rest is the writer's call.
REPORTABLE_STATUSES = {"success", "failed", "skipped", "needs_input"}
TOPIC_RE = re.compile(r"^[a-z0-9-]{1,40}$")

TAG_VALUES = {
    "trigger": TRIGGERS,
    "scope": SCOPES,
    "severity": SEVERITIES,
    "env": ENVS,
}


class BadTag(ValueError):
    pass


def validate_tags(tags: list[str]) -> list[str]:
    """`key:value` from the fixed vocabulary, deduplicated, order kept."""
    seen: list[str] = []
    for tag in tags:
        key, sep, value = tag.partition(":")
        if not sep or not key or not value:
            raise BadTag(f"{tag!r} is not key:value")
        if key in ("worker", "topic", "project"):
            if not TOPIC_RE.fullmatch(value):
                raise BadTag(f"{tag!r}: value must match {TOPIC_RE.pattern}")
        elif key in TAG_VALUES:
            if value not in TAG_VALUES[key]:
                raise BadTag(f"{tag!r}: {key} must be one of {sorted(TAG_VALUES[key])}")
        else:
            raise BadTag(f"{tag!r}: unknown key {key!r}")
        if tag not in seen:
            seen.append(tag)
    return seen


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_for(worker: str, started_at: datetime, session_id: str) -> str:
    # Time first so a worker's runs sort chronologically; the session id makes
    # two spawns in the same second distinct instead of overwriting each other.
    return f"{worker}-{started_at.strftime('%Y-%m-%dT%H-%M-%SZ')}-{session_id}"


def prompt_version(instructions: str) -> str:
    return hashlib.sha256(instructions.encode("utf-8")).hexdigest()[:7]


def new_record(
    worker: str,
    session_id: str,
    trigger: str,
    tags: list[str],
    started_at: datetime,
    instructions: str,
    env: str = "local",
) -> dict:
    fixed = [f"worker:{worker}", f"trigger:{trigger}", f"env:{env}"]
    return {
        "run_id": run_id_for(worker, started_at, session_id),
        "worker": worker,
        "trigger": trigger,
        "attempt": 1,
        "started_at": stamp(started_at),
        "ended_at": None,
        "status": "running",
        "tags": validate_tags(fixed + list(tags)),
        "prompt_version": prompt_version(instructions),
        "result": None,
        "metrics": {"turns": None, "duration_ms": None, "cost_usd": None},
        "error": None,
        "session_id": session_id,
    }


def finish(record: dict, ended_at: datetime, status: str | None = None, error: str | None = None) -> dict:
    """Close a record: ended_at and duration always; status/error only if it
    is still running (a worker's own verdict is never overwritten)."""
    started = datetime.strptime(record["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    record["ended_at"] = stamp(ended_at)
    record["metrics"]["duration_ms"] = max(0, int((ended_at - started).total_seconds() * 1000))
    if record["status"] == "running" and status is not None:
        record["status"] = status
        record["error"] = error
    return record


def record_path(workers_path: Path, record: dict) -> Path:
    return workers_path / record["worker"] / "runs" / f"{record['run_id']}.json"


def write_record(workers_path: Path, record: dict) -> Path:
    path = record_path(workers_path, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def read_record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- SQLite index ------------------------------------------------------------

RUN_COLUMNS = "run_id, worker, session_id, trigger, status, started_at, ended_at, tags, path"


def init_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                worker TEXT NOT NULL,
                session_id TEXT,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                tags TEXT NOT NULL,
                path TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def upsert(db_path: Path, record: dict, path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"""
            INSERT INTO runs ({RUN_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status = excluded.status, ended_at = excluded.ended_at, tags = excluded.tags
            """,
            (
                record["run_id"],
                record["worker"],
                record["session_id"],
                record["trigger"],
                record["status"],
                record["started_at"],
                record["ended_at"],
                json.dumps(record["tags"]),
                str(path),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def path_for_session(db_path: Path, session_id: str) -> Path | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT path FROM runs WHERE session_id = ? ORDER BY started_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else Path(row[0])


def list_runs(
    db_path: Path,
    worker: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    since: str | None = None,
) -> list[dict]:
    """Newest first. Every given filter narrows; `tags` must all be present."""
    clauses, params = [], []
    if worker:
        clauses.append("worker = ?")
        params.append(worker)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if since:
        clauses.append("started_at >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {RUN_COLUMNS} FROM runs {where} ORDER BY started_at DESC, run_id DESC", params
        ).fetchall()
    finally:
        conn.close()
    wanted = set(tags or [])
    out = []
    for r in rows:
        row_tags = json.loads(r[7])
        if wanted and not wanted.issubset(row_tags):
            continue
        out.append(
            {
                "run_id": r[0],
                "worker": r[1],
                "session_id": r[2],
                "trigger": r[3],
                "status": r[4],
                "started_at": r[5],
                "ended_at": r[6],
                "tags": row_tags,
                "path": r[8],
            }
        )
    return out
