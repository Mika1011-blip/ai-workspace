"""MCP server exposing the ai-workspace agents API as tools for Claude.

Talks to the running FastAPI app over HTTP only; never reads or writes
`agents/` or `agent_templates/` on disk directly.
"""

import os

import httpx
from fastmcp import FastMCP

API_BASE_URL = os.environ.get("WORKSPACE_API_URL", "http://localhost:8000")
SESSION_ID = os.environ.get("SESSION_ID", "")

mcp = FastMCP("ai-workspace")


@mcp.tool
def list_agents() -> list[dict]:
    """List every agent in the workspace.

    Calls GET /agents on the ai-workspace API and returns each agent's name
    and current instructions (the contents of its CLAUDE.md). Use this to
    see what agents already exist, e.g. before creating a new one.
    """
    response = httpx.get(f"{API_BASE_URL}/agents")
    response.raise_for_status()
    return response.json()


@mcp.tool
def list_agent_names() -> list[str]:
    """List just the names of every agent in the workspace.

    Calls GET /agents and returns only the `name` field of each entry, to
    check whether a proposed name is taken without pulling every agent's
    full CLAUDE.md into context (use `list_agents` instead if you need the
    instructions too).
    """
    response = httpx.get(f"{API_BASE_URL}/agents")
    response.raise_for_status()
    return [agent["name"] for agent in response.json()]


@mcp.tool
def create_agent(name: str, instructions: str) -> dict:
    """Create a new agent with the given name and instructions.

    `name` must be lowercase letters, digits and hyphens only (1-40
    characters) to match the workspace's agent-name rules. `instructions`
    becomes the full contents of the new agent's CLAUDE.md.

    Calls POST /agents to create the agent, then PUT /agents/{name} to set
    its instructions, and returns the created agent's name and final
    instructions. Raises an error if an agent with that name already
    exists, or if the name is invalid.
    """
    create_response = httpx.post(f"{API_BASE_URL}/agents", json={"name": name})
    create_response.raise_for_status()

    update_response = httpx.put(
        f"{API_BASE_URL}/agents/{name}", json={"instructions": instructions}
    )
    update_response.raise_for_status()
    return update_response.json()


@mcp.tool
def list_templates() -> list[dict]:
    """List every agent template available in the workspace.

    Calls GET /templates and returns each template's name and one-line
    description. Use this to see what starting points exist before picking
    one with `get_template`.
    """
    response = httpx.get(f"{API_BASE_URL}/templates")
    response.raise_for_status()
    return response.json()


@mcp.tool
def get_template(name: str) -> dict:
    """Fetch the raw CLAUDE.md content of one agent template.

    `name` is the template's name as returned by `list_templates` (matches
    `^[a-z0-9-]{1,40}$`). Calls GET /templates/{name} and returns
    `{"content": str}`. Raises an error if no such template exists.
    """
    response = httpx.get(f"{API_BASE_URL}/templates/{name}")
    response.raise_for_status()
    return response.json()


@mcp.tool
def update_claude_md(name: str, instructions: str) -> dict:
    """Replace an existing agent's CLAUDE.md with new instructions.

    `name` must match `^[a-z0-9-]{1,40}$` and must already exist (create it
    first with `create_agent`). Calls PUT /agents/{name} and returns the
    agent's name and final instructions. Raises an error if the agent does
    not exist or the name/instructions are invalid.
    """
    response = httpx.put(f"{API_BASE_URL}/agents/{name}", json={"instructions": instructions})
    response.raise_for_status()
    return response.json()


@mcp.tool
def write_skill(name: str, skill_name: str, content: str) -> dict:
    """Write a skill file for an existing agent.

    `name` is the agent's name and `skill_name` is the skill's name, both
    matching `^[a-z0-9-]{1,40}$`. Calls POST /agents/{name}/skills with
    `{"skill_name": skill_name, "content": content}`, which writes
    `agents/{name}/.claude/skills/{skill_name}/SKILL.md`. Raises an error if
    the agent does not exist or either name is invalid.
    """
    response = httpx.post(
        f"{API_BASE_URL}/agents/{name}/skills",
        json={"skill_name": skill_name, "content": content},
    )
    response.raise_for_status()
    if not response.content:
        return {"status_code": response.status_code}
    return response.json()


@mcp.tool
def delete_agent(name: str) -> dict:
    """Delete an agent and everything in its folder.

    `name` must match `^[a-z0-9-]{1,40}$` and must already exist. Calls
    DELETE /agents/{name}, which removes the agent's CLAUDE.md and any
    skills written under it. Irreversible — there is no undo. Raises an
    error if the agent does not exist or the name is invalid.
    """
    response = httpx.delete(f"{API_BASE_URL}/agents/{name}")
    response.raise_for_status()
    return {"deleted": name}


@mcp.tool
def spawn_session(agent: str, task: str) -> dict:
    """Spawn a new background session for an existing agent.

    `agent` must match `^[a-z0-9-]{1,40}$` and must already exist. Calls
    POST /sessions with `{"agent": agent, "task": task, "spawned_by":
    SESSION_ID}` and returns the new session's id, agent, and status.
    Raises an error if the agent does not exist or the name is invalid.
    """
    response = httpx.post(
        f"{API_BASE_URL}/sessions",
        json={"agent": agent, "task": task, "spawned_by": SESSION_ID},
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def list_sessions() -> list[dict]:
    """List every session this one may reach.

    Calls GET /sessions?caller=<this session's id> and returns itself plus
    every session in its own `may_talk_to` list. Raises an error if this
    session isn't registered.
    """
    response = httpx.get(f"{API_BASE_URL}/sessions", params={"caller": SESSION_ID})
    response.raise_for_status()
    return response.json()


@mcp.tool
def send_to_session(session_id: str, text: str) -> dict:
    """Send a message to another session.

    Calls POST /sessions/{session_id}/messages with `{"from":
    SESSION_ID, "text": text}`. Raises an error if either session is
    unknown or ended, or if this session isn't allowed to message the
    target.
    """
    response = httpx.post(
        f"{API_BASE_URL}/sessions/{session_id}/messages",
        json={"from": SESSION_ID, "text": text},
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    mcp.run()
