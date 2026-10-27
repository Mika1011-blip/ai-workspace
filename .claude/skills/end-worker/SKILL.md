---
name: end-worker
description: Stop a crew session and mark it ended in the crew registry. Lead-only.
disable-model-invocation: true
allowed-tools: Bash(claude:*), Read, Edit
---

End a crew worker: $ARGUMENTS

Usage: `/end-worker <id>`

1. Run `claude stop <id>`.
2. In `.claude/crew/registry.json`, find the entry with this `session_id`
   and set `"status": "ended"` plus `"ended_at"` to now (UTC ISO 8601).
3. Report back which role/id was ended.

Lead-only — never delegate this to a worker.
