---
name: rebuild-registry
description: Reconcile the crew registry against actually-running sessions, e.g. after switching machines. Lead-only.
disable-model-invocation: true
allowed-tools: Bash(claude:*), Read, Edit
---

Rebuild the crew registry.

1. Run `claude agents --json` to list sessions actually running right now.
2. Read `.claude/crew/registry.json`.
3. For every entry still marked `"status": "live"` whose `session_id` is
   NOT in that running list, set `"status": "ended"` and `"ended_at"` to
   now (UTC ISO 8601).
4. Leave already-`ended` entries untouched, and leave any `live` entry
   whose id is still actually running untouched.
5. Report what changed: how many entries were marked ended, and what's
   still live.

Use this after switching machines or restarting Claude Code, before
spawning anything new. Lead-only — never delegate this to a worker.
