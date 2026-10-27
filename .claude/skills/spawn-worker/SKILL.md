---
name: spawn-worker
description: Spawn a crew worker in its own git worktree and register it. Lead-only.
disable-model-invocation: true
allowed-tools: Bash(python scripts/crew.py:*), Read, Write, AskUserQuestion
---

Spawn a crew worker: $ARGUMENTS

Usage: `/spawn-worker <role> "<task>" [--tag scope:code --tag topic:<slug>]`

1. If `.claude/crew/roles/<role>.md` doesn't exist, ask the lead (the user)
   for that role's brief — what it owns, what it must not touch, how it
   reports back — and save it there, ending the file with `Follow COMMS.md.`
2. Run `python scripts/crew.py spawn <role> "<task>" [--tag ...]`. It
   creates the worktree `.claude/worktrees/<role>-<id>` on branch
   `work/<role>-<id>`, starts `claude --bg` there in the lead's permission
   mode with no MCP servers (so it can't hang on an approval prompt),
   appends the registry entry, and writes the run record and activity line
   under `.claude/crew/runs/<role>/` (schema: `docs/run-record.md`).
3. Report back what it printed: role, session id, branch, worktree, run id.

When you later message this worker, append
`{"at": "<now Z>", "event": "message_out", "to": "<id>", "outcome": "sent"}`
to `.claude/crew/runs/<role>/activity.jsonl`, and `message_in` when it
answers — the crew has no API doing this for it.

Lead-only — never delegate this to a worker.
