"""Projects: the unit of work of the animation studio (docs/animation-studio.md §1).

projects/<slug>/ holds project.json (the manifest), artifacts/ with one
sidecar per artifact, decisions.jsonl, and the two gallery files preview.jpg
and final.mp4. The folder is the truth; the `projects` table in the SQLite
file is an index rebuilt from the folders at startup.
"""

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RENDERERS = {"remotion", "manim", "ffmpeg"}
MODES = {"auto", "guided"}
STATUSES = {"created", "running", "awaiting_approval", "needs_input", "failed", "published"}
MANIFEST = "project.json"
PREVIEW = "preview.jpg"
FINAL = "final.mp4"


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_manifest(slug: str, title: str, fmt: str, renderer: str, mode: str, now: datetime) -> dict:
    return {
        "slug": slug,
        "title": title,
        "format": fmt,
        "renderer": renderer,
        "mode": mode,
        "status": "created",
        "stage": None,
        "stages": [],
        "created_at": stamp(now),
        "updated_at": stamp(now),
    }


def read_manifest(project_dir: Path) -> dict | None:
    path = project_dir / MANIFEST
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(project_dir: Path, manifest: dict, now: datetime | None = None) -> None:
    if now is not None:
        manifest["updated_at"] = stamp(now)
    (project_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def create(project_dir: Path, manifest: dict) -> None:
    project_dir.mkdir(parents=False)
    (project_dir / "artifacts").mkdir()
    write_manifest(project_dir, manifest)


def artifacts(project_dir: Path) -> list[dict]:
    """Every entry under artifacts/ (file or folder) that is not itself a
    sidecar, with its sidecar's fields merged in. A missing sidecar is
    reported, not hidden: the gallery needs a description for everything."""
    root = project_dir / "artifacts"
    if not root.is_dir():
        return []
    out = []
    for entry in sorted(root.iterdir()):
        if entry.suffix == ".json" and (root / entry.stem).exists():
            continue  # a sidecar of a sibling
        sidecar_path = root / f"{entry.name}.json"
        sidecar = {}
        if sidecar_path.is_file():
            try:
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except ValueError:
                sidecar = {}
        out.append(
            {
                "path": entry.name,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
                "has_sidecar": bool(sidecar),
                "kind": sidecar.get("kind"),
                "stage": sidecar.get("stage"),
                "run_id": sidecar.get("run_id"),
                "worker": sidecar.get("worker"),
                "description": sidecar.get("description"),
                "created_at": sidecar.get("created_at"),
            }
        )
    return out


def decisions(project_dir: Path) -> list[dict]:
    path = project_dir / "decisions.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def safe_artifact_path(project_dir: Path, rel: str) -> Path | None:
    """The real path of an artifact given by the caller, or None if it would
    leave artifacts/ (traversal, absolute paths, symlinks out)."""
    root = (project_dir / "artifacts").resolve()
    candidate = (root / rel).resolve()
    if candidate == root or root not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def export(project_dir: Path, dest_dir: Path) -> Path:
    """Copy the whole project folder to dest_dir/<slug>/. Refuses to overwrite."""
    target = dest_dir / project_dir.name
    if target.exists():
        raise FileExistsError(str(target))
    shutil.copytree(project_dir, target)
    return target


# --- SQLite index ------------------------------------------------------------

COLUMNS = "slug, title, format, renderer, mode, status, stage, created_at, updated_at, path"


def init_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                format TEXT NOT NULL,
                renderer TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                path TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_sessions (
                session_id TEXT PRIMARY KEY,
                slug TEXT NOT NULL,
                stage TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def map_stage_session(db_path: Path, session_id: str, slug: str, stage: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO stage_sessions (session_id, slug, stage) VALUES (?, ?, ?)",
            (session_id, slug, stage),
        )
        conn.commit()
    finally:
        conn.close()


def stage_for_session(db_path: Path, session_id: str) -> tuple[str, str] | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT slug, stage FROM stage_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else (row[0], row[1])


def upsert(db_path: Path, manifest: dict, project_dir: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"""
            INSERT INTO projects ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title = excluded.title, format = excluded.format, renderer = excluded.renderer,
                mode = excluded.mode, status = excluded.status, stage = excluded.stage,
                updated_at = excluded.updated_at, path = excluded.path
            """,
            (
                manifest["slug"], manifest["title"], manifest["format"], manifest["renderer"],
                manifest["mode"], manifest["status"], manifest["stage"],
                manifest["created_at"], manifest["updated_at"], str(project_dir),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def remove(db_path: Path, slug: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM projects WHERE slug = ?", (slug,))
        conn.commit()
    finally:
        conn.close()


def list_all(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"SELECT {COLUMNS} FROM projects ORDER BY updated_at DESC, slug").fetchall()
    finally:
        conn.close()
    keys = [c.strip() for c in COLUMNS.split(",")]
    return [dict(zip(keys, r)) for r in rows]


def reindex(db_path: Path, projects_path: Path) -> None:
    """Make the index say exactly what the folders say: pick up projects
    created or copied by hand, drop rows whose folder is gone."""
    on_disk = {}
    if projects_path.is_dir():
        for folder in projects_path.iterdir():
            manifest = read_manifest(folder) if folder.is_dir() else None
            if manifest and manifest.get("slug") == folder.name:
                on_disk[folder.name] = (manifest, folder)
    conn = sqlite3.connect(db_path)
    try:
        indexed = {r[0] for r in conn.execute("SELECT slug FROM projects").fetchall()}
        for slug in indexed - set(on_disk):
            conn.execute("DELETE FROM projects WHERE slug = ?", (slug,))
        conn.commit()
    finally:
        conn.close()
    for manifest, folder in on_disk.values():
        upsert(db_path, manifest, folder)
