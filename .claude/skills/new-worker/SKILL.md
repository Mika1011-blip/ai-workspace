---
name: new-worker
description: Turn a plain-language request like "make me a worker that summarizes AI news" into a new worker in the workspace. Picks a valid name, writes its CLAUDE.md, and creates it via the workspace MCP tools.
allowed-tools: mcp__ai-workspace__list_workers, mcp__ai-workspace__create_worker
---

Create a new worker from the user's request: $ARGUMENTS

## 1. Understand the request

Figure out the worker's purpose: what it does, and anything the user said (or
implied) about scope, tone, inputs, or output format.

Ask **at most one** clarifying question, and only if the request is genuinely
too vague to write a useful CLAUDE.md from (e.g. "make me a worker" with no
topic at all). If the request is workable, don't ask — make reasonable
assumptions and note them back to the user after creating the worker instead
of blocking on them.

## 2. Pick a name

Derive a slug from the purpose: lowercase, digits and hyphens only, 1-40
characters, matching `^[a-z0-9-]{1,40}$` (e.g. "summarizes AI news" ->
`ai-news-summarizer`). Keep it short and descriptive — a few words joined by
hyphens, not the whole request.

Call `list_workers` and check the slug isn't already taken. If it is, pick a
different, still-descriptive name (e.g. add a qualifier like `ai-news-digest`
instead of a numeric suffix) — don't re-ask the user for this, just resolve
it yourself.

## 3. Write the CLAUDE.md

Write clear, specific instructions for the new worker, covering:

- **Role** — one line: who this worker is / what it's for.
- **What it does** — the concrete task(s) it performs.
- **What it must not do** — explicit boundaries (scope limits, things to
  refuse or avoid, data/sources it shouldn't touch).
- **Output format** — the shape of what it should produce (e.g. a bulleted
  list, a short report, length limits, tone).

Keep it tight — a short, well-structured CLAUDE.md beats a long vague one.

## 4. Create it

Call `create_worker(name, instructions)` with the slug and the CLAUDE.md text
from step 3.

## 5. Report back

Tell the user the worker's name and a one-line summary of what it does. If you
made assumptions instead of asking in step 1, or renamed it to avoid a
collision in step 2, say so briefly.

## Constraints

- Only use the `list_workers` and `create_worker` MCP tools for this — never
  read or write files under `workers/` directly.
- If `create_worker` fails (e.g. name collision despite the check, or an
  invalid name), report the error and retry once with an adjusted name before
  giving up and asking the user.
