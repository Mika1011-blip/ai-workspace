import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import sessions_store

STATIC_DIR = Path(__file__).parent / "static"

# Lowercase letters, digits and hyphens, 1-40 characters total. Rejecting
# everything else also keeps names from escaping the agents folder, since a
# match can never contain "." or "/".
NAME_PATTERN = r"^[a-z0-9-]{1,40}$"


def validate_name(name: str) -> None:
    if not re.fullmatch(NAME_PATTERN, name):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent name {name!r}: must match {NAME_PATTERN}",
        )


class AgentCreate(BaseModel):
    name: str


class AgentUpdate(BaseModel):
    instructions: str


class Agent(BaseModel):
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
    agent: str
    task: str
    spawned_by: str | None = None
    may_talk_to: list[str] = []


class Session(BaseModel):
    session_id: str
    agent: str
    status: str
    spawned_by: str | None
    started_at: str
    ended_at: str | None
    may_talk_to: list[str]


class MessageCreate(BaseModel):
    from_: str = Field(alias="from")
    text: str

    model_config = {"populate_by_name": True}


def starter_instructions(name: str) -> str:
    return f"# {name}\n\nDescribe what this agent does and how it should work.\n"


def parse_template(text: str) -> tuple[str, str]:
    """Split a template file into (description, body).

    Templates start with a `---`-delimited frontmatter block holding a single
    `description: ...` line, followed by the body that becomes the new
    agent's starter CLAUDE.md verbatim. Missing/malformed frontmatter falls
    back to an empty description and the whole text as the body, rather than
    raising -- template files are trusted content from `agent_templates/`.
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


def default_spawn_fn(agent: str, task: str, agent_folder: Path) -> str:
    """Launch a real background Claude Code session scoped to `agent_folder`,
    mirroring the crew's `claude --bg --name <agent> "..."`, and return the
    session id Claude Code prints."""
    result = subprocess.run(
        ["claude", "--bg", "--name", agent, f"Read CLAUDE.md, then: {task}"],
        cwd=agent_folder,
        capture_output=True,
        text=True,
        check=True,
    )
    parts = [p.strip() for p in result.stdout.strip().split("·")]
    if len(parts) < 2 or not parts[1]:
        raise RuntimeError(f"could not parse a session id from: {result.stdout!r}")
    return parts[1]


def create_app(
    agents_dir: Path | str | None = None,
    templates_dir: Path | str | None = None,
    sessions_db: Path | str | None = None,
    messages_log: Path | str | None = None,
    spawn_fn: Callable[[str, str, Path], str] | None = None,
) -> FastAPI:
    agents_path = Path(agents_dir or os.environ.get("AGENTS_DIR", "agents"))
    agents_path.mkdir(parents=True, exist_ok=True)
    templates_path = Path(templates_dir or os.environ.get("TEMPLATES_DIR", "agent_templates"))
    sessions_db_path = Path(sessions_db or os.environ.get("SESSIONS_DB", "data/sessions.db"))
    sessions_store.init_db(sessions_db_path)
    messages_log_path = Path(messages_log or os.environ.get("MESSAGES_LOG", "runs/messages.jsonl"))
    messages_log_path.parent.mkdir(parents=True, exist_ok=True)
    spawn = spawn_fn or default_spawn_fn

    def log_message(from_id: str, to_id: str, outcome: str) -> None:
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "from": from_id,
            "to": to_id,
            "outcome": outcome,
        }
        with messages_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    app = FastAPI(title="ai-workspace")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/agents")
    def list_agents() -> list[Agent]:
        return [
            Agent(name=folder.name, instructions=(folder / "CLAUDE.md").read_text(encoding="utf-8"))
            for folder in sorted(agents_path.iterdir())
            if (folder / "CLAUDE.md").is_file()
        ]

    @app.get("/agents/{name}")
    def get_agent(name: str) -> Agent:
        validate_name(name)
        folder = agents_path / name
        claude_md = folder / "CLAUDE.md"
        if not claude_md.is_file():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return Agent(name=name, instructions=claude_md.read_text(encoding="utf-8"))

    @app.post("/agents", status_code=201)
    def create_agent(body: AgentCreate) -> Agent:
        validate_name(body.name)
        folder = agents_path / body.name
        try:
            folder.mkdir()
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already exists")
        instructions = starter_instructions(body.name)
        (folder / "CLAUDE.md").write_text(instructions, encoding="utf-8")
        return Agent(name=body.name, instructions=instructions)

    @app.put("/agents/{name}")
    def update_agent(body: AgentUpdate, name: str) -> Agent:
        validate_name(name)
        folder = agents_path / name
        claude_md = folder / "CLAUDE.md"
        if not claude_md.is_file():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        try:
            body.instructions.encode("utf-8")
        except UnicodeEncodeError:
            raise HTTPException(status_code=400, detail="instructions must be valid UTF-8 text")
        claude_md.write_text(body.instructions, encoding="utf-8")
        return Agent(name=name, instructions=body.instructions)

    @app.delete("/agents/{name}", status_code=204)
    def delete_agent(name: str) -> None:
        validate_name(name)
        folder = agents_path / name
        if not (folder / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
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

    @app.post("/agents/{name}/skills", status_code=201)
    def write_skill(body: SkillCreate, name: str) -> Skill:
        validate_name(name)
        validate_name(body.skill_name)
        folder = agents_path / name
        if not folder.is_dir():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
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
        validate_name(body.agent)
        agent_folder = agents_path / body.agent
        if not (agent_folder / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Agent '{body.agent}' not found")
        session_id = spawn(body.agent, body.task, agent_folder)
        started_at = datetime.now(timezone.utc).isoformat()
        sessions_store.insert_session(
            sessions_db_path, session_id, body.agent, body.spawned_by, started_at, body.may_talk_to
        )
        return Session(
            session_id=session_id,
            agent=body.agent,
            status="live",
            spawned_by=body.spawned_by,
            started_at=started_at,
            ended_at=None,
            may_talk_to=body.may_talk_to,
        )

    @app.get("/sessions")
    def list_sessions(caller: str) -> list[Session]:
        reachable = sessions_store.list_reachable(sessions_db_path, caller)
        if reachable is None:
            raise HTTPException(status_code=404, detail=f"Session '{caller}' not found")
        return [Session(**entry) for entry in reachable]

    @app.post("/sessions/{session_id}/messages", status_code=202)
    def send_message(body: MessageCreate, session_id: str) -> dict:
        sender = sessions_store.get_session(sessions_db_path, body.from_)
        target = sessions_store.get_session(sessions_db_path, session_id)
        if sender is None or target is None:
            raise HTTPException(status_code=404, detail="unknown_session")
        if sender["status"] != "live" or target["status"] != "live":
            log_message(body.from_, session_id, "session_ended")
            raise HTTPException(status_code=409, detail="session_ended")
        if body.from_ not in target["may_talk_to"]:
            log_message(body.from_, session_id, "not_allowed")
            raise HTTPException(status_code=403, detail="not_allowed")
        log_message(body.from_, session_id, "delivered")
        return {"delivered": True}

    return app


app = create_app()
