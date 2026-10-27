---
name: rebuild-registry
description: Reconcile the crew registry against actually-running sessions, e.g. after switching machines. Lead-only.
disable-model-invocation: true
allowed-tools: Bash(python scripts/crew.py:*), Read
---

Rebuild the crew registry.

1. Run `python scripts/crew.py rebuild`. It compares
   `.claude/crew/registry.json` with `claude agents --json`, marks every
   `live` entry whose id is no longer running as `ended`, closes its run
   record as `failed` ("process gone before reporting a result"), and
   appends a `reconciled` activity line.
2. Report what it printed: which ids were closed, which are still live.

Use this after switching machines or restarting Claude Code, before
spawning anything new. Lead-only — never delegate this to a worker.
