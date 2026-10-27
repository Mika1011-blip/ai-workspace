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
   claude --bg --name <role> "Read .claude/crew/roles/<role>.md and .claude/crew/COMMS.md, then: <task>"
   ```
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
5. Report back: the role, its session id, and the task it was given.

Lead-only — never delegate this to a worker.
