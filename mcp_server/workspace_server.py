"""MCP server exposing the ai-workspace agents API as tools for Claude.

Talks to the running FastAPI app over HTTP only; never reads or writes
`agents/` on disk directly.
"""

import os

import httpx
from fastmcp import FastMCP

API_BASE_URL = os.environ.get("WORKSPACE_API_URL", "http://localhost:8000")

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


if __name__ == "__main__":
    mcp.run()
