"""MCP server exposing the ai-workspace workers API as tools for Claude.

Talks to the running FastAPI app over HTTP only; never reads or writes
`workers/` or `worker_templates/` on disk directly.
"""

import os

import httpx
from fastmcp import FastMCP

API_BASE_URL = os.environ.get("WORKSPACE_API_URL", "http://127.0.0.1:8000")
# Set by the API when it spawns this session. The token *is* this session's
# identity: the API resolves who is calling from it, so these tools never
# need to know their own session id.
SESSION_TOKEN = os.environ.get("SESSION_TOKEN", "")


def _auth() -> dict:
    # No token (the lead's or your own MCP) = the host; the API treats a
    # missing header, not an empty one, as "the host is calling".
    return {"X-Session-Token": SESSION_TOKEN} if SESSION_TOKEN else {}

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
    this session's token, which tells the API who the sender is (no token
    = the host, who may message any session). Returns `{"accepted": true,
    "delivered": bool}`: delivered means the text was handed to the
    running session as its next turn, prefixed with who sent it; false
    means the session's runner cannot take messages (it was logged only).
    Raises an error if either session is unknown or ended, if the token
    isn't recognised, or if this session isn't allowed to message the
    target.
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
    The host may end any session; a session may end only itself or one it
    spawned (403 otherwise). Raises an error if the session is unknown or
    already ended. Ended ids are never reused.
    """
    response = httpx.post(f"{API_BASE_URL}/sessions/{session_id}/end", headers=_auth())
    response.raise_for_status()
    return response.json()


# --- dispatching (docs/vision-gap.md §2.1) ------------------------------------


@mcp.tool
def assign_task(project: str, worker: str, task: str, tools: list[str] | None = None, read_from: list[str] | None = None) -> dict:
    """Hand a task to a worker inside a project -- the default way work
    happens. The worker runs in its sandbox with the project's artifacts/
    folder to read and write; the hand-off is logged on the project and
    as a run record. `tools` may grant WebSearch/WebFetch; `read_from`
    extra folders (repo-relative, under workers/ or projects/).
    Calls POST /projects/{project}/tasks and returns the session, with
    `run_id` to pass to wait_for_run. Raises an error if the project or
    worker is unknown.
    """
    response = httpx.post(
        f"{API_BASE_URL}/projects/{project}/tasks",
        json={"worker": worker, "task": task, "tools": tools or [], "read_from": read_from or []},
        headers=_auth(),
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def render_project(project: str, renderer: str | None = None) -> dict:
    """Render and publish a project: the API runs the renderer image,
    extracts frames, and publishes a browser-safe final.mp4 + preview.jpg.
    `renderer` overrides the project's renderer: "ffmpeg" renders the
    plan in artifacts/07-render/ (still shots with captions); "html"
    records an HTML canvas animation (artifacts/explainer.html or
    artifacts/07-render/*.html, with window.seek / window.DURATION, sound
    from SOUND.renderOffline) -- use it for the style-explainer's work.
    Returns the manifest, now `published`. Calls POST
    /projects/{project}/render; raises an error if there is nothing to
    render or the render fails (the project is then `failed`, with the
    reason).
    """
    response = httpx.post(
        f"{API_BASE_URL}/projects/{project}/render",
        params={"renderer": renderer} if renderer else None,
        headers=_auth(), timeout=900,
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def wait_for_run(run_id: str, timeout_s: int = 300) -> dict:
    """Block until a run finishes (or `timeout_s` passes) and return its
    record: status (success / failed / needs_input / ... or still
    running on timeout), the worker's summary, tags, metrics. Use it right
    after assign_task to chain hand-offs. Calls GET /runs/{run_id}?wait=.
    """
    timeout_s = max(1, min(int(timeout_s), 600))
    response = httpx.get(f"{API_BASE_URL}/runs/{run_id}", params={"wait": timeout_s}, timeout=timeout_s + 30)
    response.raise_for_status()
    return response.json()


@mcp.tool
def get_run(run_id: str) -> dict:
    """One run record in full, right now (no waiting). Calls GET /runs/{run_id}."""
    response = httpx.get(f"{API_BASE_URL}/runs/{run_id}")
    response.raise_for_status()
    return response.json()


@mcp.tool
def list_runs(worker: str | None = None, status: str | None = None, tag: str | None = None) -> list[dict]:
    """Run records from the index, newest first, narrowed by worker, status
    and/or one `key:value` tag (e.g. project:first-reel). Calls GET /runs."""
    params = {k: v for k, v in (("worker", worker), ("status", status), ("tag", tag)) if v}
    response = httpx.get(f"{API_BASE_URL}/runs", params=params)
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


# --- toolkits (docs/vision-gap.md §2.3) ----------------------------------------


@mcp.tool
def get_catalog() -> dict:
    """What may be attached to a worker on this host: the built-in web tools,
    the MCP servers vetted in catalog.json, and the skills in
    worker_templates/skills/. Names and descriptions only. Calls GET /catalog.
    Nothing in the catalog is attached to anyone until set_toolkit says so.
    """
    response = httpx.get(f"{API_BASE_URL}/catalog")
    response.raise_for_status()
    return response.json()


@mcp.tool
def get_toolkit(worker: str) -> dict:
    """A worker's persistent toolkit: tools, MCP servers and read-only folders
    applied on every spawn, and the skills installed in its .claude/skills/.
    Calls GET /workers/{worker}/toolkit. Raises an error if the worker is
    unknown.
    """
    response = httpx.get(f"{API_BASE_URL}/workers/{worker}/toolkit")
    response.raise_for_status()
    return response.json()


@mcp.tool
def set_toolkit(
    worker: str,
    tools: list[str] | None = None,
    mcp_servers: list[str] | None = None,
    read_from: list[str] | None = None,
    skills: list[str] | None = None,
) -> dict:
    """Attach exactly these catalog items to a worker, for every future spawn:
    `tools` (WebSearch/WebFetch), `mcp_servers` (names from get_catalog),
    `read_from` (repo-relative folders under workers/ or projects/, read-only)
    and `skills` (installed from the catalog; already-installed skills stay --
    use remove_skill to take one away). Calls PUT /workers/{worker}/toolkit
    and returns the resulting toolkit. Raises an error (400) if a name is not
    in the catalog or a folder is not grantable, 404 if the worker is unknown.
    """
    response = httpx.put(
        f"{API_BASE_URL}/workers/{worker}/toolkit",
        json={"tools": tools or [], "mcp_servers": mcp_servers or [], "read_from": read_from or [], "skills": skills or []},
    )
    response.raise_for_status()
    return response.json()


@mcp.tool
def remove_skill(worker: str, skill: str) -> dict:
    """Uninstall one skill from a worker (deletes workers/{worker}/.claude/skills/{skill}/).
    Calls DELETE /workers/{worker}/toolkit/skills/{skill} and returns the
    toolkit afterwards. Raises an error if the worker or the skill is unknown.
    """
    response = httpx.delete(f"{API_BASE_URL}/workers/{worker}/toolkit/skills/{skill}")
    response.raise_for_status()
    return response.json()
