import os
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

STATIC_DIR = Path(__file__).parent / "static"

# Lowercase letters and digits, separated by single dashes (e.g. "code-reviewer").
# Rejecting everything else also keeps names from escaping the agents folder.
NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class AgentCreate(BaseModel):
    name: str = Field(pattern=NAME_PATTERN, min_length=1, max_length=64)


class AgentUpdate(BaseModel):
    instructions: str


class Agent(BaseModel):
    name: str
    instructions: str


def starter_instructions(name: str) -> str:
    return f"# {name}\n\nDescribe what this agent does and how it should work.\n"


def create_app(agents_dir: Path | str | None = None) -> FastAPI:
    agents_path = Path(agents_dir or os.environ.get("AGENTS_DIR", "agents"))
    agents_path.mkdir(parents=True, exist_ok=True)

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
    def get_agent(name: str = PathParam(pattern=NAME_PATTERN, min_length=1, max_length=64)) -> Agent:
        folder = agents_path / name
        claude_md = folder / "CLAUDE.md"
        if not claude_md.is_file():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return Agent(name=name, instructions=claude_md.read_text(encoding="utf-8"))

    @app.post("/agents", status_code=201)
    def create_agent(body: AgentCreate) -> Agent:
        folder = agents_path / body.name
        try:
            folder.mkdir()
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already exists")
        instructions = starter_instructions(body.name)
        (folder / "CLAUDE.md").write_text(instructions, encoding="utf-8")
        return Agent(name=body.name, instructions=instructions)

    @app.put("/agents/{name}")
    def update_agent(
        body: AgentUpdate, name: str = PathParam(pattern=NAME_PATTERN, min_length=1, max_length=64)
    ) -> Agent:
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
    def delete_agent(name: str = PathParam(pattern=NAME_PATTERN, min_length=1, max_length=64)) -> None:
        folder = agents_path / name
        if not (folder / "CLAUDE.md").is_file():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        shutil.rmtree(folder)

    return app


app = create_app()
