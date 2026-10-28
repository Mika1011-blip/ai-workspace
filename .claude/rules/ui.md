---
paths:
  - "frontend/**"
  - "app/static/**"
---

# Web app rules

The web app is a single-page React 19 + TypeScript app in `frontend/`, built
with Vite; the design is `docs/ui-spec.md` (read it before touching the
frontend). The API serves the built app from `frontend/dist` at `/app`
(`npm run build`); `npm run dev` serves it at http://localhost:5173/app/ with
API calls proxied to port 8000.

- One page: the isometric office (`src/office/`, 2D canvas, a function of
  state + time + theme, drawing kit in `src/iso/`; people and the cat keep a
  little movement state) plus the solid pane: the collapsed strip and the
  worker panel.
- The scene only draws data from the API. No business logic in the scene or
  in components; every change (create, edit, message, end) goes through
  `src/api.ts`, which is the only place URLs are built.
- Status is never shown by colour alone: an icon and the word, always
  (`StatusBadge`, the canvas tags).
- Themes: colours and edge lines come from the theme (`src/theme.ts`), on the
  canvas directly and in HTML through CSS variables. No hard-coded colours
  in components.
- Tests: Vitest + Testing Library in `src/**/*.test.ts(x)`; the canvas is
  mocked in component tests. Run `npm test` in `frontend/`
  and `pytest` at the root before saying a task is done.
- After a UI change, open the page with Playwright and look at it.

`app/static/` holds the old plain pages (`/`, `/gallery`, `/factory`); they
stay until the React app covers everything, then they go.
