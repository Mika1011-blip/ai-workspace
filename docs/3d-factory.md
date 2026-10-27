# 3D Factory view

A 3D view of the workspace: each worker is a workstation in a factory, and its live activity is shown on the station.

## What it shows
- One station per worker (from `GET /workers`). The master worker is a central control booth.
- Each station shows the worker's status with an animation **and** an icon + text label (never colour alone).
- Clicking a station opens a side panel: name, status, current task, and a link to edit its CLAUDE.md.
- A plain list view of the same data is always available as a fallback.

## Tech
- Plain Three.js, loaded from a CDN with a pinned version. No build step.
- Code lives in `static/factory/`. The page is served at `/factory`.
- The 3D code only draws data. No business logic in the scene; all changes (create, edit, wipe context) go through the API.

## Data contract
The scene renders only what this endpoint returns:

```
GET /workers/state
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

- Until workers really run, the backend returns **simulated** state (cycling statuses), and the page shows a visible "SIMULATED" badge. (Done: every entry carries `"simulated": false`, plus `session_id`, `cost_usd` and `turns`.)
- `updated_at` older than 60 s → show the station as "stale".

Live feed (milestone 4, done): `GET /events` is a server-sent-events stream of every
state change -- `event: state`, `data: {"at", "session_id", "worker", "status", "tool",
"context_used", "cost_usd", "turns", "text"?}`. `?replay=N` sends the last N events first
(default 50), `?limit=N` closes after N events, and a `: keepalive` comment arrives every 15 s.

## Milestones
1. `/factory` page: stations from `GET /workers`, simulated `GET /workers/state`, click → side panel, list fallback.
2. New workers appear as new stations without reloading.
3. Real status from worker runs (in progress, success, error) and run history in the panel.
4. Live updates streamed from running sessions (server-sent events); context gauge per station; clear/compact actions in the panel.

## Tests
- `GET /workers/state` returns one entry per worker, with valid status values.
- Simulated mode is flagged in the response (`"simulated": true` header or field).
