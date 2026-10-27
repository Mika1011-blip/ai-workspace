import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import run_records, sessions_store

STATIC_DIR = Path(__file__).parent / "static"

# Lowercase letters, digits and hyphens, 1-40 characters total. Rejecting
# everything else also keeps names from escaping the workers folder, since a
# match can never contain "." or "/".
NAME_PATTERN = r"^[a-z0-9-]{1,40}$"


def validate_name(name: str) -> None:
    if not re.fullmatch(NAME_PATTERN, name):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid worker name {name!r}: must match {NAME_PATTERN}",
        )


class WorkerCreate(BaseModel):
    name: str
    instructions: str | None = None


class WorkerUpdate(BaseModel):
    instructions: str


class Worker(BaseModel):
    name: str
    instructions: str


class Template(BaseModel):
    name: str
    description: str


class TemplateContent(BaseModel):
    content: str


class SkillCreate(BaseModel):
    skill_name: str
    content: str


class Skill(BaseModel):
    name: str
    content: str


class SessionCreate(BaseModel):
    worker: str
    task: str
    spawned_by: str | None = None
    may_talk_to: list[str] = []
    trigger: str = "manual"
    tags: list[str] = []


class Session(BaseModel):
    session_id: str
    worker: str
    status: str
    spawned_by: str | None
    started_at: str
    ended_at: str | None
    may_talk_to: list[str]
    run_id: str | None = None


class ResultReport(BaseModel):
    status: str
    summary: str | None = None
    tags: list[str] = []
    metrics: dict = {}
    error: str | None = None


class MessageCreate(BaseModel):
    from_: str = Field(alias="from")
    text: str

    model_config = {"populate_by_name": True}


def starter_instructions(name: str) -> str:
    return f"# {name}\n\nDescribe what this worker does and how it should work.\n"


def parse_template(text: str) -> tuple[str, str]:
    """Split a template file into (description, body).

    Templates start with a `---`-delimited frontmatter block holding a single
    `description: ...` line, followed by the body that becomes the new
    worker's starter CLAUDE.md verbatim. Missing/malformed frontmatter falls
    back to an empty description and the whole text as the body, rather than
    raising -- template files are trusted content from `worker_templates/`.
    """
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            frontmatter = text[4:end]
            body = text[end + 4 :].lstrip("\n")
            description = ""
            for line in frontmatter.splitlines():
                if line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
            return description, body
    return "", text


def claude_cli() -> str:
    # On Windows the npm shim is claude.cmd, which a bare "claude" argv
    # can't resolve; which() finds it on every platform.
    path = shutil.which("claude")
    if path is None:
        raise RuntimeError("claude CLI not found on PATH")
    return path


MCP_SERVER_NAME = "ai-workspace"
MCP_SERVER_PATH = Path(__file__).resolve().parents[1] / "mcp_server" / "workspace_server.py"

# The wall, as the API enforces it on every spawned app session. Mirrors
# docs/comms-protocol.md §5: Claude Code's own messaging is closed, and the
# file tools can't touch anything but the worker's folder and workers/_shared.
LOCKDOWN_SETTINGS = {
    "permissions": {
        "allow": ["Read", "Glob", "Grep", f"mcp__{MCP_SERVER_NAME}__*"],
        "deny": ["SendMessage", "ListAgents", "Edit", "Write", "Bash"],
    },
    "crossSessionInbound": "refuse",
}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(entry: dict, token: str | None) -> bool:
    if not token or not entry.get("token_hash"):
        return False
    return hmac.compare_digest(entry["token_hash"], hash_token(token))


def lockdown_mcp_config(session_id: str, api_url: str, token: str) -> dict:
    # The raw token lives only here, in the spawned session's MCP env. The
    # API keeps its hash; nothing ever returns the token in a response.
    return {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "type": "stdio",
                "command": sys.executable,
                "args": [str(MCP_SERVER_PATH)],
                "env": {
                    "SESSION_ID": session_id,
                    "SESSION_TOKEN": token,
                    "WORKSPACE_API_URL": api_url,
                },
            }
        }
    }


def spawn_argv(
    worker: str, task: str, session_uuid: str, token: str, shared_dir: Path, api_url: str
) -> list[str]:
    """The exact command for one locked-down app session.

    --restricted ignores user/project/local settings and confines the file
    tools to cwd plus --add-dir; --strict-mcp-config keeps every MCP server
    but ours out; dontAsk turns anything not allow-listed into a refusal,
    since a background session has nobody to answer a prompt.
    """
    return [
        claude_cli(),
        "--bg",
        "--restricted",
        "--strict-mcp-config",
        "--permission-mode", "dontAsk",
        "--session-id", session_uuid,
        "--name", worker,
        "--settings", json.dumps(LOCKDOWN_SETTINGS),
        "--mcp-config", json.dumps(lockdown_mcp_config(session_uuid[:8], api_url, token)),
        "--add-dir", str(shared_dir),
        f"Read CLAUDE.md and ../_shared/COMMS.md, then: {task}",
    ]


def write_lockdown_settings(worker_folder: Path) -> None:
    """The spec's per-worker settings.json, for anyone running `claude` in the
    folder by hand. Never overwrites a hand-curated one (e.g. app-master)."""
    settings = worker_folder / ".claude" / "settings.json"
    if settings.exists():
        return
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(LOCKDOWN_SETTINGS, indent=2) + "\n", encoding="utf-8")


def default_spawn_fn(argv: list[str], cwd: Path) -> str:
    """Run the spawn command and return what Claude Code printed."""
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout


def parse_spawned_id(stdout: str) -> str:
    parts = [p.strip() for p in stdout.strip().split("·")]
    if len(parts) < 2 or not parts[1]:
        raise RuntimeError(f"could not parse a session id from: {stdout!r}")
    return parts[1]


def default_stop_fn(session_id: str) -> None:
    subprocess.run([claude_cli(), "stop", session_id], capture_output=True, text=True, check=True)


def default_running_ids_fn() -> set[str] | None:
    """Ids of the background sessions Claude Code says are running right now,
    or None when that can't be determined (no CLI, command failed) -- None
    means "unknown", never "nothing is running"."""
    try:
        result = subprocess.run(
            [claude_cli(), "agents", "--json"], capture_output=True, text=True, check=True
        )
        entries = json.loads(result.stdout)
    except (RuntimeError, OSError, subprocess.CalledProcessError, ValueError):
        return None
    return {e["id"] for e in entries if e.get("kind") == "background" and "id" in e}


def create_app(
    workers_dir: Path | str | None = None,
    templates_dir: Path | str | None = None,
    sessions_db: Path | str | None = None,
    messages_log: Path | str | None = None,
    api_url: str | None = None,
    spawn_fn: Callable[[list[str], Path], str] | None = None,
    spawn_enabled: bool | None = None,
    stop_fn: Callable[[str], None] | None = None,
    running_ids_fn: Callable[[], set[str] | None] | None = None,
) -> FastAPI:
    workers_path = Path(workers_dir or os.environ.get("WORKERS_DIR", "workers"))
    workers_path.mkdir(parents=True, exist_ok=True)
    templates_path = Path(templates_dir or os.environ.get("TEMPLATES_DIR", "worker_templates"))
    sessions_db_path = Path(sessions_db or os.environ.get("SESSIONS_DB", "data/sessions.db"))
    sessions_store.init_db(sessions_db_path)
    run_records.init_table(sessions_db_path)
    messages_log_path = Path(messages_log or os.environ.get("MESSAGES_LOG", "runs/messages.jsonl"))
    messages_log_path.parent.mkdir(parents=True, exist_ok=True)
    api_url = api_url or os.environ.get("WORKSPACE_API_URL", "http://localhost:8000")
    shared_dir = workers_path / "_shared"
    spawn = spawn_fn or default_spawn_fn
    stop = stop_fn or default_stop_fn
    running_ids = running_ids_fn or default_running_ids_fn
    if spawn_enabled is None:
        spawn_enabled = os.environ.get("SPAWN_ENABLED", "true").lower() not in ("0", "false", "no")

    # Session ids belong to one machine (docs/comms-protocol.md §4): when the
    # server starts, close every row whose process is no longer running. Only
    # where the claude CLI exists -- i.e. not inside Docker -- and only when
    # the running set is actually known. Runs at startup, not import: the
    # CLI call takes seconds and importing a module must not shell out.
    def finalize_run(session_id: str, ended_at: datetime, status: str, error: str) -> None:
        """Close the run record behind a session. `status`/`error` apply only
        if the worker never reported -- its own verdict is never overwritten."""
        path = run_records.path_for_session(sessions_db_path, session_id)
        if path is None or not path.is_file():
            return
        record = run_records.finish(run_records.read_record(path), ended_at, status, error)
        run_records.write_record(workers_path, record)
        run_records.upsert(sessions_db_path, record, path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if spawn_enabled:
            ids = running_ids()
            if ids is not None:
                now = datetime.now(timezone.utc)
                for sid in sessions_store.reconcile(sessions_db_path, ids, now.isoformat()):
                    finalize_run(sid, now, "failed", "process gone before reporting a result")
        yield

    def log_message(from_id: str, to_id: str, outcome: str) -> None:
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "from": from_id,
            "to": to_id,
            "outcome": outcome,
        }
        with messages_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    app = FastAPI(title="ai-workspace", lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/workers")
    def list_workers() -> list[Worker]:
        return [
            Worker(name=folder.name, instructions=(folder / "CLAUDE.md").read_text(encoding="utf-8"))
            for folder in sorted(workers_path.iterdir())
            if (folder / "CLAUDE.md").is_file()
        ]

    @app.get("/workers/{name}")
    def get_worker(name: str) -> Worker:
        validate_name(name)
        folder = workers_path / name
        claude_md = folder / "CLAUDE.md"
        if not claude_md.is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
        return Worker(name=name, instructions=claude_md.read_text(encoding="utf-8"))

    @app.post("/workers", status_code=201)
    def create_worker(body: WorkerCreate) -> Worker:
        validate_name(body.name)
        # Optional initial content makes creation one call, so a client never
        # has to follow up with a PUT that could fail and leave a stub behind.
        instructions = body.instructions if body.instructions is not None else starter_instructions(body.name)
        try:
            instructions.encode("utf-8")
        except UnicodeEncodeError:
            raise HTTPException(status_code=400, detail="instructions must be valid UTF-8 text")
        folder = workers_path / body.name
        try:
            folder.mkdir()
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Worker '{body.name}' already exists")
        (folder / "CLAUDE.md").write_text(instructions, encoding="utf-8")
        return Worker(name=body.name, instructions=instructions)

    @app.put("/workers/{name}")
    def update_worker(body: WorkerUpdate, name: str) -> Worker:
        validate_name(name)
        folder = workers_path / name
        claude_md = folder / "CLAUDE.md"
        if not claude_md.is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
        try:
            body.instructions.encode("utf-8")
        except UnicodeEncodeError:
            raise HTTPException(status_code=400, detail="instructions must be valid UTF-8 text")
        claude_md.write_text(body.instructions, encoding="utf-8")
        return Worker(name=name, instructions=body.instructions)

    @app.delete("/workers/{name}", status_code=204)
    def delete_worker(name: str) -> None:
        validate_name(name)
        folder = workers_path / name
        if not (folder / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
        shutil.rmtree(folder)

    @app.get("/templates")
    def list_templates() -> list[Template]:
        if not templates_path.is_dir():
            return []
        templates = []
        for file in sorted(templates_path.glob("*.md")):
            try:
                text = file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            description, _ = parse_template(text)
            templates.append(Template(name=file.stem, description=description))
        return templates

    @app.get("/templates/{name}")
    def get_template(name: str) -> TemplateContent:
        validate_name(name)
        file = templates_path / f"{name}.md"
        if not file.is_file():
            raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
        _, body = parse_template(text)
        return TemplateContent(content=body)

    @app.post("/workers/{name}/skills", status_code=201)
    def write_skill(body: SkillCreate, name: str) -> Skill:
        validate_name(name)
        validate_name(body.skill_name)
        folder = workers_path / name
        if not folder.is_dir():
            raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
        try:
            body.content.encode("utf-8")
        except UnicodeEncodeError:
            raise HTTPException(status_code=400, detail="content must be valid UTF-8 text")
        skill_dir = folder / ".claude" / "skills" / body.skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(body.content, encoding="utf-8")
        return Skill(name=body.skill_name, content=body.content)

    @app.post("/sessions", status_code=201)
    def spawn_session(body: SessionCreate) -> Session:
        if not spawn_enabled:
            raise HTTPException(status_code=503, detail="spawning_disabled")
        validate_name(body.worker)
        worker_folder = workers_path / body.worker
        if not (worker_folder / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{body.worker}' not found")
        if body.trigger not in run_records.TRIGGERS:
            raise HTTPException(status_code=400, detail="bad_trigger")
        try:
            run_records.validate_tags(body.tags)
        except run_records.BadTag as exc:
            raise HTTPException(status_code=400, detail=f"bad_tag: {exc}")
        session_uuid = str(uuid.uuid4())
        session_id = session_uuid[:8]
        token = secrets.token_urlsafe(32)
        shared_dir.mkdir(exist_ok=True)
        write_lockdown_settings(worker_folder)
        argv = spawn_argv(body.worker, body.task, session_uuid, token, shared_dir, api_url)
        printed_id = parse_spawned_id(spawn(argv, worker_folder))
        if printed_id != session_id:
            raise RuntimeError(f"claude started {printed_id!r}, expected {session_id!r}")
        now = datetime.now(timezone.utc)
        started_at = now.isoformat()
        sessions_store.insert_session(
            sessions_db_path,
            session_id,
            body.worker,
            body.spawned_by,
            started_at,
            body.may_talk_to,
            hash_token(token),
        )
        record = run_records.new_record(
            body.worker,
            session_id,
            body.trigger,
            body.tags,
            now,
            (worker_folder / "CLAUDE.md").read_text(encoding="utf-8"),
        )
        path = run_records.write_record(workers_path, record)
        run_records.upsert(sessions_db_path, record, path)
        return Session(
            session_id=session_id,
            worker=body.worker,
            status="live",
            spawned_by=body.spawned_by,
            started_at=started_at,
            ended_at=None,
            may_talk_to=body.may_talk_to,
            run_id=record["run_id"],
        )

    @app.post("/sessions/{session_id}/result")
    def report_result(
        body: ResultReport, session_id: str, x_session_token: str | None = Header(default=None)
    ) -> dict:
        entry = sessions_store.get_session(sessions_db_path, session_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown_session")
        if not token_matches(entry, x_session_token):
            raise HTTPException(status_code=401, detail="bad_token")
        if entry["status"] != "live":
            raise HTTPException(status_code=409, detail="session_ended")
        if body.status not in run_records.REPORTABLE_STATUSES:
            raise HTTPException(status_code=400, detail="bad_status")
        path = run_records.path_for_session(sessions_db_path, session_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="unknown_run")
        record = run_records.read_record(path)
        try:
            record["tags"] = run_records.validate_tags(record["tags"] + body.tags)
        except run_records.BadTag as exc:
            raise HTTPException(status_code=400, detail=f"bad_tag: {exc}")
        record["status"] = body.status
        record["result"] = {"summary": body.summary} if body.summary is not None else record["result"]
        record["error"] = body.error
        for key in ("turns", "cost_usd"):
            if key in body.metrics:
                record["metrics"][key] = body.metrics[key]
        run_records.write_record(workers_path, record)
        run_records.upsert(sessions_db_path, record, path)
        return record

    @app.get("/runs")
    def list_runs(
        worker: str | None = None,
        status: str | None = None,
        tag: list[str] = Query(default=[]),
        since: str | None = None,
    ) -> list[dict]:
        return run_records.list_runs(sessions_db_path, worker, status, tag, since)

    @app.get("/sessions")
    def list_sessions(
        caller: str, x_session_token: str | None = Header(default=None)
    ) -> list[Session]:
        entry = sessions_store.get_session(sessions_db_path, caller)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Session '{caller}' not found")
        if not token_matches(entry, x_session_token):
            raise HTTPException(status_code=401, detail="bad_token")
        return [Session(**e) for e in sessions_store.list_reachable(sessions_db_path, caller)]

    @app.post("/sessions/{session_id}/messages", status_code=202)
    def send_message(
        body: MessageCreate, session_id: str, x_session_token: str | None = Header(default=None)
    ) -> dict:
        sender = sessions_store.get_session(sessions_db_path, body.from_)
        target = sessions_store.get_session(sessions_db_path, session_id)
        if sender is None or target is None:
            raise HTTPException(status_code=404, detail="unknown_session")
        # `from` is self-declared; the token proves the caller really is it.
        if not token_matches(sender, x_session_token):
            log_message(body.from_, session_id, "bad_token")
            raise HTTPException(status_code=401, detail="bad_token")
        if sender["status"] != "live" or target["status"] != "live":
            log_message(body.from_, session_id, "session_ended")
            raise HTTPException(status_code=409, detail="session_ended")
        if body.from_ not in target["may_talk_to"]:
            log_message(body.from_, session_id, "not_allowed")
            raise HTTPException(status_code=403, detail="not_allowed")
        # Accepted and logged only: forwarding into the target session is
        # not implemented yet, so this must not claim delivery.
        log_message(body.from_, session_id, "accepted")
        return {"accepted": True}

    @app.post("/sessions/{session_id}/end")
    def end_session(session_id: str) -> Session:
        entry = sessions_store.get_session(sessions_db_path, session_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown_session")
        if entry["status"] != "live":
            raise HTTPException(status_code=409, detail="session_ended")
        if spawn_enabled:
            stop(session_id)
        now = datetime.now(timezone.utc)
        ended_at = now.isoformat()
        sessions_store.mark_ended(sessions_db_path, session_id, ended_at)
        finalize_run(session_id, now, "failed", "ended before reporting a result")
        return Session(**{**entry, "status": "ended", "ended_at": ended_at})

    return app


app = create_app()
