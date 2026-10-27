# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Web app to create and manage Claude agents. Each agent is a folder `agents/<name>/` with a `CLAUDE.md`.

## Working with Mika

- Explain what you did in plain language; Mika is still learning servers, Docker and git.
- Small steps: one feature per branch and per PR.
- Ask before deleting files or rewriting git history.
- When something fails, show the exact error before trying a fix.

## Commands

```bash
# Run the app locally (no Docker)
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# Run: docker compose up  → http://localhost:8000

# Tests: pytest  (run before saying a task is done)
pytest

# Run a single test
pytest tests/test_agents.py::test_duplicate_name_is_refused

# Run one parametrized case
pytest "tests/test_agents.py::test_bad_name_is_refused[../secret]"
```

There is no lint/format command configured in this repo.

## Rules

- Every endpoint gets pytest tests: success, not-found, invalid name.
- Agent names: lowercase letters, digits, dashes. Validate on every endpoint that takes a name.
- Never read or write outside `agents/` from agent endpoints.
- One feature per branch; open PRs with `/ship`.

## Layout

- Backend: see `.claude/rules/api.md` · Web page: `.claude/rules/ui.md` · 3D factory: `.claude/rules/factory.md`
- 3D factory spec: @docs/3d-factory.md
- `BUILD_LOG.md` is maintained automatically by two hooks — `.claude/hooks/log-step.sh` (the `Stop`
  hook in `.claude/settings.json`) and `.githooks/post-commit` (active via `core.hooksPath`). Don't
  edit `BUILD_LOG.md` by hand or disable these hooks to "fix" its output; fix the hook scripts instead.
