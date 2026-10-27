# UI spec — the AI office

One page. The isometric office fills the viewport; everything else is a glass
pane on its edge. React 19 + TypeScript + Vite in `frontend/`, served by the
API (`/app` while the old pages still exist, then `/`).

## The office (main object)

Drawn in 2D canvas in the **Isometric Pastel** style: true 30° projection,
flat three-tone face shading, a floating lavender tile with a cream floor and
long soft shadows, white pill tags, Inter. Pure function of (state, time, theme):
same inputs, same frame. Code in `frontend/src/iso/` (ported helpers: iso
projection, `box`, `shade`, `cylinder`, `tag`, `numberTag`, `arrow`, painter's
sort, shadows, dot grid).

Two things on top of the reference look:

- **Hand-drawn surfaces.** Every printed face gets a paper grain and a faint
  ink wobble (seeded noise, cached per theme), so flat colour reads as drawn,
  not vector-clean.
- **Edge lines.** Every object is outlined with a thin dark line. Width and
  colour are theme settings (default 1.25 px, near-black ink).

Objects:

| Thing | Drawing | State → motion |
|---|---|---|
| Master (`app-master`) | central machine with a glass-top panel and dials | as a station, plus cards leaving on the conveyor when it dispatches |
| Worker station | desk + monitor + lamp + tiny person; a role prop (typewriter, easel, projector, magnifier, tape reel…) picked from the worker's name/role | appears: springy pop-in; idle: lamp dim; thinking: lamp pulses, cubes rise; using tool: fan spins + white tag with the tool name; waiting: slow blink + coral "?"; error: coral flash, ✖ badge, shake; stale: faded + "?" |
| Context gauge | a pile of cubes beside the desk, grows with `context_used` | colour shifts to coral past 80 % |
| Hand-off / message | a card riding a conveyor from the master to the station | one card per delivered message |
| Showroom | a small cinema tile with a marquee | clicking opens the gallery panel; a new published video lights the marquee |
| Name tags | white pill tag pinned above each station with icon + status word | never colour alone |

Clicking a station opens that worker's panel. Drag orbits nothing: the camera
is fixed with a slow push; wheel zooms within limits.

## Sidebar (collapsed by default)

A narrow glass strip (liquid-glass-react) on the left:

- **Top, pinned:** magnifying-glass button; hovering unfolds a text field that
  filters avatars by name.
- **Middle:** vertical list of worker avatars (initials on a pastel disc, a tiny
  status dot + the status word in the tooltip). Hover → name tooltip. Click →
  opens that worker's panel. Active session → a soft pulse.
- **Bottom, pinned:** add button → opens the panel in *new worker* mode
  (template, name, role, CLAUDE.md preview, create). Below it a small gallery
  button (same panel, gallery mode) and the theme button.

## Worker panel (the sidebar unfolds)

A wider glass pane. One per worker; the tab bar on top never changes:

- **Chat** — transcript from the event stream + run results, message field
  (forwarded into the running session), Start a session / End session.
- **Stats** — runs, success rate, cost, avg turns, avg duration, recent runs,
  activity tail.
- **Settings** — CLAUDE.md editor, toolkit (tools / MCP servers / skills from
  the catalog, read-only folders), installed skills, delete.

The panel remembers each worker's last tab. Esc or clicking the office
collapses it.

## Theme

A theme is a named colour set plus the edge settings, chosen from the theme
button and saved in `localStorage`:

```
{ name, background: [c0, c1, c2], slab, floor, ink, muted, accent, good,
  machine, machineDark, tagBg, edge: { color, width } }
```

Presets ship: *Pastel* (the reference: cream → lavender, coral accent),
*Mint*, *Dusk* (deeper lavender, warm ink), *Paper* (near-white, grey slab).
Edge width is a slider (0–3 px) and edge colour a picker; the glass panes
follow the theme's ink and accent.

## Data

The page draws only API data: `GET /workers`, `GET /workers/state`,
`GET /events` (SSE), `GET /runs?worker=&full=true`, `GET /workers/{w}/activity`,
`GET /catalog`, `GET|PUT /workers/{w}/toolkit`, `/sessions*`, `/projects*`.
No business logic in the scene.

## Later

Sound effects from the reference kit (wooden pop on a session start, ding on
success, buzz on error), off by default behind a toggle.
