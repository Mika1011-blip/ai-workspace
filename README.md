# ai-workspace

A web app to create and manage Claude workers. Each worker is a folder
`workers/<name>/` with a `CLAUDE.md`. A FastAPI backend owns that folder, a
small MCP server (`ai-workspace`) exposes the same API to Claude Code
sessions, and `docs/comms-protocol.md` defines how sessions talk to each
other — crew sessions on your laptop, app sessions started by the API.

```
browser ──► app/main.py (FastAPI) ──► workers/<name>/CLAUDE.md
                  ▲                    data/sessions.db · runs/messages.jsonl
   mcp_server/workspace_server.py      (session registry · message log)
   = the "ai-workspace" MCP server, used by Claude Code sessions
```

## Run it

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload        # http://localhost:8000
pytest                               # run before saying a task is done

docker compose up                    # same app in a container; see note below
```

App workers run on the Claude Agent SDK (`app/sdk_runner.py`): the API
starts each session in-process, sees its status, tool and cost live
(`GET /workers/state`), and ends it once it has reported. Sessions use the
login this machine already has (`claude login`); any `ANTHROPIC_API_KEY`
in the environment is deliberately kept away from them. `RUNNER=cli` falls
back to the old `claude --bg` processes.

Inside Docker, `POST /sessions` answers `503 spawning_disabled`: spawning a
session needs the SDK's bundled CLI and your login, and the image has
neither. Everything else works there; `workers/`, `worker_templates/`,
`data/` and `runs/` are mounted from your disk.

## First run on a new machine

Things that live outside git and bit us once each:

1. **Approve the project's MCP servers once.** A fresh Claude Code session in
   this repo asks whether to use the servers in `.mcp.json`
   (`ai-workspace`, `context7`, `playwright`). A *background* session
   can't answer that prompt and just hangs on it. Say yes once in an
   interactive session, or pre-approve them in the gitignored
   `.claude/settings.local.json`:
   ```json
   { "enabledMcpjsonServers": ["ai-workspace", "context7", "playwright"] }
   ```
2. **The crew registry is per machine.** `.claude/crew/registry.json` is
   gitignored because session ids don't travel. On a new machine start
   with `/rebuild-registry`, then spawn what you need with `/spawn-worker`.
   Both skills (and `/end-worker`) just run `scripts/crew.py`, which is the
   one place the crew lifecycle is implemented: each worker gets its own
   worktree `.claude/worktrees/<role>-<id>` on branch `work/<role>-<id>`,
   and `end` removes it only once that branch is merged.
3. **Crew workers must run in the lead's permission mode.** Claude Code
   holds cross-session messages between sessions in different modes, and a
   background worker can never approve the hold. `/spawn-worker` passes
   `--permission-mode bypassPermissions`; if you run the lead in another
   mode, change both together.
4. **`workers/app-master` is its own Claude Code project.** Run `claude`
   *inside* that folder. Claude Code's project root is the git root, so the
   root `.mcp.json` servers show up there too; app-master's gitignored
   `.claude/settings.local.json` disables them so only its own
   `ai-workspace` entry is active:
   ```json
   { "disabledMcpjsonServers": ["context7", "playwright"],
     "enabledMcpjsonServers": ["ai-workspace"] }
   ```
   (Sessions the API spawns don't need any of this — they're started with
   `--strict-mcp-config` and get exactly one server.)
5. **Naming.** The MCP server is `ai-workspace` everywhere: root
   `.mcp.json`, app-master's `.mcp.json`, `FastMCP("ai-workspace")`, and
   the tool prefix `mcp__ai-workspace__*` in every allow list. The name
   is load-bearing — permission rules match on it — so don't rename it in
   one place only. (`workspace` on its own is a reserved name and silently
   never loads.)
6. **Build the renderer images** the studio renders with (one per
   renderer, `docker/renderers/<name>/`; the `ffmpeg` one is also the
   media utility every project needs for frames and publishing):
   ```bash
   docker build -t ai-workspace/renderer-ffmpeg docker/renderers/ffmpeg
   ```
   Without it, a project fails at its render step with the docker error in
   `artifacts/07-render.log`.
7. **The studio has two front doors.** The gallery at `/gallery` (grid of
   projects, every artifact with its description, the checkpoint buttons)
   and the `producer` worker: run `claude` inside `workers/producer` and
   talk to it — it creates and starts projects and turns what you say at a
   checkpoint into a decision. Like app-master, it is its own Claude Code
   project with only the project tools granted; its gitignored
   `.claude/settings.local.json` needs the same two lines as app-master's
   (item 4).

## Where things are

| Path | What |
|---|---|
| `app/main.py` | every endpoint; `create_app()` is a factory, tests pass temp paths |
| `app/sessions_store.py` | SQLite session registry |
| `mcp_server/workspace_server.py` | the `ai-workspace` MCP server: thin HTTP wrappers, never touches disk |
| `workers/` | one folder per worker; `workers/_shared/` is the only folder every app worker may also read |
| `worker_templates/` | starter `CLAUDE.md`s served by `GET /templates` |
| `.claude/crew/` | crew protocol (`COMMS.md`), role briefs, the per-machine registry |
| `.claude/rules/` | conventions per area, loaded by `CLAUDE.md` |
| `docs/` | contracts: `master-worker.md`, `comms-protocol.md`, `app-comms-plan.md` |

`BUILD_LOG.md` is written by hooks — don't edit it by hand.
