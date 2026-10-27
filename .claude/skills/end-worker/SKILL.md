---
name: end-worker
description: Stop a crew worker, close its books, and remove its worktree once merged. Lead-only.
disable-model-invocation: true
allowed-tools: Bash(python scripts/crew.py:*), Read
---

End a crew worker: $ARGUMENTS

Usage: `/end-worker <id> [--status success|failed|skipped|needs_input] [--summary "..."] [--force]`

1. Decide the run's final status from what the worker actually delivered:
   `success` only if its work was validated and merged into main.
2. Run `python scripts/crew.py end <id> --status <status> --summary "<one line>"`.
   It stops the session, marks the registry entry ended, closes the run
   record (`ended_at`, `duration_ms`, your status/summary unless the record
   already carries the worker's own verdict), appends the `ended` activity
   line, and removes the worktree and branch — but only if the branch is
   merged into main. Otherwise it keeps them and says so; pass `--force`
   to drop unmerged work deliberately.
3. Report back what it printed.

Lead-only — never delegate this to a worker.
