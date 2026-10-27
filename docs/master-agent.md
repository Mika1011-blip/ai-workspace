# Master agent — API/MCP contract

Frozen interface for building the master-agent feature across three parallel git
worktrees. Each worktree builds against this contract, not against each other's
code. Don't change these shapes without a sync across all three.

## 1. New API endpoints — owned by Worktree B (`app/main.py`, `tests/test_agents.py`)

```
GET  /templates
     -> 200, list[{ "name": str, "description": str }]
     Reads agent_templates/*.md, parses frontmatter "description" per file.

GET  /templates/{name}
     -> 200 { "content": str }   # raw CLAUDE.md text of the template
     -> 404 if agent_templates/{name}.md does not exist
     `name` validated with the existing NAME_PATTERN / validate_name().

POST /agents/{name}/skills
     body: { "skill_name": str, "content": str }
     -> 201, writes agents/{name}/.claude/skills/{skill_name}/SKILL.md
     -> 404 if agents/{name}/ does not exist
     Both `name` and `skill_name` validated with validate_name(). Parent
     dirs (.claude/skills/{skill_name}/) are created as needed.

PUT  /agents/{name}        # EXISTING — unchanged, do not touch
     Still the only way to edit an agent's CLAUDE.md.
```

Rules carried over from `.claude/rules/api.md`: `validate_name()` is called
first in every handler that takes a name (it's the only path-traversal
guard), 404/400 only — never a bare 500, and every new endpoint ships with
success + not-found + invalid-name tests.

## 2. New MCP tools — owned by Worktree A (`mcp_server/workspace_server.py`)

```
list_templates()                          -> GET /templates
get_template(name)                        -> GET /templates/{name}
update_claude_md(name, instructions)       -> PUT /agents/{name}   (existing endpoint, new tool name)
write_skill(name, skill_name, content)     -> POST /agents/{name}/skills
```

Same style as `list_agents`/`create_agent`: plain `httpx` calls against
`API_BASE_URL`, `response.raise_for_status()`, no direct filesystem access —
HTTP only. Docstrings cover what the tool does, name-pattern constraints,
the HTTP call it makes, and failure behavior (404/400 propagated as errors).

## 3. Template format — owned by Worktree C (`agent_templates/`)

```
agent_templates/<name>.md      # <name> matches ^[a-z0-9-]{1,40}$
---
description: <one line, shown by GET /templates>
---
<Markdown body — becomes the new agent's starter CLAUDE.md verbatim>
```

Body follows the existing agent shape (Role / What it does / What it must
not do / Output format). `agent_templates/` doesn't exist yet — Worktree C
creates it from scratch; no code changes.

## 4. File ownership

| Worktree | Owns | Must not touch |
|---|---|---|
| A | `mcp_server/workspace_server.py` + its tests | `app/main.py`, `agent_templates/` |
| B | `app/main.py`, `tests/test_agents.py`, `static/index.html` (only if UI needs it) | `mcp_server/`, `agent_templates/` |
| C | `agent_templates/*.md` | `app/main.py`, `mcp_server/` |

Each worktree branches from the same base commit and merges only the files
it owns. Any cross-cutting need (e.g. B needs a shared helper A also wants)
goes through a short sync between the worktree owners — never a silent edit
inside another worktree's folder.
