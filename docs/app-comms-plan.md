# App-side communication — implementation plan

Plan only — nothing here is built yet. Implements the app half of
`docs/comms-protocol.md` for a future worktree split. This doc is the
builder's reference; it is not shipped to any worker.

## 1. Session registry (SQLite, API-owned)

One table, one writer (the API itself — no other process touches it):

| column | type | notes |
|---|---|---|
| `session_id` | text, PK | printed by `claude --bg`, never reused |
| `worker` | text | the owning worker folder under `workers/` |
| `status` | text | `live` → `ended` |
| `spawned_by` | text | `session_id` of the spawner, or `app-master` |
| `started_at` / `ended_at` | text (ISO 8601) | `ended_at` null while live |
| `may_talk_to` | text (JSON array) | session ids this one may message |
| `token_hash` | text | SHA-256 of the session's token; the raw token exists only in that session's MCP env (`SESSION_TOKEN`) |

Mirrors the crew registry's shape (`docs/comms-protocol.md` §2) so the two
halves stay conceptually identical, just file-backed on the crew side and
SQLite-backed here.

## 2. New API endpoints (owner: worktree B — `app/main.py`, `tests/`)

```
POST /sessions
  body: { "worker": str, "task": str }
  -> 201 { "session_id": str, "worker": str, "status": "live" }
  Validates `worker` exists (a workers/<worker>/ folder with a CLAUDE.md).
  Launches the session scoped to that worker's folder (mirrors the crew's
  `claude --bg --name <worker> "..."`), inserts a `live` row.
  -> 503 "spawning_disabled" when SPAWN_ENABLED=false. Spawning is
     host-only: it needs the `claude` CLI and your login, which the
     Docker image doesn't have, so docker-compose sets this off.

GET /sessions?caller={session_id}
  header: X-Session-Token: <caller's token>
  -> 200, the sessions `caller` may reach: itself, every id in its own
     `may_talk_to`, plus app-master.
  -> 404 if `caller` is unknown; 401 "bad_token" if the token isn't
     caller's.

POST /sessions/{id}/messages
  body: { "from": str, "text": str }
  header: X-Session-Token: <from's token>
  -> 202 { "accepted": true }. Checked and logged only -- forwarding the
     text into `{id}`'s running session is NOT implemented yet, so the
     response must not say "delivered".
  -> 404 "unknown_session" if `id` or `from` doesn't exist in the table.
  -> 401 "bad_token" if the token isn't `from`'s -- `from` is otherwise
     just a claim any client could make.
  -> 409 "session_ended" if either is `ended`.
  -> 403 "not_allowed" if `from` isn't in `{id}`'s `may_talk_to`.
  Every attempt (success or refusal) is appended to `runs/messages.jsonl`
  with timestamp, `from`, `to`, and outcome.

POST /sessions/{id}/end
  -> 200, the entry with status "ended" and `ended_at` set. Runs
     `claude stop {id}` first (skipped when SPAWN_ENABLED=false, where
     there is no process to stop -- the row is still closed).
  -> 404 "unknown_session"; 409 "session_ended" if already ended.
```

**Startup reconciliation** (`docs/comms-protocol.md` §4: ids belong to
one machine): when the app starts with spawning enabled, it runs
`claude agents --json` and marks every `live` row whose id is no longer
running as `ended`. Inside Docker (spawning disabled) this is skipped --
the rows are the host's to reconcile.

Follows the existing conventions in `.claude/rules/api.md`: pydantic bodies,
404/400/403 only, never a bare 500, new tests alongside the endpoints.

## 3. MCP tools (owner: worktree A — alongside `mcp_server/workspace_server.py`)

```
spawn_session(worker: str, task: str) -> dict      # POST /sessions
list_sessions() -> list[dict]                     # GET /sessions?caller=<self>
send_to_session(session_id: str, text: str) -> dict  # POST /sessions/{id}/messages
end_session(session_id: str) -> dict              # POST /sessions/{id}/end
```

Same thin-wrapper style as the existing tools (`httpx` calls,
`raise_for_status()`, no local filesystem access). `list_sessions`/
`send_to_session` act as the calling session: the API sets `SESSION_ID`
and `SESSION_TOKEN` in the MCP server's env at spawn time (see §4), and
these tools send the token as `X-Session-Token` on every call that
claims to be `SESSION_ID`.

## 4. Per-worker lockdown (owner: worktree A — app-master writes these into
every worker it creates)

- **Enforced by the API on the command line**, not by files the worker
  could edit. `POST /sessions` starts every app session as
  `claude --bg --restricted --strict-mcp-config --permission-mode dontAsk
  --session-id <uuid> --settings <json> --mcp-config <json>
  --add-dir workers/_shared`, in the worker's own folder:
  - `--restricted` ignores user/project/local settings, removes Bash and
    the other code-running tools, and confines the file tools to cwd plus
    `--add-dir` — i.e. the worker's folder and `workers/_shared/`, nothing
    else in the repo.
  - `--strict-mcp-config` loads only the `--mcp-config` we pass: the
    `ai-workspace` server, with that session's `SESSION_ID` in its
    env. Nothing from the root `.mcp.json` (context7/playwright) can leak in,
    so no `disabledMcpjsonServers` list to maintain.
  - `--settings` denies `SendMessage`, `ListAgents`, `Edit`, `Write`,
    `Bash` and sets `"crossSessionInbound": "refuse"`; allows `Read`,
    `Glob`, `Grep` and `mcp__ai-workspace__*`.
  - `dontAsk`: anything not allow-listed is refused, since a background
    session has nobody to answer a prompt. `--restricted` also refuses
    `bypassPermissions`, so an app session can never run in the lead's
    mode — which is also why crew↔app messages would be held even if the
    built-in tools weren't denied.
  - The session UUID is generated by the API (`--session-id`), so the id
    is known — and handed to the MCP server — before the process exists.
- `workers/<name>/.claude/settings.json`: the same deny/allow set, written
  once if missing (never overwriting a hand-curated one like
  app-master's). Under `--restricted` it isn't even loaded; it's for
  anyone running `claude` in that folder by hand.
- Wiring a new tool/server for a specific worker is always a deliberate,
  explicit change to what the API passes — by the user or by whoever's
  building — never automatic.
- `workers/_shared/`: a read-only reference folder, no `CLAUDE.md` (so
  `GET /workers` never lists it as a worker — `app/main.py`'s `list_workers`
  already filters on `CLAUDE.md` presence). Every worker's `Read` scope
  includes this folder in addition to its own.
- `workers/_shared/COMMS.md` (worker-facing, positive-only — lives inside
  the shared folder, since it's the one thing beyond its own folder every
  wired-up worker needs to read): just the one line from
  `docs/comms-protocol.md` §7 — *"To contact another worker, use
  list_sessions and send_to_session only."* Nothing about what's denied;
  a worker only ever reads about what it can do.

## 4b. Run records

Every `POST /sessions` opens a run record at
`workers/<name>/runs/<run_id>.json` (status `running`) and indexes it in
the `runs` table of the same SQLite file. The worker fills in its part
with the `report_result` MCP tool (`POST /sessions/{id}/result`, its own
token required); `POST /sessions/{id}/end` and startup reconciliation
close the record, marking it `failed` if the worker never reported.
`GET /runs?worker=&status=&tag=&since=` queries the index. Schema, status
transitions and the tag vocabulary: `docs/run-record.md`.

Alongside, `workers/<name>/activity.jsonl` is each worker's timeline:
every spawn, report, message (both sides, refusals included), end and
reconciliation the API handles for it, readable via
`GET /workers/{name}/activity?limit=`.

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
