# Level 2 — Baseline Round (no CLAUDE.md)

Date: 2026-10-26
Branch: `baseline` (no `CLAUDE.md` exists in the repo at this point)
Method: each task was sent to a **fresh, context-free Claude agent** (no memory of this conversation,
no access to this answer key) with *only* the exact box prompt. Results were graded against the
answer key and verified independently via `pytest`, `docker compose`, and `curl` against the running
container — not just taken on the agent's word.

## Scorecard

| Task | Corrections needed | What went wrong |
|---|---|---|
| 1 — Delete an agent | **0** | None. Matched spec exactly on first try. |
| 2 — Read an agent's CLAUDE.md | **0** | None. Matched spec exactly on first try. |
| 3 — Agent count on the page | **1** | Shows `(2)` / `(1)` / `(0)` instead of the required "2 agents" / "1 agent" wording. No singular/plural grammar handling at all — would need to be told explicitly to fix the copy. |
| **Total** | **1** | |

## Per-task detail

### Task 1 — Delete an agent — ✅ 0 corrections
- Added `DELETE /agents/{name}` in `app/main.py`, reusing the existing `NAME_PATTERN` validator on the path parameter.
- 404 on unknown agent (verified: `curl -X DELETE .../does-not-exist` → `404 {"detail":"Agent 'does-not-exist' not found"}`).
- 204 on success; verified `agents/test-b/` folder actually removed from disk after `DELETE /agents/test-b`.
- Unsafe names rejected before touching the filesystem: `DELETE /agents/..` → `405` (route pattern rejects it), `DELETE /agents/..%2Fsecret` → `404`. Neither deleted anything outside `agents/` (confirmed via `ls ..`). Minor nit: the ".." case returns 405 rather than the suggested 400/404, but nothing unsafe happened — not counted as a correction.
- Wrote 4 new pytest cases unprompted (delete removes folder, delete removes from list, missing agent → 404, bad names parametrized → 404/422).
- Ran the full suite itself before reporting done ("All 22 tests pass") — confirmed independently, 22/22 passed.
- No Delete button added to the UI (bonus, correctly treated as optional).

### Task 2 — Read an agent's CLAUDE.md — ✅ 0 corrections
- Added `GET /agents/{name}` (chose this path over `/agents/{name}/claude-md`; spec explicitly allows the path to vary) returning `{"name": ..., "instructions": ...}`.
- 404 on unknown agent (verified).
- Unsafe name `..%2Fsecret` → `404`, nothing read outside `agents/`.
- Hand check: fetched `test-a`, hand-edited `agents/test-a/CLAUDE.md` on disk to append a line, re-fetched the endpoint — new line appeared in the response, proving it reads live from disk rather than caching.
- Wrote 1 success case + 404/422 cases unprompted. Ran the suite itself ("All 31 tests pass") — confirmed independently, 31/31 passed.

### Task 3 — Agent count on the page — ⚠️ 1 correction
- Added `<span id="count">` next to the `<h1>Agents</h1>` title, updated via `count.textContent = \`(${agents.length})\`` inside the existing `loadAgents()` function.
- Functionally correct: updates on initial load and after every create (confirmed by reading the JS — `loadAgents()` is called after every successful POST), uses the existing `GET /agents` data, no new backend logic.
- **Gap:** displays `(0)` / `(1)` / `(2)` — not the "N agent(s)" phrasing the spec asked for ("page shows e.g. '2 agents' near the top", singular "1 agent"). This is the one point where a human would have had to say "no, write out '2 agents' not '(2)', and handle the singular case" before accepting the result.
- No "No agents yet" bonus added for the count specifically (a separate `#empty` paragraph with that text already existed in the codebase from v1, unrelated to this task).
- Did not write any test for this (page/HTML changes are hard to unit test — the task spec explicitly says this is acceptable, and no test was written). It also did not say how it verified the change, beyond "I added X" — it reported re-running the existing 31 backend tests, which is unrelated to verifying the frontend behavior it just added; it had no way to verify the browser behavior itself since it has no browser tool.

## Cross-cutting observations (things CLAUDE.md should target)

- **Tests**: all three agents wrote tests without being asked and ran them before declaring done, for the two backend tasks. Good baseline — nothing to fix here specifically from a CLAUDE.md standpoint, but worth confirming this habit is preserved after adding rules, not just a lucky baseline run.
- **Name validation**: both backend tasks correctly reused the existing `NAME_PATTERN` / FastAPI path-parameter validation rather than inventing new validation. No `../` vulnerabilities introduced.
- **Code style/location**: all three tasks put code in the right existing files (`app/main.py`, `tests/test_agents.py`, `app/static/index.html`) rather than creating new modules.
- **Startup**: no agent asked how to run tests or start the app — they inferred it from the existing project structure (`requirements.txt`, `docker-compose.yml`, `app/main.py`) without being told.
- **The one real gap**: frontend/copy-level correctness (Task 3's wording) is where a spec-following-but-not-"product sense" failure showed up — this is a believable target for a CLAUDE.md rule, e.g. "when displaying counts, use correct singular/plural English, not an opaque `(N)`" or more generally "match the exact UX wording described in the request."

## Repo state after this round

- Still on `baseline` branch, uncommitted changes in `app/main.py`, `app/static/index.html`, `tests/test_agents.py`, `BUILD_LOG.md`.
- `agents/test-a`, `agents/test-b`, `agents/test-c` exist on disk from setup + hand checks.
- Per the exercise's own cleanup step, this branch and the test agent folders should be deleted before starting the "after" round — not done yet, left for you to run (`git checkout main && git branch -D baseline`, then remove `agents/test-*`) since that's a destructive step outside the scope of "write the scorecard."
