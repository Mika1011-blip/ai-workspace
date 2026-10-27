# App-side communication — implementation plan

Plan only — nothing here is built yet. Implements the app half of
`docs/comms-protocol.md` for a future worktree split. This doc is the
builder's reference; it is not shipped to any agent.

## 1. Session registry (SQLite, API-owned)

One table, one writer (the API itself — no other process touches it):

| column | type | notes |
|---|---|---|
| `session_id` | text, PK | printed by `claude --bg`, never reused |
| `agent` | text | the owning agent folder under `agents/` |
| `status` | text | `live` → `ended` |
| `spawned_by` | text | `session_id` of the spawner, or `app-master` |
| `started_at` / `ended_at` | text (ISO 8601) | `ended_at` null while live |
| `may_talk_to` | text (JSON array) | session ids this one may message |

Mirrors the crew registry's shape (`docs/comms-protocol.md` §2) so the two
halves stay conceptually identical, just file-backed on the crew side and
SQLite-backed here.

## 2. New API endpoints (owner: worktree B — `app/main.py`, `tests/`)

```
POST /sessions
  body: { "agent": str, "task": str }
  -> 201 { "session_id": str, "agent": str, "status": "live" }
  Validates `agent` exists (an agents/<agent>/ folder with a CLAUDE.md).
  Launches the session scoped to that agent's folder (mirrors the crew's
  `claude --bg --name <agent> "..."`), inserts a `live` row.

GET /sessions?caller={session_id}
  -> 200, the sessions `caller` may reach: itself, every id in its own
     `may_talk_to`, plus app-master.
  -> 404 if `caller` is unknown.

POST /sessions/{id}/messages
  body: { "from": str, "text": str }
  -> 202 on success; forwards the message to `{id}`'s session.
  -> 404 "unknown_session" if `id` or `from` doesn't exist in the table.
  -> 409 "session_ended" if either is `ended`.
  -> 403 "not_allowed" if `from` isn't in `{id}`'s `may_talk_to`.
  Every attempt (success or refusal) is appended to `runs/messages.jsonl`
  with timestamp, `from`, `to`, and outcome.
```

Follows the existing conventions in `.claude/rules/api.md`: pydantic bodies,
404/400/403 only, never a bare 500, new tests alongside the endpoints.

## 3. MCP tools (owner: worktree A — alongside `mcp_server/workspace_server.py`)

```
spawn_session(agent: str, task: str) -> dict      # POST /sessions
list_sessions() -> list[dict]                     # GET /sessions?caller=<self>
send_to_session(session_id: str, text: str) -> dict  # POST /sessions/{id}/messages
```

Same thin-wrapper style as the existing tools (`httpx` calls,
`raise_for_status()`, no local filesystem access). `list_sessions`/
`send_to_session` need to know their own session id as the caller —
proposal: the API passes it in as an env var (e.g. `SESSION_ID`) when it
spawns the session, and these tools read it from `os.environ`.

## 4. Per-agent lockdown (owner: worktree A — app-master writes these into
every agent it creates)

- `agents/<name>/.claude/settings.json`: deny `SendMessage`, `ListAgents`;
  set `"crossSessionInbound": "refuse"`; scope `Read`/`Glob`/`Grep` to
  `agents/<name>/**` plus the shared folder below. Allow-list only the
  specific `mcp__<server>__*` tools this agent has actually been wired
  with — empty by default.
- `agents/<name>/.claude/settings.local.json`: `disabledMcpjsonServers`
  for every user-level MCP server known at creation time (same pattern
  already used for `agents/app-master`), so nothing leaks in by default.
  Wiring a new tool/server for a specific agent is always a deliberate,
  explicit edit — by the user or by whoever's building — never automatic.
- `agents/_shared/`: a read-only reference folder, no `CLAUDE.md` (so
  `GET /agents` never lists it as an agent — `app/main.py`'s `list_agents`
  already filters on `CLAUDE.md` presence). Every agent's `Read` scope
  includes this folder in addition to its own.
- `agents/COMMS.md` (worker-facing, positive-only — ships into every new
  agent): just the one line from `docs/comms-protocol.md` §7 — *"To
  contact another agent, use list_sessions and send_to_session only."*
  Nothing about what's denied; an agent only ever reads about what it can
  do.

## 5. Tests (owner: worktree B, for the API; worktree A for the MCP tools)

- Message to an unknown `session_id` → `404 unknown_session`.
- Message to an `ended` session → `409 session_ended`.
- Message from a sender not in the target's `may_talk_to` → `403
  not_allowed`.
- A crew session id (never present in the SQLite table at all, since crew
  and app registries are entirely separate) → `404 unknown_session` when
  used against any `/sessions` endpoint. This is the actual enforcement
  point for the crew/app wall — not a special case, just the natural
  result of the two registries never sharing ids.
