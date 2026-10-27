---
paths:
  - "app/**"
  - "tests/**"
---

# Backend rules

- FastAPI. Request/response bodies are pydantic models.
- Errors: 404 unknown worker, 400 invalid name. Never 500 for user input.
- New endpoint = new tests in tests/ in the same change.

All routes live in `app/main.py` — there's no router module, DI layer, or service class yet. Keep new
endpoints there unless the file grows large enough to justify splitting.

## Worker storage

A worker is just a folder under `workers/` (path resolved from the `WORKERS_DIR` env var, default
`./workers`) containing a `CLAUDE.md` file. There is no database. `create_app(workers_dir=None)` is a
factory, not a module-level singleton — tests pass a `tmp_path` so they never touch the real
`workers/` folder; `app = create_app()` is what `uvicorn app.main:app` actually serves.

## Name validation

`NAME_PATTERN = r"^[a-z0-9-]{1,40}$"` is the single source of truth for a valid worker name —
lowercase letters, digits and hyphens, 1-40 characters (leading/trailing/double hyphens are allowed).
It is checked manually with `validate_name(name)`, which raises `HTTPException(400)` itself — names
are plain `str` fields/path params, not pydantic/FastAPI `pattern=` validation, so a bad name always
gets a 400, never FastAPI's automatic 422. This pattern is also the path-traversal guard: it has no
`.`, `/`, or uppercase, so a rejected name can never escape `workers/`. Any new endpoint that accepts
a worker name — by path or by body — must call `validate_name(name)` itself, never invent separate
validation.

Never read or write outside `workers/` from a worker endpoint. If an operation needs a path, build it
as `workers_path / name` after `validate_name(name)` has passed, not before.

## Tests

Every endpoint needs pytest coverage for: the success case, the not-found case (unknown worker name),
and the invalid-name case. Follow the existing pattern in `tests/test_workers.py` — a `client` fixture
built from `create_app(tmp_path)`, and a parametrized case for invalid names (reuse the existing bad-name
list: `../secret`, `Bad Name`, `UPPER`, empty, 41 chars, underscore) asserting `400`, plus the
`NEWLY_VALID_NAMES` list (`-leading`, `double--dash`) asserting success.
Run `pytest` yourself before saying a task is done.
