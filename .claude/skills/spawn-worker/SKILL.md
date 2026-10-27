---
name: spawn-worker
description: Spawn a background crew session for a role and register it in the crew registry. Lead-only.
disable-model-invocation: true
allowed-tools: Bash(claude:*), Read, Write, Edit, AskUserQuestion
---

Spawn a crew worker: $ARGUMENTS

Usage: `/spawn-worker <role> "<task>"`

1. If `.claude/crew/roles/<role>.md` doesn't exist, ask the lead (the user)
   for that role's brief — what it owns, what it must not touch, how it
   reports back — and save it there, ending the file with `Follow COMMS.md.`
   Then continue.
2. Run:
   ```
   claude --bg --permission-mode bypassPermissions --name <role> "Read .claude/crew/roles/<role>.md and .claude/crew/COMMS.md, then: <task>"
   ```
   The permission mode must match the lead's session, or Claude Code
   holds every message between them and a background worker can never
   approve the hold. The lead runs in `bypassPermissions`; change both
   together if that ever changes.
3. Read the printed id from the `backgrounded · <id> · <role>` output.
4. Read `.claude/crew/registry.json` and append a new entry:
   ```json
   {
     "session_id": "<id>",
     "role": "<role>",
     "folder": null,
     "worktree": null,
     "status": "live",
     "spawned_by": "lead",
     "started_at": "<now, UTC ISO 8601>",
     "ended_at": null,
     "may_talk_to": ["lead"]
   }
   ```
   Fill `folder`/`worktree` if the task specifies one, else leave `null`.
   Fill `may_talk_to` from what the task/role brief implies, defaulting to
   `["lead"]` only.
5. Write the run record `.claude/crew/runs/<role>/<run_id>.json` (schema:
   `docs/run-record.md`), with `run_id` = `<role>-<started_at with : -> ->-<id>`,
   `status: "running"`, `trigger: "manual"`, tags
   `["worker:<role>", "trigger:manual", "env:local"]` plus any
   `scope:`/`topic:` the task implies, `prompt_version` = first 7 hex of
   sha256 of `roles/<role>.md`, and `session_id` = the id.
6. Append one line to `.claude/crew/runs/<role>/activity.jsonl`:
   `{"at": "<now Z>", "event": "spawned", "session_id": "<id>", "run_id": "<run_id>", "trigger": "manual", "task": "<task>"}`.
7. Report back: the role, its session id, and the task it was given.

When you later message this worker, append `{"at", "event": "message_out",
"to": "<id>", "outcome": "sent"}` to the same file, and `message_in` when
it answers — the crew has no API doing this for it.

Lead-only — never delegate this to a worker.
