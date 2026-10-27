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
3. In `.claude/crew/runs/<role>/`, open the record whose `session_id` is
   this id: set `ended_at` and `metrics.duration_ms`; if its `status` is
   still `running`, set it from what the worker actually delivered
   (`success` if its work was validated and merged, else `failed` with a
   one-line `error`) and put a one-line `result.summary`.
4. Append `{"at": "<now Z>", "event": "ended", "session_id": "<id>",
   "run_id": "<run_id>", "status": "<final status>"}` to
   `.claude/crew/runs/<role>/activity.jsonl`.
5. Report back which role/id was ended and the run's final status.

Lead-only — never delegate this to a worker.
