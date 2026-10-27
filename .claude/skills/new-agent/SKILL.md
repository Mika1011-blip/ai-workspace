---
name: new-agent
description: Turn a plain-language request like "make me an agent that summarizes AI news" into a new agent in the workspace. Picks a valid name, writes its CLAUDE.md, and creates it via the workspace MCP tools.
allowed-tools: mcp__mymcp__list_agents, mcp__mymcp__create_agent
---

Create a new agent from the user's request: $ARGUMENTS

## 1. Understand the request

Figure out the agent's purpose: what it does, and anything the user said (or
implied) about scope, tone, inputs, or output format.

Ask **at most one** clarifying question, and only if the request is genuinely
too vague to write a useful CLAUDE.md from (e.g. "make me an agent" with no
topic at all). If the request is workable, don't ask — make reasonable
assumptions and note them back to the user after creating the agent instead
of blocking on them.

## 2. Pick a name

Derive a slug from the purpose: lowercase, digits and hyphens only, 1-40
characters, matching `^[a-z0-9-]{1,40}$` (e.g. "summarizes AI news" ->
`ai-news-summarizer`). Keep it short and descriptive — a few words joined by
hyphens, not the whole request.

Call `list_agents` and check the slug isn't already taken. If it is, pick a
different, still-descriptive name (e.g. add a qualifier like `ai-news-digest`
instead of a numeric suffix) — don't re-ask the user for this, just resolve
it yourself.

## 3. Write the CLAUDE.md

Write clear, specific instructions for the new agent, covering:

- **Role** — one line: who this agent is / what it's for.
- **What it does** — the concrete task(s) it performs.
- **What it must not do** — explicit boundaries (scope limits, things to
  refuse or avoid, data/sources it shouldn't touch).
- **Output format** — the shape of what it should produce (e.g. a bulleted
  list, a short report, length limits, tone).

Keep it tight — a short, well-structured CLAUDE.md beats a long vague one.

## 4. Create it

Call `create_agent(name, instructions)` with the slug and the CLAUDE.md text
from step 3.

## 5. Report back

Tell the user the agent's name and a one-line summary of what it does. If you
made assumptions instead of asking in step 1, or renamed it to avoid a
collision in step 2, say so briefly.

## Constraints

- Only use the `list_agents` and `create_agent` MCP tools for this — never
  read or write files under `agents/` directly.
- If `create_agent` fails (e.g. name collision despite the check, or an
  invalid name), report the error and retry once with an adjusted name before
  giving up and asking the user.
