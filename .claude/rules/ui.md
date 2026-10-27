---
paths:
  - "static/**"
  - "templates/**"
---

# Web page rules

- Plain HTML/CSS/JS, no build step, no framework.
- Status is never shown by colour alone: add an icon or label.
- After a UI change, open the page with Playwright and check it.

`app/static/index.html` is a single static page: vanilla HTML/CSS/JS, no framework, no build step,
no bundler. It talks to the backend with plain `fetch` calls against `/agents`. Served via
`FileResponse` from the `/` route in `app/main.py` (not a `StaticFiles` mount), so it's currently the
only static asset wired up that way.

Keep new page logic in this same file and this same style unless the page grows enough to need
splitting — don't introduce a frontend framework or a build step for small additions.

See `.claude/rules/factory.md` for the separate `/factory` 3D view, which is a different static page
with its own tech stack.
