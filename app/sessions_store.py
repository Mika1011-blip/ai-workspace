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
                agent TEXT NOT NULL,
                status TEXT NOT NULL,
                spawned_by TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                may_talk_to TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def insert_session(
    db_path: Path,
    session_id: str,
    agent: str,
    spawned_by: str | None,
    started_at: str,
    may_talk_to: list[str],
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO sessions
                (session_id, agent, status, spawned_by, started_at, ended_at, may_talk_to)
            VALUES (?, ?, 'live', ?, ?, NULL, ?)
            """,
            (session_id, agent, spawned_by, started_at, json.dumps(may_talk_to)),
        )
        conn.commit()
    finally:
        conn.close()


def get_session(db_path: Path, session_id: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT session_id, agent, status, spawned_by, started_at, ended_at, may_talk_to "
            "FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "session_id": row[0],
        "agent": row[1],
        "status": row[2],
        "spawned_by": row[3],
        "started_at": row[4],
        "ended_at": row[5],
        "may_talk_to": json.loads(row[6]),
    }


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
        rows = conn.execute(
            "SELECT session_id, agent, status, spawned_by, started_at, ended_at, may_talk_to "
            "FROM sessions"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "session_id": r[0],
            "agent": r[1],
            "status": r[2],
            "spawned_by": r[3],
            "started_at": r[4],
            "ended_at": r[5],
            "may_talk_to": json.loads(r[6]),
        }
        for r in rows
        if r[0] in reachable_ids
    ]
