# Communication protocol · crew and app

**Rule:** you talk to a **session**, by its **id**. Every session is spawned by its manager, written in a registry, and found by reading that registry. No discovery, no guessing by name.

```
CREW (dev, on your laptop)                 APP (in Docker)
lead ── spawns ──► build-* sessions        app-master ── spawns ──► app worker sessions
  │ writes                                   │ asks the API, which writes
  ▼                                          ▼
.claude/crew/registry.json                 data/registry.json  (API-owned)
  ▲ read by every crew session               ▲ read via list_sessions()
        ════════════ wall: no messages cross ════════════
```

## 1. Who does what
| | Crew | App |
|---|---|---|
| Manager (only writer) | lead session | app-master, **through the API** |
| Spawns a session with | `claude --bg --name <role> "<brief>"` | MCP tool `spawn_session(worker, task)` |
| Registry | `.claude/crew/registry.json` (gitignored, per machine) | `data/registry.json` (API writes it, nobody else) |
| Protocol file | `.claude/crew/COMMS.md` (committed) | `workers/_shared/COMMS.md` (committed) |
| Send a message | `SendMessage` to the session id | MCP tool `send_to_session(session_id, text)` |
| May talk to | crew sessions + you | app sessions + app-master + you |

Workers **read** the registry, never write it. Only the manager adds or ends entries. A worker can't register itself or rewrite who's who.

## 2. Registry entry
```json
{
  "session_id": "7c5dcf5d",
  "role": "build-wizard",
  "folder": "workers/news-digest",
  "worktree": ".claude/worktrees/build-wizard",
  "status": "live",
  "spawned_by": "lead",
  "started_at": "2026-10-27T16:00:00Z",
  "ended_at": null,
  "may_talk_to": ["lead", "build-master", "build-templates"]
}
```
- `role` is a label for humans. The **address is `session_id`**.
- Paths are **relative to the repo root**, so the file stays valid wherever the repo lives.
- `status`: `live` → `ended`. An id is never reused. Ended entries stay for history.

## 3. Lifecycle
1. **Spawn.** The lead runs `claude --bg --name build-wizard "Read .claude/crew/roles/build-wizard.md and .claude/crew/COMMS.md, then: …"`. Claude Code prints `backgrounded · 7c5dcf5d · build-wizard`.
2. **Register.** The lead writes the entry with id `7c5dcf5d`.
3. **Talk.** Before sending, the sender reads the registry, picks the entry by role, checks `status: live` and `may_talk_to`, then sends to the id.
4. **End.** When the worker's PR is merged, the lead stops it (`claude stop 7c5dcf5d`) and sets `status: ended`.

## 4. Moving to another machine or environment
Session ids belong to one machine. They don't travel.
- Committed: `COMMS.md`, the role briefs (`.claude/crew/roles/<role>.md`), the workers' folders. Everything needed to rebuild.
- Not committed: `registry.json`.
- On a new machine, the lead starts with **"rebuild the registry"**: mark every old entry `ended`, spawn the roles still needed, write the new ids. In the app, the API does the same at startup.

## 5. The wall
- Every app worker's `.claude/settings.json`: `"permissions": {"deny": ["SendMessage","ListAgents"]}` and `"crossSessionInbound": "refuse"`. So Claude Code messaging is closed, and app workers can only talk through `send_to_session`.
- The API checks `may_talk_to` on every send, and logs every message (`runs/messages.jsonl`).
- Sending to an `ended` or unknown id → refused (`session_ended` / `unknown_session`), never rerouted.

## 6. Where it lives
- **Rules** (`COMMS.md`): file on disk, committed, loaded via CLAUDE.md.
- **Crew registry**: file on disk (one writer, few changes). Re-read it **right before each send**, never import it into CLAUDE.md (it would go stale).
- **App registry**: inside the running API (SQLite-backed), reached only through `list_sessions` / `send_to_session`. Always fresh, safe with many writers, and enforces the rules.

## 7. What every CLAUDE.md gets (one line)
Crew: `Before messaging another session, follow @.claude/crew/COMMS.md.`
App: `To contact another worker, use list_sessions and send_to_session only. Rules: @../_shared/COMMS.md`
