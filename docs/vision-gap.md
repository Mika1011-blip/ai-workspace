# Vision → build: the gap, and the decisions that close it

*27 Oct 2026. Companion to the product vision ("ai-workspace is a 3D media
factory you run from your browser"). What exists, what the vision changes,
and what was decided.*

## 1. What the vision calls for vs what exists

| Vision | Status |
|---|---|
| Workers (CLAUDE.md), managed only through the API | built — `/workers`, MCP tools (`agents` became `workers`) |
| Master that creates workers from a prompt | built — `app-master` |
| Projects on the table, media with descriptions, save / clean | built — `projects/<slug>/`, sidecars, `/gallery`, export, delete with confirm |
| Every run writes a tagged JSON record; stats from records | records + index + `GET /runs` built; Stats tab not yet |
| Messaging by session id; crew/app wall | built, proven live |
| Code-made media | ffmpeg video built; SVG/HTML→PNG and Remotion not yet |
| Live state (`/workers/state`), thought bubbles, SSE | built — `/workers/state` and `GET /events` (SSE); bubbles are the page's job |
| Sidebar · worker panel (Chat / Stats / Settings) · 3D floor | not built |
| Per-worker toolkit from a vetted catalog | built — `catalog.json` + `worker_templates/skills/` are the catalog; `workers/<w>/toolkit.json` the toolkit (`/catalog`, `/workers/{w}/toolkit`, MCP `set_toolkit`) |
| app-master undeletable | built with the dispatcher (below) |
| Runner on the Claude Agent SDK | built — `app/sdk_runner.py`, default; `RUNNER=cli` keeps `claude --bg` |

## 2. Three decisions

### 2.1 The master dispatches; the gated pipeline is optional
The fixed stage order (script → review → storyboard → … → publish) turned
any prompt into eight sessions, deserved or not. **Default path now:**

```
prompt → app-master → fitting worker(s) from the roster → assign_task
      → worker writes artifacts + a run record into the project
      → master reads the result → next hand-off, or done
```

- Hand off **immediately** to whoever fits, judged from the workers that
  exist; **if none fits, the master does it itself** (a sandboxed copy of
  the master runs the task in the project) or, if the need will recur,
  creates a worker first.
- Review is the master's call, not a gate the machine forces.
- A hand-off to a worker **always lands in a project**; the master may
  answer small prompts in chat with no project.
- Every hand-off is a run record tagged `project:<slug>` and a line in
  the project's **hand-off log**, so nothing the master decides is hidden.
- The review-gated pipeline (`docs/animation-studio.md` §2) stays as a
  tool the master may run when a production warrants it. Default off.

### 2.2 App workers move to the Claude Agent SDK runner
Nearly every live defect so far was a `claude --bg` quirk: it ignores
`--session-id`, refuses writes until `EnterWorktree`, needs a trusted
workspace (so `workers/` must stay inside the repo), leaves MCP servers
holding folders after `stop`, and reports no cost or turns. The SDK removes
all of that and gives the live events the floor needs (status, tool,
thinking/idle) plus message forwarding into a session. Crew workers keep
`claude --bg`.

### 2.3 Toolkit = catalog, in two layers
A **catalog** of MCP servers and skills vetted on the host; **attach** to a
worker writes a persistent per-worker grant that every spawn applies. Today
grants are per spawn only; the persistent layer is the next management work.

## 3. Answers to the vision's open questions

| | Decision |
|---|---|
| Media engines | **All code-made.** Claude for text; SVG/HTML→PNG for images; ffmpeg now, Remotion later for video. No generator APIs, no keys. |
| Save all | **Zip download** in the gallery (built: `GET /projects/{slug}/download`); `export_project` to a host folder stays. |
| Workers persist? | **Yes, a fixed team.** The master creates one only when nobody fits, never retires one on its own. |
| Chat with a worker during a project | **Yes** — the Chat tab, on top of message forwarding (SDK runner). The master is reachable when `may_talk_to` includes it. |
| Budget | **None.** Media is $0 by construction; the records keep `cost_usd` so it can be seen, nothing enforces it. |

## 4. Order of work
1. Master as dispatcher: `assign_task`, `wait_for_run`, `get_run`,
   `list_runs`; hand-off log; dispatcher brief; app-master undeletable.
2. One real project through the master.
3. SDK runner for app workers → real `/workers/state`, SSE, forwarding,
   cost in records.
4. Persistent toolkit + catalog; zip download; SVG/HTML→PNG engine.
5. Worker panel (Chat / Stats / Settings), then the 3D floor on real state.
