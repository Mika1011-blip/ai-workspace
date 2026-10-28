import hashlib
import hmac
import json
import os
import re
import asyncio
import queue as queue_module
import secrets
import shutil
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Callable

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app import activity, pipeline, projects, render, run_records, sdk_runner, sessions_store, toolkit
from app.runner import CliRunner, Runner, SpawnSpec

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


class ToolkitBody(BaseModel):
    """What a worker is allowed on every spawn; each name must be in the catalog."""

    tools: list[str] = []
    mcp_servers: list[str] = []
    read_from: list[str] = []  # repo-relative folders under workers/ or projects/
    skills: list[str] = []     # installed into the worker's .claude/skills/


class SessionCreate(BaseModel):
    worker: str
    task: str
    spawned_by: str | None = None
    may_talk_to: list[str] = []
    trigger: str = "manual"
    tags: list[str] = []
    # Per-spawn grants -- nothing is granted unless named here (see §4 of
    # docs/app-comms-plan.md): extra built-in tools, and extra directories
    # the worker may read, or read and write.
    tools: list[str] = []
    read_from: list[str] = []
    write_to: list[str] = []


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


class ProjectCreate(BaseModel):
    slug: str
    title: str
    format: str
    renderer: str = "ffmpeg"
    mode: str = "guided"


class ProjectPatch(BaseModel):
    title: str | None = None
    mode: str | None = None


class ExportRequest(BaseModel):
    dest_dir: str


class DecisionRequest(BaseModel):
    decision: str
    notes: str | None = None
    by: str | None = None


class TaskRequest(BaseModel):
    worker: str
    task: str
    tools: list[str] = []
    read_from: list[str] = []
    by: str | None = None


# The factory's brain cannot be removed through the API (vision §5).
PROTECTED_WORKERS = {"app-master"}


class MessageCreate(BaseModel):
    # `from` is optional: the token says who the sender is. If given, it
    # must agree with the token.
    from_: str | None = Field(default=None, alias="from")
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

# Every app session has these; --tools *defines* the built-in set, so the
# full list is always passed, with any granted tools appended.
BASE_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write"]
GRANTABLE_TOOLS = {"WebSearch", "WebFetch"}


def rule_path(directory: PurePath) -> str:
    """An absolute directory as a Claude Code permission-rule path: the "//"
    prefix means absolute, and on Windows the drive is a lower-case folder,
    C:/x/y -> //c/x/y. Verified live: //C:/x/y never matches, so with the
    old form the _shared deny rule silently did nothing on Windows."""
    if isinstance(directory, Path):
        directory = directory.resolve()
    posix = directory.as_posix()
    if directory.drive:
        posix = "/" + directory.drive.rstrip(":").lower() + posix[len(directory.drive):]
    return "//" + posix.lstrip("/")


def lockdown_settings(
    shared_dir: Path, read_only_dirs: list[Path] = (), tools: list[str] = (), mcp_servers: list[str] = ()
) -> dict:
    """The wall, as the API enforces it on every spawned app session. Mirrors
    docs/comms-protocol.md §5: Claude Code's own messaging is closed; the
    file tools reach only the worker's folder and the granted directories
    (that is --restricted's job), and read-only grants -- _shared always
    among them -- get deny rules for Edit and Write. A worker may build
    anything inside its own folder (or a write_to grant), never elsewhere."""
    read_only = [shared_dir, *read_only_dirs]
    deny = ["SendMessage", "ListAgents", "Bash"]
    for directory in read_only:
        deny += [f"Edit({rule_path(directory)}/**)", f"Write({rule_path(directory)}/**)"]
    return {
        "permissions": {
            "allow": [*BASE_TOOLS, *tools, f"mcp__{MCP_SERVER_NAME}__*", *[f"mcp__{n}__*" for n in mcp_servers]],
            "deny": deny,
        },
        "crossSessionInbound": "refuse",
        # Background sessions inside a git repo refuse every write until they
        # EnterWorktree (verified live). Our confinement is the worker's own
        # folder, not a worktree, so that guard is switched off for app
        # sessions only -- the lead's and the crew's sessions keep it.
        "worktree": {"bgIsolation": "none"},
    }


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(entry: dict, token: str | None) -> bool:
    if not token or not entry.get("token_hash"):
        return False
    return hmac.compare_digest(entry["token_hash"], hash_token(token))


def lockdown_mcp_config(api_url: str, token: str, extra: dict | None = None) -> dict:
    # The raw token lives only here, in the spawned session's MCP env. The
    # API keeps its hash; nothing ever returns the token in a response. The
    # token is the session's whole identity: `claude --bg` picks its own id
    # (it ignores --session-id), so the id isn't known until after launch
    # and the API resolves "who is calling" from the token instead.
    servers = {
        MCP_SERVER_NAME: {
            "type": "stdio",
            "command": sys.executable,
            "args": [str(MCP_SERVER_PATH)],
            "env": {"SESSION_TOKEN": token, "WORKSPACE_API_URL": api_url},
        }
    }
    # The worker's toolkit may add catalog servers; ours is never replaced.
    for name, definition in (extra or {}).items():
        if name != MCP_SERVER_NAME:
            servers[name] = definition
    return {"mcpServers": servers}


def spawn_argv(
    worker: str,
    task: str,
    token: str,
    shared_dir: Path,
    api_url: str,
    tools: list[str] = (),
    read_from: list[Path] = (),
    write_to: list[Path] = (),
    mcp_servers: dict | None = None,
) -> list[str]:
    """The exact command for one locked-down app session.

    --restricted ignores user/project/local settings and confines the file
    tools to cwd plus --add-dir; --strict-mcp-config keeps every MCP server
    but ours out; dontAsk turns anything not allow-listed into a refusal,
    since a background session has nobody to answer a prompt.

    --add-dir and --tools are variadic: they swallow every following
    argument until the next flag, so they go first and the single-valued
    --name sits right before the prompt. Never reorder that.
    """
    # The session's cwd is the worker's folder, so a relative directory here
    # would silently point nowhere (seen live: the project grant was ignored).
    add_dirs = [Path(d).resolve() for d in (shared_dir, *read_from, *write_to)]
    return [
        claude_cli(),
        "--bg",
        "--restricted",
        "--strict-mcp-config",
        "--add-dir", *[str(d) for d in add_dirs],
        "--tools", ",".join([*BASE_TOOLS, *tools]),
        "--permission-mode", "dontAsk",
        "--settings", json.dumps(lockdown_settings(shared_dir, list(read_from), list(tools), list(mcp_servers or {}))),
        "--mcp-config", json.dumps(lockdown_mcp_config(api_url, token, mcp_servers)),
        "--name", worker,
        f"Read CLAUDE.md and ../_shared/COMMS.md, then: {task}",
    ]


def sdk_options(spec: SpawnSpec, session_id: str):
    """spawn_argv's twin for the SDK runner: the same wall (--restricted,
    the same settings JSON, the same MCP server carrying the token), the
    same first prompt -- but we choose the session id, and the API key, if
    any, never reaches the session (it runs on this machine's login)."""
    from claude_agent_sdk import ClaudeAgentOptions

    add_dirs = [Path(d).resolve() for d in (spec.shared_dir, *spec.read_from, *spec.write_to)]
    options = ClaudeAgentOptions(
        cwd=str(spec.worker_folder),
        tools=[*BASE_TOOLS, *spec.tools],
        permission_mode="dontAsk",
        settings=json.dumps(lockdown_settings(
            spec.shared_dir, list(spec.read_from), list(spec.tools), list(spec.mcp_servers)
        )),
        setting_sources=["project"],
        add_dirs=[str(d) for d in add_dirs],
        mcp_servers=lockdown_mcp_config(spec.api_url, spec.token, spec.mcp_servers)["mcpServers"],
        strict_mcp_config=True,
        session_id=session_id,
        env=sdk_runner.session_env(),
        extra_args={"restricted": None},
    )
    return options, f"Read CLAUDE.md and ../_shared/COMMS.md, then: {spec.task}"


def write_lockdown_settings(worker_folder: Path, shared_dir: Path) -> None:
    """The spec's per-worker settings.json, for anyone running `claude` in the
    folder by hand. Never overwrites a hand-curated one (e.g. app-master)."""
    settings = worker_folder / ".claude" / "settings.json"
    if settings.exists():
        return
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(lockdown_settings(shared_dir), indent=2) + "\n", encoding="utf-8")


def default_spawn_fn(argv: list[str], cwd: Path) -> str:
    """Run the spawn command and return what Claude Code printed."""
    # The "·" in "backgrounded · <id> · <name>" is UTF-8; the Windows locale
    # would mangle it and leave garbage glued to the id.
    result = subprocess.run(
        argv, cwd=cwd, capture_output=True, encoding="utf-8", errors="replace", check=True
    )
    return result.stdout


def authenticate(db_path: Path, token: str | None) -> dict | None:
    """The session a token belongs to, or None."""
    if not token:
        return None
    return sessions_store.get_by_token_hash(db_path, hash_token(token))


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
    projects_dir: Path | str | None = None,
    api_url: str | None = None,
    spawn_fn: Callable[[list[str], Path], str] | None = None,
    spawn_enabled: bool | None = None,
    stop_fn: Callable[[str], None] | None = None,
    running_ids_fn: Callable[[], set[str] | None] | None = None,
    render_run: render.RunFn | None = None,
    runner: Runner | None = None,
    catalog_file: Path | str | None = None,
    frontend_dist: Path | str | None = None,
) -> FastAPI:
    # Resolved once: these paths are handed to other processes (spawned
    # sessions, docker) whose cwd is not ours.
    workers_path = Path(workers_dir or os.environ.get("WORKERS_DIR", "workers")).resolve()
    workers_path.mkdir(parents=True, exist_ok=True)
    templates_path = Path(templates_dir or os.environ.get("TEMPLATES_DIR", "worker_templates"))
    catalog_path = Path(catalog_file or os.environ.get("CATALOG_FILE", Path(__file__).resolve().parents[1] / "catalog.json"))
    frontend_dist_path = Path(frontend_dist or os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[1] / "frontend" / "dist"))

    def load_catalog() -> dict:
        # Re-read on every use: editing catalog.json must not need a restart.
        try:
            return toolkit.load_catalog(catalog_path, templates_path / "skills")
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=f"bad_catalog: {exc}")
    sessions_db_path = Path(sessions_db or os.environ.get("SESSIONS_DB", "data/sessions.db"))
    sessions_store.init_db(sessions_db_path)
    run_records.init_table(sessions_db_path)
    projects.init_table(sessions_db_path)
    messages_log_path = Path(messages_log or os.environ.get("MESSAGES_LOG", "runs/messages.jsonl"))
    messages_log_path.parent.mkdir(parents=True, exist_ok=True)
    api_url = api_url or os.environ.get("WORKSPACE_API_URL", "http://127.0.0.1:8000")
    shared_dir = workers_path / "_shared"
    projects_path = Path(projects_dir or os.environ.get("PROJECTS_DIR", "projects")).resolve()
    projects_path.mkdir(parents=True, exist_ok=True)
    projects.reindex(sessions_db_path, projects_path)

    def project_or_404(slug: str) -> tuple[Path, dict]:
        validate_name(slug)
        folder = projects_path / slug
        manifest = projects.read_manifest(folder)
        if manifest is None:
            raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
        return folder, manifest

    def resolve_grant(raw: str) -> Path:
        """A grantable directory: an existing folder under workers/ or
        projects/, given relative to the repo root. Anything else is a 400."""
        candidate = Path(raw)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise HTTPException(status_code=400, detail=f"bad_dir: {raw!r}")
        resolved = candidate.resolve()
        roots = [workers_path.resolve(), projects_path.resolve()]
        if not any(resolved == root or root in resolved.parents for root in roots):
            raise HTTPException(status_code=400, detail=f"bad_dir: {raw!r} is outside workers/ and projects/")
        if not resolved.is_dir():
            raise HTTPException(status_code=400, detail=f"bad_dir: {raw!r} does not exist")
        return resolved
    # Sessions are run through a Runner; the three callables are the CLI
    # runner's parts, kept so tests (and the host) can fake them one by one.
    # The SDK runner is the default; the CLI runner stays for RUNNER=cli and
    # for tests, which fake its parts.
    use_cli = os.environ.get("RUNNER", "sdk").lower() == "cli" or any(
        f is not None for f in (spawn_fn, stop_fn, running_ids_fn)
    )
    if runner is None and not use_cli:
        runner = sdk_runner.SdkRunner(sdk_options)
    if runner is None:
        runner = CliRunner(
            lambda spec: spawn_argv(
                spec.worker, spec.task, spec.token, spec.shared_dir, spec.api_url,
                tools=list(spec.tools), read_from=list(spec.read_from), write_to=list(spec.write_to),
                mcp_servers=spec.mcp_servers,
            ),
            spawn_fn or default_spawn_fn,
            stop_fn or default_stop_fn,
            running_ids_fn or default_running_ids_fn,
            parse_spawned_id,
        )
    if spawn_enabled is None:
        spawn_enabled = os.environ.get("SPAWN_ENABLED", "true").lower() not in ("0", "false", "no")

    # Session ids belong to one machine (docs/comms-protocol.md §4): when the
    # server starts, close every row whose process is no longer running. Only
    # where the claude CLI exists -- i.e. not inside Docker -- and only when
    # the running set is actually known. Runs at startup, not import: the
    # CLI call takes seconds and importing a module must not shell out.
    def close_handoff(session_id: str, status: str, summary: str | None) -> None:
        """A hand-off's session reported or died: update the project's hand-off log."""
        slug = projects.handoff_for_session(sessions_db_path, session_id)
        if slug is None:
            return
        folder = projects_path / slug
        manifest = projects.read_manifest(folder)
        if manifest is None:
            return
        for entry in reversed(manifest.setdefault("handoffs", [])):
            if entry["session_id"] == session_id and entry["status"] == "running":
                entry["status"] = status
                entry["summary"] = summary
                entry["ended_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                break
        projects.write_manifest(folder, manifest, datetime.now(timezone.utc))
        projects.upsert(sessions_db_path, manifest, folder)

    def finalize_run(session_id: str, ended_at: datetime, status: str, error: str) -> dict | None:
        """Close the run record behind a session. `status`/`error` apply only
        if the worker never reported -- its own verdict is never overwritten."""
        path = run_records.path_for_session(sessions_db_path, session_id)
        if path is None or not path.is_file():
            return None
        record = run_records.finish(run_records.read_record(path), ended_at, status, error)
        run_records.write_record(workers_path, record)
        run_records.upsert(sessions_db_path, record, path)
        return record

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if spawn_enabled:
            ids = runner.running_ids()
            if ids is not None:
                now = datetime.now(timezone.utc)
                for sid in sessions_store.reconcile(sessions_db_path, ids, now.isoformat()):
                    record = finalize_run(sid, now, "failed", "process gone before reporting a result")
                    studio.on_session_failed(sid, "process gone before reporting a result")
                    close_handoff(sid, "failed", "process gone before reporting a result")
                    entry = sessions_store.get_session(sessions_db_path, sid)
                    if entry is not None:
                        activity.log(
                            workers_path,
                            entry["worker"],
                            "reconciled",
                            {
                                "session_id": sid,
                                "run_id": record["run_id"] if record else None,
                                "status": record["status"] if record else None,
                                "reason": "process gone",
                            },
                        )
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

    @app.get("/gallery", include_in_schema=False)
    def gallery() -> FileResponse:
        return FileResponse(STATIC_DIR / "gallery.html")

    @app.get("/factory", include_in_schema=False)
    def factory() -> FileResponse:
        """The 3D floor (docs/3d-factory.md): draws /workers/state, nothing else."""
        return FileResponse(STATIC_DIR / "factory" / "index.html")

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{path:path}", include_in_schema=False)
    def spa(path: str = "") -> FileResponse:
        """The React app (frontend/dist, built with `npm run build`): a real
        file when the path names one, otherwise index.html so the app owns
        its routes. 503 until it has been built."""
        if path:
            candidate = (frontend_dist_path / path).resolve()
            if candidate.is_file() and frontend_dist_path.resolve() in candidate.parents:
                return FileResponse(candidate)
        index = frontend_dist_path / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=503, detail="frontend_not_built: run `npm install && npm run build` in frontend/")
        return FileResponse(index)

    @app.get("/workers")
    def list_workers() -> list[Worker]:
        return [
            Worker(name=folder.name, instructions=(folder / "CLAUDE.md").read_text(encoding="utf-8"))
            for folder in sorted(workers_path.iterdir())
            if (folder / "CLAUDE.md").is_file()
        ]

    @app.get("/workers/state")
    def workers_state() -> list[dict]:
        """One entry per worker for the factory floor (docs/3d-factory.md).
        Real state from the runner; a worker with no session is idle."""
        now = datetime.now(timezone.utc).isoformat()
        by_worker: dict[str, dict] = {}
        for st in runner.state():
            if st.worker in by_worker and by_worker[st.worker]["updated_at"] >= st.updated_at:
                continue
            by_worker[st.worker] = {
                "id": st.worker, "status": st.status, "current_task": st.current_task, "tool": st.tool,
                "context_used": st.context_used, "updated_at": st.updated_at, "session_id": st.session_id,
                "cost_usd": st.extra.get("cost_usd"), "turns": st.extra.get("turns"), "simulated": False,
            }
        out = []
        for folder in sorted(workers_path.iterdir()):
            if not (folder / "CLAUDE.md").is_file():
                continue
            out.append(by_worker.get(folder.name) or {
                "id": folder.name, "status": "idle", "current_task": None, "tool": None, "context_used": 0.0,
                "updated_at": now, "session_id": None, "cost_usd": None, "turns": None, "simulated": False,
            })
        return out

    @app.get("/events", include_in_schema=True)
    async def events(
        replay: int = Query(default=50, ge=0, le=500),
        limit: int | None = Query(default=None, ge=1),
    ) -> StreamingResponse:
        """Server-sent events: every state change of every running session
        (the floor's live feed). `replay` recent events come first, then
        the stream stays open; `limit` ends it after that many events
        (handy for curl and tests). A comment line every 15 s keeps the
        connection alive."""
        q = runner.subscribe()

        async def stream():
            sent = 0
            try:
                for event in list(runner.history)[-replay:] if replay else []:
                    yield f"event: state\ndata: {json.dumps(event)}\n\n"
                    sent += 1
                    if limit is not None and sent >= limit:
                        return
                while limit is None or sent < limit:
                    try:
                        event = await asyncio.to_thread(q.get, True, 15)
                    except queue_module.Empty:
                        yield ": keepalive\n\n"
                        continue
                    yield f"event: state\ndata: {json.dumps(event)}\n\n"
                    sent += 1
            finally:
                runner.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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
        if name in PROTECTED_WORKERS:
            raise HTTPException(status_code=403, detail=f"protected: '{name}' cannot be deleted")
        folder = workers_path / name
        if not (folder / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
        try:
            shutil.rmtree(folder)
        except OSError:
            # A session's process (typically its MCP server) still has the
            # folder open -- seen live on Windows after `claude stop`. Not a
            # server error: tell the caller to end the session and retry.
            raise HTTPException(
                status_code=409,
                detail=f"worker_busy: a process still holds '{name}'; end its sessions and retry",
            )

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

    @app.get("/catalog")
    def get_catalog() -> dict:
        """What may be attached to a worker on this host: built-in web tools,
        the MCP servers vetted in catalog.json, the skills in worker_templates/skills."""
        return toolkit.catalog_view(load_catalog())

    def worker_folder_or_404(name: str) -> Path:
        validate_name(name)
        folder = workers_path / name
        if not (folder / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
        return folder

    @app.get("/workers/{name}/toolkit")
    def get_toolkit(name: str) -> dict:
        return toolkit.read(worker_folder_or_404(name))

    @app.put("/workers/{name}/toolkit")
    def set_toolkit(body: ToolkitBody, name: str) -> dict:
        """Attach exactly these tools / MCP servers / read-only folders to the
        worker, and install the listed catalog skills. Every spawn applies it."""
        folder = worker_folder_or_404(name)
        try:
            kit = toolkit.validate(body.model_dump(), load_catalog())
        except toolkit.BadToolkit as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        kit["read_from"] = sorted({d.replace("\\", "/") for d in kit["read_from"]})
        for d in kit["read_from"]:
            resolve_grant(d)  # 400 bad_dir if it is outside workers/ or projects/, or missing
        result = toolkit.write(folder, kit, load_catalog())
        activity.log(workers_path, name, "toolkit_set", {k: result[k] for k in ("tools", "mcp_servers", "read_from", "skills")})
        return result

    @app.delete("/workers/{name}/toolkit/skills/{skill}")
    def remove_skill(name: str, skill: str) -> dict:
        folder = worker_folder_or_404(name)
        validate_name(skill)
        if not toolkit.remove_skill(folder, skill):
            raise HTTPException(status_code=404, detail=f"Skill '{skill}' is not installed on '{name}'")
        activity.log(workers_path, name, "skill_removed", {"skill": skill})
        return toolkit.read(folder)

    def start_session(
        worker: str,
        task: str,
        trigger: str = "manual",
        tags: list[str] = (),
        tools: list[str] = (),
        read_from: list[Path] = (),
        write_to: list[Path] = (),
        spawned_by: str | None = None,
        may_talk_to: list[str] = (),
    ) -> dict:
        """Spawn one locked-down app session and open its books. Shared by the
        endpoint and the pipeline; inputs are already validated/resolved."""
        if not spawn_enabled:
            raise HTTPException(status_code=503, detail="spawning_disabled")
        worker_folder = workers_path / worker
        if not (worker_folder / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{worker}' not found")
        token = secrets.token_urlsafe(32)
        shared_dir.mkdir(exist_ok=True)
        write_lockdown_settings(worker_folder, shared_dir)
        # The worker's toolkit applies on every spawn, on top of this spawn's grants.
        kit = toolkit.read(worker_folder)
        catalog = load_catalog()
        missing = sorted((set(kit["tools"]) - set(catalog["tools"])) | (set(kit["mcp_servers"]) - set(catalog["mcp_servers"])))
        if missing:
            raise HTTPException(status_code=409, detail=f"toolkit_not_in_catalog: {missing} (fix {worker}/toolkit.json)")
        tools = list(tools) + [t for t in kit["tools"] if t not in tools]  # request order, then the toolkit
        read_from = list(read_from) + [resolve_grant(d) for d in kit["read_from"]]
        mcp_servers = toolkit.server_configs(kit["mcp_servers"], catalog)
        session_id = runner.start(SpawnSpec(
            worker, task, token, worker_folder, shared_dir, api_url,
            tuple(tools), tuple(read_from), tuple(write_to), mcp_servers,
        ))
        now = datetime.now(timezone.utc)
        started_at = now.isoformat()
        sessions_store.insert_session(
            sessions_db_path, session_id, worker, spawned_by, started_at, list(may_talk_to), hash_token(token)
        )
        record = run_records.new_record(
            worker, session_id, trigger, list(tags), now,
            (worker_folder / "CLAUDE.md").read_text(encoding="utf-8"),
        )
        path = run_records.write_record(workers_path, record)
        run_records.upsert(sessions_db_path, record, path)
        activity.log(
            workers_path,
            worker,
            "spawned",
            {
                "session_id": session_id,
                "run_id": record["run_id"],
                "trigger": trigger,
                "spawned_by": spawned_by,
                "task": task,
                "tools": list(tools),
                "read_from": [str(p) for p in read_from],
                "write_to": [str(p) for p in write_to],
                "mcp_servers": sorted(mcp_servers),
            },
        )
        return {
            "session_id": session_id,
            "worker": worker,
            "status": "live",
            "spawned_by": spawned_by,
            "started_at": started_at,
            "ended_at": None,
            "may_talk_to": list(may_talk_to),
            "run_id": record["run_id"],
        }

    renderer = render.Renderer(render_run) if render_run else render.Renderer()
    studio = pipeline.Pipeline(
        projects_path, sessions_db_path, workers_path, start_session,
        render_step=renderer.render, publish_step=renderer.publish,
    )

    def session_over(session_id: str, info: dict) -> None:
        """The runner says a session is gone -- it finished, was stopped, or
        crashed. Close every book it had open; safe to call twice."""
        entry = sessions_store.get_session(sessions_db_path, session_id)
        if entry is None:
            return
        now = datetime.now(timezone.utc)
        outcome = info.get("outcome")
        reason = {
            "success": "ended without reporting a result",
            "stopped": "stopped before reporting a result",
        }.get(outcome, f"session error: {info.get('error')}")
        if entry["status"] == "live":
            sessions_store.mark_ended(sessions_db_path, session_id, now.isoformat())
        record = finalize_run(session_id, now, "failed", reason)
        if record is not None:
            metrics = record["metrics"]
            if info.get("cost_usd") is not None:
                metrics["cost_usd"] = info["cost_usd"]
            if info.get("turns"):
                metrics["turns"] = info["turns"]
            if info.get("usage"):
                metrics["tokens"] = info["usage"]
            run_records.write_record(workers_path, record)
            run_records.upsert(sessions_db_path, record, run_records.record_path(workers_path, record))
        studio.on_session_failed(session_id, reason)
        close_handoff(session_id, "failed", reason)
        activity.log(
            workers_path,
            entry["worker"],
            "session_over",
            {
                "session_id": session_id,
                "run_id": record["run_id"] if record else None,
                "status": record["status"] if record else None,
                "outcome": outcome,
                "cost_usd": info.get("cost_usd"),
                "turns": info.get("turns"),
            },
        )

    if getattr(runner, "on_end", "absent") is None:
        runner.on_end = session_over

    @app.post("/sessions", status_code=201)
    def spawn_session(
        body: SessionCreate, x_session_token: str | None = Header(default=None)
    ) -> Session:
        if not spawn_enabled:
            raise HTTPException(status_code=503, detail="spawning_disabled")
        validate_name(body.worker)
        if not (workers_path / body.worker / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{body.worker}' not found")
        if body.trigger not in run_records.TRIGGERS:
            raise HTTPException(status_code=400, detail="bad_trigger")
        try:
            run_records.validate_tags(body.tags)
        except run_records.BadTag as exc:
            raise HTTPException(status_code=400, detail=f"bad_tag: {exc}")
        bad_tools = sorted(set(body.tools) - GRANTABLE_TOOLS)
        if bad_tools:
            raise HTTPException(status_code=400, detail=f"bad_tool: {bad_tools} (grantable: {sorted(GRANTABLE_TOOLS)})")
        read_from = [resolve_grant(d) for d in body.read_from]
        write_to = [resolve_grant(d) for d in body.write_to]
        # A spawning session identifies itself by its token, not by a claim.
        spawned_by = body.spawned_by
        if spawned_by is None:
            spawner = authenticate(sessions_db_path, x_session_token)
            spawned_by = spawner["session_id"] if spawner else None
        return Session(
            **start_session(
                body.worker, body.task, body.trigger, body.tags, body.tools,
                read_from, write_to, spawned_by, body.may_talk_to,
            )
        )

    @app.post("/sessions/{session_id}/result")
    def report_result(
        body: ResultReport, session_id: str, x_session_token: str | None = Header(default=None)
    ) -> dict:
        # "me" = whoever the token says; a worker never needs to know its id.
        if session_id == "me":
            entry = authenticate(sessions_db_path, x_session_token)
            if entry is None:
                raise HTTPException(status_code=401, detail="bad_token")
            session_id = entry["session_id"]
        else:
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
        activity.log(
            workers_path,
            entry["worker"],
            "result_reported",
            {"session_id": session_id, "run_id": record["run_id"], "status": body.status},
        )
        # If this session was a pipeline stage, the project moves on; if it
        # was a hand-off from the master, the project's log closes it.
        studio.on_report(session_id, body.status, body.summary)
        close_handoff(session_id, body.status, body.summary)
        # Reported = done: the session ends once this turn is over.
        runner.finish(session_id)
        return record

    @app.post("/projects/{slug}/tasks", status_code=201)
    def assign_task(
        body: TaskRequest, slug: str, x_session_token: str | None = Header(default=None)
    ) -> Session:
        """The master hands a task to a worker inside a project
        (docs/vision-gap.md §2.1). The worker gets the project's artifacts/
        folder to read and write; the hand-off is logged in the manifest."""
        folder, manifest = project_or_404(slug)
        validate_name(body.worker)
        if not (workers_path / body.worker / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{body.worker}' not found")
        bad_tools = sorted(set(body.tools) - GRANTABLE_TOOLS)
        if bad_tools:
            raise HTTPException(status_code=400, detail=f"bad_tool: {bad_tools} (grantable: {sorted(GRANTABLE_TOOLS)})")
        read_from = [resolve_grant(d) for d in body.read_from]
        session = authenticate(sessions_db_path, x_session_token)
        by = session["session_id"] if session else (body.by or "app-master")
        artifacts_dir = folder / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)
        task = (
            f"Project '{slug}' ({manifest['title']}). Your working files are in {artifacts_dir.resolve()} "
            "(read and write). Next to every file or folder you produce, write a sidecar <name>.json with: "
            "kind, stage, run_id, worker, description (one line, mandatory), created_at.\n"
            f"Task from the master: {body.task}\n"
            "When finished, call report_result once: status 'success' with a one-line summary of what you "
            "produced and where, 'needs_input' if you are blocked (say on what), or 'failed'."
        )
        result = start_session(
            body.worker, task, trigger="event",
            tags=[f"project:{slug}", f"topic:{slug}"], tools=body.tools,
            read_from=read_from, write_to=[artifacts_dir], spawned_by=by,
        )
        manifest.setdefault("handoffs", []).append(
            {
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "by": by,
                "worker": body.worker,
                "task": body.task,
                "session_id": result["session_id"],
                "run_id": result["run_id"],
                "status": "running",
                "summary": None,
                "ended_at": None,
            }
        )
        if manifest["status"] == "created":
            manifest["status"] = "running"
        projects.write_manifest(folder, manifest, datetime.now(timezone.utc))
        projects.upsert(sessions_db_path, manifest, folder)
        projects.map_handoff(sessions_db_path, result["session_id"], slug)
        return Session(**result)

    @app.post("/projects/{slug}/render")
    def render_project(
        slug: str, renderer_name: str | None = Query(default=None, alias="renderer"),
        x_session_token: str | None = Header(default=None),
    ) -> dict:
        """Render and publish a project (dispatch mode's counterpart of the
        pipeline's render and publish steps). `?renderer=` overrides the
        project's renderer for this render and is saved on the project.
        Both steps are logged as `api` hand-offs; a failure leaves the
        project `failed` with the container's last line as the error."""
        folder, manifest = project_or_404(slug)
        if renderer_name is not None:
            if renderer_name not in projects.RENDERERS:
                raise HTTPException(status_code=400, detail=f"bad_renderer: one of {sorted(projects.RENDERERS)}")
            manifest["renderer"] = renderer_name
        if not render.has_input(folder, manifest["renderer"]):
            hint = "artifacts/07-render/*.html or artifacts/explainer.html" if manifest["renderer"] == "html" else "artifacts/07-render/"
            raise HTTPException(status_code=409, detail=f"nothing_to_render: {hint} is missing")
        session = authenticate(sessions_db_path, x_session_token)
        by = session["session_id"] if session else "app-master"
        now = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

        def log(step: str, ok: bool, output: str) -> None:
            manifest.setdefault("handoffs", []).append(
                {
                    "at": now(), "by": by, "worker": "api", "task": step, "session_id": None, "run_id": None,
                    "status": "success" if ok else "failed",
                    "summary": (output or "")[-300:].strip() or None, "ended_at": now(),
                }
            )

        ok, output = renderer.render(folder, manifest["renderer"])
        log("render", ok, output)
        if ok:
            ok, output = renderer.publish(folder)
            log("publish", ok, output)
        if ok:
            manifest["status"], manifest["stage"], manifest["error"] = "published", None, None
        else:
            last = (output or "failed").strip().splitlines()
            manifest["status"], manifest["error"] = "failed", f"render: {last[-1] if last else 'failed'}"
        projects.write_manifest(folder, manifest, datetime.now(timezone.utc))
        projects.upsert(sessions_db_path, manifest, folder)
        if not ok:
            raise HTTPException(status_code=502, detail=manifest["error"])
        return manifest

    @app.get("/runs/{run_id}")
    def get_run(run_id: str, wait: float = 0) -> dict:
        """One run record in full. With `wait` (seconds, max 600) the call
        long-polls until the run leaves `running`, so a dispatcher can chain
        hand-offs without busy-polling."""
        deadline = time.monotonic() + max(0.0, min(wait, 600.0))
        while True:
            rows = [r for r in run_records.list_runs(sessions_db_path) if r["run_id"] == run_id]
            if not rows:
                raise HTTPException(status_code=404, detail="unknown_run")
            record = run_records.read_record(Path(rows[0]["path"]))
            if record["status"] != "running" or time.monotonic() >= deadline:
                return record
            time.sleep(0.5)

    @app.post("/projects/{slug}/start")
    def start_project(slug: str) -> dict:
        validate_name(slug)
        try:
            return studio.start(slug)
        except pipeline.PipelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    @app.post("/projects/{slug}/decision")
    def decide_project(
        body: DecisionRequest, slug: str, x_session_token: str | None = Header(default=None)
    ) -> dict:
        validate_name(slug)
        # Who decided: a session (the producer worker) by its token, else a
        # person -- the name they give, or "mika" when they don't.
        session = authenticate(sessions_db_path, x_session_token)
        by = session["session_id"] if session else (body.by or "mika")
        try:
            return studio.decide(slug, body.decision, body.notes, by)
        except pipeline.PipelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    @app.get("/workers/{name}/activity")
    def worker_activity(name: str, limit: int = 100) -> list[dict]:
        validate_name(name)
        if not (workers_path / name / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Worker '{name}' not found")
        return activity.tail(workers_path, name, max(1, min(limit, 1000)))

    @app.post("/projects", status_code=201)
    def create_project(body: ProjectCreate) -> dict:
        validate_name(body.slug)
        validate_name(body.format)
        if body.renderer not in projects.RENDERERS:
            raise HTTPException(status_code=400, detail=f"bad_renderer: one of {sorted(projects.RENDERERS)}")
        if body.mode not in projects.MODES:
            raise HTTPException(status_code=400, detail=f"bad_mode: one of {sorted(projects.MODES)}")
        if not body.title.strip():
            raise HTTPException(status_code=400, detail="title must not be empty")
        folder = projects_path / body.slug
        manifest = projects.new_manifest(
            body.slug, body.title.strip(), body.format, body.renderer, body.mode, datetime.now(timezone.utc)
        )
        try:
            projects.create(folder, manifest)
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Project '{body.slug}' already exists")
        projects.upsert(sessions_db_path, manifest, folder)
        return manifest

    @app.get("/projects")
    def list_projects() -> list[dict]:
        out = []
        for row in projects.list_all(sessions_db_path):
            folder = projects_path / row["slug"]
            out.append(
                {
                    **{k: row[k] for k in ("slug", "title", "format", "renderer", "mode", "status", "stage", "updated_at")},
                    "has_preview": (folder / projects.PREVIEW).is_file(),
                    "has_final": (folder / projects.FINAL).is_file(),
                }
            )
        return out

    @app.get("/projects/{slug}")
    def get_project(slug: str) -> dict:
        folder, manifest = project_or_404(slug)
        return {
            **manifest,
            "artifacts": projects.artifacts(folder),
            "decisions": projects.decisions(folder),
            "has_preview": (folder / projects.PREVIEW).is_file(),
            "has_final": (folder / projects.FINAL).is_file(),
        }

    @app.patch("/projects/{slug}")
    def patch_project(body: ProjectPatch, slug: str) -> dict:
        folder, manifest = project_or_404(slug)
        if body.mode is not None:
            if body.mode not in projects.MODES:
                raise HTTPException(status_code=400, detail=f"bad_mode: one of {sorted(projects.MODES)}")
            manifest["mode"] = body.mode
        if body.title is not None:
            if not body.title.strip():
                raise HTTPException(status_code=400, detail="title must not be empty")
            manifest["title"] = body.title.strip()
        projects.write_manifest(folder, manifest, datetime.now(timezone.utc))
        projects.upsert(sessions_db_path, manifest, folder)
        # auto means nobody is at the checkpoint: a waiting project moves on.
        if body.mode == "auto" and manifest["status"] == "awaiting_approval":
            return studio.decide(slug, "approve", None, "auto")
        return manifest

    @app.delete("/projects/{slug}", status_code=204)
    def delete_project(slug: str) -> None:
        folder, _ = project_or_404(slug)
        try:
            shutil.rmtree(folder)
        except OSError:
            raise HTTPException(
                status_code=409,
                detail=f"project_busy: a process still holds '{slug}'; end its sessions and retry",
            )
        projects.remove(sessions_db_path, slug)

    @app.get("/projects/{slug}/artifacts/{path:path}")
    def get_artifact(slug: str, path: str) -> FileResponse:
        folder, _ = project_or_404(slug)
        real = projects.safe_artifact_path(folder, path)
        if real is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(real)

    @app.get("/projects/{slug}/final.mp4")
    def get_final(slug: str) -> FileResponse:
        folder, _ = project_or_404(slug)
        if not (folder / projects.FINAL).is_file():
            raise HTTPException(status_code=404, detail="not published")
        return FileResponse(folder / projects.FINAL, media_type="video/mp4")

    @app.get("/projects/{slug}/preview.jpg")
    def get_preview(slug: str) -> FileResponse:
        folder, _ = project_or_404(slug)
        if not (folder / projects.PREVIEW).is_file():
            raise HTTPException(status_code=404, detail="no preview")
        return FileResponse(folder / projects.PREVIEW, media_type="image/jpeg")

    @app.get("/projects/{slug}/download")
    def download_project(slug: str) -> Response:
        """The whole project as a zip, for the gallery's download button."""
        folder, _ = project_or_404(slug)
        return Response(
            projects.zip_bytes(folder),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
        )

    @app.post("/projects/{slug}/export")
    def export_project(body: ExportRequest, slug: str) -> dict:
        folder, _ = project_or_404(slug)
        dest = Path(body.dest_dir)
        if not dest.is_absolute() or not dest.is_dir():
            raise HTTPException(status_code=400, detail="dest_dir must be an existing absolute directory")
        if projects_path.resolve() in dest.resolve().parents or dest.resolve() == projects_path.resolve():
            raise HTTPException(status_code=400, detail="dest_dir must be outside projects/")
        try:
            target = projects.export(folder, dest)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=f"already exists: {exc}")
        return {"exported_to": str(target)}

    @app.get("/runs")
    def list_runs(
        worker: str | None = None,
        status: str | None = None,
        tag: list[str] = Query(default=[]),
        since: str | None = None,
        full: bool = False,
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> list[dict]:
        """The index rows, newest first. `full=true` returns the whole
        record of each (metrics, result, error) -- what the Stats tab shows."""
        rows = run_records.list_runs(sessions_db_path, worker, status, tag, since)[:limit]
        if not full:
            return rows
        out = []
        for row in rows:
            path = Path(row["path"]) if row.get("path") else None
            out.append(run_records.read_record(path) if path and path.is_file() else row)
        return out

    @app.get("/sessions")
    def list_sessions(
        caller: str | None = None, x_session_token: str | None = Header(default=None)
    ) -> list[Session]:
        # The token says who is asking; `caller`, if given, must agree.
        if caller is not None:
            entry = sessions_store.get_session(sessions_db_path, caller)
            if entry is None:
                raise HTTPException(status_code=404, detail=f"Session '{caller}' not found")
            if not token_matches(entry, x_session_token):
                raise HTTPException(status_code=401, detail="bad_token")
        else:
            entry = authenticate(sessions_db_path, x_session_token)
            if entry is None:
                raise HTTPException(status_code=401, detail="bad_token")
        return [
            Session(**e)
            for e in sessions_store.list_reachable(sessions_db_path, entry["session_id"])
        ]

    @app.post("/sessions/{session_id}/messages", status_code=202)
    def send_message(
        body: MessageCreate, session_id: str, x_session_token: str | None = Header(default=None)
    ) -> dict:
        x_session_token = x_session_token or None
        target = sessions_store.get_session(sessions_db_path, session_id)
        if target is None:
            raise HTTPException(status_code=404, detail="unknown_session")
        # No token and no `from` = the host (you, at the API or the lead's
        # MCP): it owns every session and may talk to any of them. Otherwise
        # the token says who the sender is; `from`, if given, must agree.
        if body.from_ is None and x_session_token is None:
            sender, sender_id = None, "host"
        else:
            if body.from_ is None:
                sender = authenticate(sessions_db_path, x_session_token)
                if sender is None:
                    raise HTTPException(status_code=401, detail="bad_token")
            else:
                sender = sessions_store.get_session(sessions_db_path, body.from_)
                if sender is None:
                    raise HTTPException(status_code=404, detail="unknown_session")
            sender_id = sender["session_id"]

        def outcome(name: str) -> None:
            # Global audit log plus both workers' own timelines, refusals included.
            log_message(sender_id, session_id, name)
            if sender is not None:
                activity.log(workers_path, sender["worker"], "message_out", {"to": session_id, "outcome": name})
            activity.log(workers_path, target["worker"], "message_in", {"from": sender_id, "outcome": name})

        if sender is not None:
            if not token_matches(sender, x_session_token):
                outcome("bad_token")
                raise HTTPException(status_code=401, detail="bad_token")
            if sender["status"] != "live":
                outcome("session_ended")
                raise HTTPException(status_code=409, detail="session_ended")
            if sender_id not in target["may_talk_to"]:
                outcome("not_allowed")
                raise HTTPException(status_code=403, detail="not_allowed")
        if target["status"] != "live":
            outcome("session_ended")
            raise HTTPException(status_code=409, detail="session_ended")
        # Delivered = handed to the running session as its next turn. The CLI
        # runner cannot do that; its messages are accepted and logged only.
        label = "the host" if sender is None else f"session {sender_id} ({sender['worker']})"
        delivered = runner.send(session_id, f"Message from {label}: {body.text}")
        outcome("delivered" if delivered else "accepted")
        return {"accepted": True, "delivered": delivered}

    @app.post("/sessions/{session_id}/end")
    def end_session(session_id: str, x_session_token: str | None = Header(default=None)) -> Session:
        entry = sessions_store.get_session(sessions_db_path, session_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown_session")
        # The host (no token) may end anything; a session may end itself or
        # a session it spawned, nothing else.
        x_session_token = x_session_token or None
        if x_session_token is not None:
            caller = authenticate(sessions_db_path, x_session_token)
            if caller is None:
                raise HTTPException(status_code=401, detail="bad_token")
            if caller["session_id"] not in (session_id, entry["spawned_by"]):
                raise HTTPException(status_code=403, detail="not_allowed")
        if entry["status"] != "live":
            raise HTTPException(status_code=409, detail="session_ended")
        if spawn_enabled:
            runner.stop(session_id)
        now = datetime.now(timezone.utc)
        ended_at = now.isoformat()
        sessions_store.mark_ended(sessions_db_path, session_id, ended_at)
        record = finalize_run(session_id, now, "failed", "ended before reporting a result")
        studio.on_session_failed(session_id, "session ended before reporting a result")
        close_handoff(session_id, "failed", "ended before reporting a result")
        activity.log(
            workers_path,
            entry["worker"],
            "ended",
            {
                "session_id": session_id,
                "run_id": record["run_id"] if record else None,
                "status": record["status"] if record else None,
            },
        )
        return Session(**{**entry, "status": "ended", "ended_at": ended_at})

    return app


app = create_app()
