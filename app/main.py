import os
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

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


def create_app(agents_dir: Path | str | None = None, templates_dir: Path | str | None = None) -> FastAPI:
    agents_path = Path(agents_dir or os.environ.get("AGENTS_DIR", "agents"))
    agents_path.mkdir(parents=True, exist_ok=True)
    templates_path = Path(templates_dir or os.environ.get("TEMPLATES_DIR", "agent_templates"))

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

    return app


app = create_app()
