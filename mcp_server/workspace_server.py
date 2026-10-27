"""MCP server exposing the ai-workspace workers API as tools for Claude.

Talks to the running FastAPI app over HTTP only; never reads or writes
`workers/` or `worker_templates/` on disk directly.
"""

import os

import httpx
from fastmcp import FastMCP

API_BASE_URL = os.environ.get("WORKSPACE_API_URL", "http://localhost:8000")
# Set by the API when it spawns this session. The token *is* this session's
# identity: the API resolves who is calling from it, so these tools never
# need to know their own session id.
SESSION_TOKEN = os.environ.get("SESSION_TOKEN", "")


def _auth() -> dict:
    return {"X-Session-Token": SESSION_TOKEN}

# One name everywhere -- root .mcp.json, app-master's .mcp.json, the API's
# --mcp-config, and the mcp__ai-workspace__* prefix in every allow list.
mcp = FastMCP("ai-workspace")


@mcp.tool
def list_workers() -> list[dict]:
    """List every worker in the workspace.

    Calls GET /workers on the ai-workspace API and returns each worker's name
    and current instructions (the contents of its CLAUDE.md). Use this to
    see what workers already exist, e.g. before creating a new one.
    """
    response = httpx.get(f"{API_BASE_URL}/workers")
    response.raise_for_status()
    return response.json()


@mcp.tool
def list_worker_names() -> list[str]:
    """List just the names of every worker in the workspace.

    Calls GET /workers and returns only the `name` field of each entry, to
    check whether a proposed name is taken without pulling every worker's
    full CLAUDE.md into context (use `list_workers` instead if you need the
    instructions too).
    """
    response = httpx.get(f"{API_BASE_URL}/workers")
    response.raise_for_status()
    return [worker["name"] for worker in response.json()]


@mcp.tool
def create_worker(name: str, instructions: str) -> dict:
    """Create a new worker with the given name and instructions.

    `name` must be lowercase letters, digits and hyphens only (1-40
    characters) to match the workspace's worker-name rules. `instructions`
    becomes the full contents of the new worker's CLAUDE.md.

    Calls POST /workers once with both fields and returns the created
    worker's name and instructions. One call, so a failure can't leave a
    half-made worker behind. Raises an error if a worker with that name
    already exists, or if the name or instructions are invalid.
    """
    response = httpx.post(
        f"{API_BASE_URL}/workers", json={"name": name, "instructions": instructions}
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def list_templates() -> list[dict]:
    """List every worker template available in the workspace.

    Calls GET /templates and returns each template's name and one-line
    description. Use this to see what starting points exist before picking
    one with `get_template`.
    """
    response = httpx.get(f"{API_BASE_URL}/templates")
    response.raise_for_status()
    return response.json()


@mcp.tool
def get_template(name: str) -> dict:
    """Fetch the raw CLAUDE.md content of one worker template.

    `name` is the template's name as returned by `list_templates` (matches
    `^[a-z0-9-]{1,40}$`). Calls GET /templates/{name} and returns
    `{"content": str}`. Raises an error if no such template exists.
    """
    response = httpx.get(f"{API_BASE_URL}/templates/{name}")
    response.raise_for_status()
    return response.json()


@mcp.tool
def update_claude_md(name: str, instructions: str) -> dict:
    """Replace an existing worker's CLAUDE.md with new instructions.

    `name` must match `^[a-z0-9-]{1,40}$` and must already exist (create it
    first with `create_worker`). Calls PUT /workers/{name} and returns the
    worker's name and final instructions. Raises an error if the worker does
    not exist or the name/instructions are invalid.
    """
    response = httpx.put(f"{API_BASE_URL}/workers/{name}", json={"instructions": instructions})
    response.raise_for_status()
    return response.json()


@mcp.tool
def write_skill(name: str, skill_name: str, content: str) -> dict:
    """Write a skill file for an existing worker.

    `name` is the worker's name and `skill_name` is the skill's name, both
    matching `^[a-z0-9-]{1,40}$`. Calls POST /workers/{name}/skills with
    `{"skill_name": skill_name, "content": content}`, which writes
    `workers/{name}/.claude/skills/{skill_name}/SKILL.md`. Raises an error if
    the worker does not exist or either name is invalid.
    """
    response = httpx.post(
        f"{API_BASE_URL}/workers/{name}/skills",
        json={"skill_name": skill_name, "content": content},
    )
    response.raise_for_status()
    if not response.content:
        return {"status_code": response.status_code}
    return response.json()


@mcp.tool
def delete_worker(name: str) -> dict:
    """Delete a worker and everything in its folder.

    `name` must match `^[a-z0-9-]{1,40}$` and must already exist. Calls
    DELETE /workers/{name}, which removes the worker's CLAUDE.md and any
    skills written under it. Irreversible — there is no undo. Raises an
    error if the worker does not exist or the name is invalid.
    """
    response = httpx.delete(f"{API_BASE_URL}/workers/{name}")
    response.raise_for_status()
    return {"deleted": name}


@mcp.tool
def spawn_session(worker: str, task: str) -> dict:
    """Spawn a new background session for an existing worker.

    `worker` must match `^[a-z0-9-]{1,40}$` and must already exist. Calls
    POST /sessions with `{"worker": worker, "task": task}` and this
    session's token, so the API records this session as the spawner.
    Returns the new session's id, worker, and status. Raises an error if
    the worker does not exist or the name is invalid.
    """
    response = httpx.post(
        f"{API_BASE_URL}/sessions", json={"worker": worker, "task": task}, headers=_auth()
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def list_sessions() -> list[dict]:
    """List every session this one may reach.

    Calls GET /sessions with this session's token and returns itself plus
    every session in its own `may_talk_to` list. Raises an error if the
    token isn't recognised.
    """
    response = httpx.get(f"{API_BASE_URL}/sessions", headers=_auth())
    response.raise_for_status()
    return response.json()


@mcp.tool
def send_to_session(session_id: str, text: str) -> dict:
    """Send a message to another session.

    Calls POST /sessions/{session_id}/messages with `{"text": text}` and
    this session's token, which tells the API who the sender is. Returns
    `{"accepted": true}` -- the API has checked and logged the message,
    but does not yet forward it into the target session. Raises an error
    if either session is unknown or ended, if the token isn't recognised,
    or if this session isn't allowed to message the target.
    """
    response = httpx.post(
        f"{API_BASE_URL}/sessions/{session_id}/messages", json={"text": text}, headers=_auth()
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def report_result(
    status: str,
    summary: str | None = None,
    tags: list[str] | None = None,
    metrics: dict | None = None,
    error: str | None = None,
) -> dict:
    """Record how this run went -- call it once, when the task is done.

    `status` is your own verdict: success, failed, skipped or needs_input.
    `summary` is a short plain-text result. `tags` are extra `key:value`
    tags from the fixed list (scope:research|code|docs|ops, topic:<slug>,
    severity:info|warn|error). `metrics` may carry `turns` and `cost_usd`.
    Calls POST /sessions/me/result with this session's token (the API
    knows which session "me" is from it) and returns the updated run
    record. Raises an error on an unknown status or tag.
    """
    response = httpx.post(
        f"{API_BASE_URL}/sessions/me/result",
        json={
            "status": status,
            "summary": summary,
            "tags": tags or [],
            "metrics": metrics or {},
            "error": error,
        },
        headers=_auth(),
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def end_session(session_id: str) -> dict:
    """End a session: stop its process and mark it ended in the registry.

    Calls POST /sessions/{session_id}/end and returns the closed entry.
    Raises an error if the session is unknown or already ended. Ended ids
    are never reused.
    """
    response = httpx.post(f"{API_BASE_URL}/sessions/{session_id}/end")
    response.raise_for_status()
    return response.json()


# --- studio projects (docs/animation-studio.md §7) ----------------------------


@mcp.tool
def create_project(slug: str, title: str, format: str, renderer: str = "ffmpeg", mode: str = "guided") -> dict:
    """Create a studio project: projects/<slug>/ with its manifest.

    `slug` and `format` match `^[a-z0-9-]{1,40}$`; `renderer` is one of
    ffmpeg, remotion, manim; `mode` is guided (stops at every review for a
    decision) or auto. Calls POST /projects and returns the manifest.
    Raises an error on a bad value or if the slug already exists.
    """
    response = httpx.post(
        f"{API_BASE_URL}/projects",
        json={"slug": slug, "title": title, "format": format, "renderer": renderer, "mode": mode},
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def list_projects() -> list[dict]:
    """Every project with its title, format, renderer, mode, status and
    current stage. Calls GET /projects."""
    response = httpx.get(f"{API_BASE_URL}/projects")
    response.raise_for_status()
    return response.json()


@mcp.tool
def get_project(slug: str) -> dict:
    """One project in full: manifest (status, stage, stage history with each
    worker's summary), every artifact with its description, and the
    decision trail. At a checkpoint, the last stage's summary is the
    reviewer's verdict. Calls GET /projects/{slug}."""
    response = httpx.get(f"{API_BASE_URL}/projects/{slug}")
    response.raise_for_status()
    return response.json()


@mcp.tool
def start_pipeline(slug: str) -> dict:
    """Run the project's pipeline from the first stage. Calls POST
    /projects/{slug}/start. Raises an error if a stage worker is missing
    or the project is already running or waiting for a decision."""
    response = httpx.post(f"{API_BASE_URL}/projects/{slug}/start")
    response.raise_for_status()
    return response.json()


@mcp.tool
def decide(slug: str, decision: str, notes: str | None = None) -> dict:
    """Close a guided-mode checkpoint: approve (next stage), revise (the
    maker runs again with the reviewer's notes plus `notes`), or skip.

    Calls POST /projects/{slug}/decision. The decision is recorded as made
    by this session when it has a token, else as "producer". Raises an
    error if the project isn't waiting for a decision.
    """
    response = httpx.post(
        f"{API_BASE_URL}/projects/{slug}/decision",
        json={"decision": decision, "notes": notes, "by": "producer"},
        headers=_auth(),
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def export_project(slug: str, dest_dir: str) -> dict:
    """Copy the whole project folder to <dest_dir>/<slug>/ on the host --
    `dest_dir` must be an existing absolute directory outside projects/.
    Never overwrites. Calls POST /projects/{slug}/export."""
    response = httpx.post(f"{API_BASE_URL}/projects/{slug}/export", json={"dest_dir": dest_dir})
    response.raise_for_status()
    return response.json()


@mcp.tool
def delete_project(slug: str, confirm: bool = False) -> dict:
    """Delete a project everywhere: host folder, Docker (bind mount) and
    gallery. Irreversible. Refuses unless `confirm` is true -- ask the user
    first. Calls DELETE /projects/{slug}."""
    if not confirm:
        raise ValueError(f"refusing to delete '{slug}': call again with confirm=True after the user agreed")
    response = httpx.delete(f"{API_BASE_URL}/projects/{slug}")
    response.raise_for_status()
    return {"deleted": slug}


if __name__ == "__main__":
    mcp.run()
