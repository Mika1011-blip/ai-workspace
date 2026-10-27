# 3D Factory view

A 3D view of the workspace: each agent is a workstation in a factory, and its live activity is shown on the station.

## What it shows
- One station per agent (from `GET /agents`). The master agent is a central control booth.
- Each station shows the agent's status with an animation **and** an icon + text label (never colour alone).
- Clicking a station opens a side panel: name, status, current task, and a link to edit its CLAUDE.md.
- A plain list view of the same data is always available as a fallback.

## Tech
- Plain Three.js, loaded from a CDN with a pinned version. No build step.
- Code lives in `static/factory/`. The page is served at `/factory`.
- The 3D code only draws data. No business logic in the scene; all changes (create, edit, wipe context) go through the API.

## Data contract
The scene renders only what this endpoint returns:

```
GET /agents/state
[
  {
    "id": "researcher",
    "status": "idle" | "thinking" | "using_tool" | "waiting" | "error",
    "current_task": "Summarize today's AI news",   // or null
    "tool": "WebSearch",                            // or null
    "context_used": 0.42,                           // 0..1 share of context window
    "updated_at": "2026-10-26T19:10:00Z"
  }
]
```

- Until agents really run, the backend returns **simulated** state (cycling statuses), and the page shows a visible "SIMULATED" badge.
- `updated_at` older than 60 s → show the station as "stale".

## Milestones
1. `/factory` page: stations from `GET /agents`, simulated `GET /agents/state`, click → side panel, list fallback.
2. New agents appear as new stations without reloading.
3. Real status from agent runs (in progress, success, error) and run history in the panel.
4. Live updates streamed from running sessions (server-sent events); context gauge per station; clear/compact actions in the panel.

## Tests
- `GET /agents/state` returns one entry per agent, with valid status values.
- Simulated mode is flagged in the response (`"simulated": true` header or field).
