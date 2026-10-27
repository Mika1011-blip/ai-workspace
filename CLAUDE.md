# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Web app to create and manage Claude workers. Each worker is a folder `workers/<name>/` with a `CLAUDE.md`.

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

# Run: docker compose up  → http://127.0.0.1:8000

# Tests: pytest  (run before saying a task is done)
pytest

# Run a single test
pytest tests/test_workers.py::test_duplicate_name_is_refused

# Run one parametrized case
pytest "tests/test_workers.py::test_bad_name_is_refused[../secret]"

# Frontend (React, in frontend/): install, dev server, build, tests
cd frontend && npm install
npm run dev        # http://localhost:5173/app/ (API proxied to :8000)
npm run build      # -> frontend/dist, served by the API at /app
npm test           # vitest
```

There is no lint/format command configured in this repo.

## Rules

- Every endpoint gets pytest tests: success, not-found, invalid name.
- Worker names: lowercase letters, digits, dashes. Validate on every endpoint that takes a name.
- Never read or write outside `workers/` from worker endpoints.
- One feature per branch; open PRs with `/ship`.
- Before messaging another session, follow @.claude/crew/COMMS.md.

## Layout

- Backend: see `.claude/rules/api.md` · Web app (React, `frontend/`): `.claude/rules/ui.md` and `docs/ui-spec.md` · old 3D page: `.claude/rules/factory.md`
- 3D factory spec: @docs/3d-factory.md
- `BUILD_LOG.md` is maintained automatically by two hooks — `.claude/hooks/log-step.sh` (the `Stop`
  hook in `.claude/settings.json`) and `.githooks/post-commit` (active via `core.hooksPath`). Don't
  edit `BUILD_LOG.md` by hand or disable these hooks to "fix" its output; fix the hook scripts instead.
