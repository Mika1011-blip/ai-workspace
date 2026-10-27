---
paths:
  - "static/factory/**"
---

# 3D factory rules

Full spec: @docs/3d-factory.md — read it before touching anything under `static/factory/` or the
`/agents/state` endpoint.

Quick summary:

- Served at `/factory`, code lives in `static/factory/`. Plain Three.js from a version-pinned CDN —
  no build step, matching the rest of the frontend (see `.claude/rules/ui.md`).
- The 3D scene only renders data from `GET /agents/state`. No business logic in the scene — create,
  edit, and context-wipe actions all go through the API, never through scene code.
- Until agents actually run, `/agents/state` returns simulated (cycling) status, and the page must
  show a visible "SIMULATED" badge. Don't make the simulated data look indistinguishable from real
  status.
- A plain list view of the same `/agents/state` data must always be available as a fallback to the
  3D view.
- Status must never be shown by colour alone — pair it with an icon and a text label.
- `updated_at` older than 60s → render the station as "stale".
- Build in milestone order (see the spec's Milestones section) — don't jump ahead to streaming/live
  updates before the simulated-state milestone works end to end.
