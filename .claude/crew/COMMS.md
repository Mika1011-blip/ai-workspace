# Crew communication protocol

Talk to a **session**, addressed by its **session id** — never by name or
role. A role (`build-wizard`, etc.) is a label for humans; resolve it to its
current id via the registry before sending anything.

## Rules

1. **Address by session id, never by name.** Look up the role in the
   registry to find its id; the id is the only valid address.
2. **Read the registry right before every send.** Never rely on memory of a
   previously-seen id — it may have ended since. Re-read
   `.claude/crew/registry.json` immediately before each `SendMessage`.
3. **Only the lead writes the registry.** Workers read it to find each
   other; they never add, edit, or remove entries themselves.
4. **Crew talks only to crew + you.** A crew session may message other
   live crew sessions and you. There is no channel to app-side sessions —
   crew and app never message each other directly (see
   `docs/comms-protocol.md`).

## Registry entry

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

- `role` is a label for humans; the address is `session_id`.
- `folder`/`worktree` are relative to the repo root, or `null` if not
  applicable to the task.
- `status`: `live` → `ended`. An id is never reused; ended entries stay for
  history.

Full spec: `docs/comms-protocol.md`.
