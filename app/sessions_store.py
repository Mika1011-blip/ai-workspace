"""SQLite-backed session registry for the app-side comms protocol.

One table, one writer (the API). Each call opens and closes its own
connection against a file path, so it's safe across FastAPI's threadpool
without sharing a connection between threads.
"""

import json
import sqlite3
from pathlib import Path


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                worker TEXT NOT NULL,
                status TEXT NOT NULL,
                spawned_by TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                may_talk_to TEXT NOT NULL,
                token_hash TEXT
            )
            """
        )
        # Databases created before tokens existed: add the column; their rows
        # keep NULL and so can never authenticate, which is the right outcome.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "token_hash" not in columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN token_hash TEXT")
        # Databases from before the agents -> workers rename.
        if "agent" in columns and "worker" not in columns:
            conn.execute("ALTER TABLE sessions RENAME COLUMN agent TO worker")
        conn.commit()
    finally:
        conn.close()


COLUMNS = "session_id, worker, status, spawned_by, started_at, ended_at, may_talk_to, token_hash"


def _row_to_dict(row) -> dict:
    return {
        "session_id": row[0],
        "worker": row[1],
        "status": row[2],
        "spawned_by": row[3],
        "started_at": row[4],
        "ended_at": row[5],
        "may_talk_to": json.loads(row[6]),
        "token_hash": row[7],
    }


def insert_session(
    db_path: Path,
    session_id: str,
    worker: str,
    spawned_by: str | None,
    started_at: str,
    may_talk_to: list[str],
    token_hash: str,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"""
            INSERT INTO sessions ({COLUMNS})
            VALUES (?, ?, 'live', ?, ?, NULL, ?, ?)
            """,
            (session_id, worker, spawned_by, started_at, json.dumps(may_talk_to), token_hash),
        )
        conn.commit()
    finally:
        conn.close()


def get_session(db_path: Path, session_id: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {COLUMNS} FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _row_to_dict(row)


def get_by_token_hash(db_path: Path, token_hash: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {COLUMNS} FROM sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _row_to_dict(row)


def mark_ended(db_path: Path, session_id: str, ended_at: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE sessions SET status = 'ended', ended_at = ? WHERE session_id = ?",
            (ended_at, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def reconcile(db_path: Path, running_ids: set[str], ended_at: str) -> list[str]:
    """Mark every `live` session whose id is not actually running as ended.
    Returns the ids that were closed."""
    conn = sqlite3.connect(db_path)
    try:
        live = [
            r[0]
            for r in conn.execute("SELECT session_id FROM sessions WHERE status = 'live'").fetchall()
        ]
        stale = [sid for sid in live if sid not in running_ids]
        for sid in stale:
            conn.execute(
                "UPDATE sessions SET status = 'ended', ended_at = ? WHERE session_id = ?",
                (ended_at, sid),
            )
        conn.commit()
    finally:
        conn.close()
    return stale


def list_reachable(db_path: Path, caller_id: str) -> list[dict] | None:
    """Every session `caller_id` may reach: itself, plus everything in its
    own `may_talk_to`. Returns None if `caller_id` is unknown."""
    caller = get_session(db_path, caller_id)
    if caller is None:
        return None
    reachable_ids = {caller_id, *caller["may_talk_to"]}
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"SELECT {COLUMNS} FROM sessions").fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows if r[0] in reachable_ids]
