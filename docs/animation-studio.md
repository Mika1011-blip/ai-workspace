# Animation studio — contract

Workers produce short animated videos as **projects**, through a staged
pipeline where every stage is checked by a reviewer before the next one
starts. This doc is the frozen interface the PRs below are built against.
It builds on `docs/comms-protocol.md` (the wall), `docs/run-record.md`
(records, tags) and `docs/app-comms-plan.md` (spawning).

## 1. A project

Unit of work. One folder, bind-mounted into Docker like `workers/`:

```
projects/<slug>/                     # slug matches ^[a-z0-9-]{1,40}$
  project.json                       # manifest (below) -- the state machine lives here
  preview.jpg                        # thumbnail for the gallery, written by the publish step
  final.mp4                          # the deliverable, browser-safe (see §6)
  artifacts/
    01-script.md                     # one file (or folder) per artifact …
    01-script.md.json                # … plus a sidecar: what it is, who made it, from which run
    02-script-review.md  (+ .json)   # a review is an artifact too
    03-storyboard/       (+ .json)
    04-voice.mp3         (+ .json)
    05-render/           (+ .json)   # renderer input written by the renderer worker
    05-render.log        (+ .json)   # what the container printed
  decisions.jsonl                    # every approve / revise / skip: who, when, notes, run it triggered
```

Delete the folder and the project is gone everywhere: host, Docker (it's a
bind mount), gallery. Nothing about a project is stored anywhere else
except a row in the `projects` SQLite index, rebuilt from the folders.

### project.json

```json
{
  "slug": "first-reel",
  "title": "First reel",
  "format": "social-short",
  "renderer": "remotion",
  "mode": "guided",
  "status": "awaiting_approval",
  "stage": "script-review",
  "stages": [
    {"name": "script", "run_id": "scriptwriter-…", "status": "success", "artifacts": ["01-script.md"]},
    {"name": "script-review", "run_id": "script-reviewer-…", "status": "needs_input",
     "artifacts": ["02-script-review.md"]}
  ],
  "created_at": "…Z", "updated_at": "…Z"
}
```

- `format` picks the skills the stages use (§3); `renderer` picks the
  Docker image (§6); `mode` is `auto` or `guided` (§4).
- `status`: `created · running · awaiting_approval · needs_input · failed · published`.
- `stage` is the current stage name, `null` once published; `stages` is
  the history, one entry per stage run.

### Artifact sidecar `<file>.json`

```json
{ "kind": "script | review | storyboard | audio | image | render-input | log | video",
  "stage": "script", "run_id": "scriptwriter-…", "worker": "scriptwriter",
  "description": "Three-beat script, 38 s, question hook in the first 2 s.",
  "created_at": "…Z" }
```
`description` is mandatory and is what the gallery shows next to the file.
A stage worker writes the artifact and its sidecar; the API refuses to
advance a stage whose declared artifacts lack a sidecar.

## 2. Stages and gates

```
script ─► script-review ─► storyboard ─► storyboard-review ─► assets ─► asset-review
       ─► render ─► render-review ─► publish
```

| stage | worker | reads | writes |
|---|---|---|---|
| script | `scriptwriter` | brief (`project.json.title`, format skill) | `01-script.md` |
| script-review | `script-reviewer` | script, the same format skill | `02-script-review.md` |
| storyboard | `storyboarder` | approved script | `03-storyboard/` (shots as md + images) |
| storyboard-review | `storyboard-reviewer` | storyboard, script | review |
| assets | `asset-maker` | storyboard | `04-*.mp3/.png` (voice, music, images) |
| asset-review | `asset-reviewer` | assets, storyboard | review |
| render | `renderer` | everything above | `05-render/` (renderer input: code or spec) |
| *(API)* render step | — | `05-render/` | `final-candidate.mp4`, `05-render.log` |
| render-review | `render-reviewer` | frames the API extracts from the candidate, storyboard | review |
| publish | *(API)* | candidate | `final.mp4` (format-checked), `preview.jpg`, status `published` |

**Gate rule:** a reviewer reports `success` → next stage; `needs_input` →
the maker runs **once more** with the reviewer's notes (and yours, in
guided mode), then the reviewer runs again; a second `needs_input` stops
the project at `needs_input` for you. `failed` anywhere stops at `failed`.
Both the maker and its reviewer are briefed with the **same format skill**
(§3), so they judge by one rubric.

Each stage is one `POST /sessions` with the project folder granted
(`--add-dir projects/<slug>`); the worker may write only under
`artifacts/` (deny rules on `project.json`, `final.mp4`, `preview.jpg`,
`decisions.jsonl` — those are the API's). Stage runs carry tags
`scope:docs|research|ops`, `topic:<slug>`, plus `project:<slug>` (new tag
key, value = slug).

## 3. Formats are skills

A format is a skill written with `write_skill` onto every stage worker:
`social-short` (hook in ≤ 2 s and which kind — question, contrast,
result-first; 3-beat structure; caption rules; 9:16, ≤ 60 s), `explainer`
(16:9, 2–4 min, chapter beats), `trailer`, … Adding a format is adding a
skill file, not code. `project.json.format` names it; the API passes
"use skill `<format>`" in every stage task.

## 4. Modes, checkpoints, decisions

One state machine, two ways to drive it.

- **`auto`** — the API advances through every gate by itself.
- **`guided`** — after every review stage the project stops at
  `awaiting_approval` with the maker's artifact and the reviewer's notes
  side by side, and waits for a decision.

`POST /projects/{slug}/decision` with
`{"decision": "approve" | "revise" | "skip", "notes": "…", "by": "mika" | "producer"}`:
`approve` → next stage; `revise` → the maker runs again with the
reviewer's notes **and** `notes`; `skip` → next stage regardless. Every
decision is appended to `decisions.jsonl`. `mode` can be changed any time
with `PATCH /projects/{slug}` (`auto` just means the API answers `approve`
at each checkpoint itself).

Two things make decisions: **you**, from the gallery (Approve / Revise
with a text box / Skip on the checkpoint view), and the **`producer`**
worker — an app-master-style worker you talk to, which turns "the hook is
too slow, make it a question" into `revise(notes)`, can show you two
options and ask which, or propose a renderer switch. It holds only the
project MCP tools (§7); it never touches files.

## 5. API

```
POST   /projects                      { slug, title, format, renderer, mode }   -> 201 manifest
GET    /projects                      -> [ { slug, title, format, status, stage, has_preview } ]
GET    /projects/{slug}               -> manifest + artifacts (each with its sidecar) + decisions
PATCH  /projects/{slug}               { mode?, title? }
DELETE /projects/{slug}               -> 204; removes the folder (host = Docker) and the index row
POST   /projects/{slug}/start         -> runs the pipeline from the first stage (409 if running)
POST   /projects/{slug}/decision      -> see §4; 409 unless status is awaiting_approval
POST   /projects/{slug}/export        { dest_dir }  -> copies the whole folder to dest_dir/<slug>/ on the host
GET    /projects/{slug}/artifacts/{path}  -> the file (video/audio/image/text); path validated inside the project
GET    /gallery                       -> the static gallery page
```

Internal transitions (`report_result` from a stage worker → advance;
render step; publish) are not endpoints — they're the state machine
reacting to events. All slugs go through `validate_name`; artifact paths
are resolved and must stay under `projects/<slug>/artifacts/`.

## 6. Rendering

**No Claude inside Docker.** The `renderer` worker writes the renderer's
input into `05-render/` (a Remotion composition, a Manim scene, or an
ffmpeg plan); the API runs the container:

```
docker run --rm -v <abs>/projects/<slug>:/project ai-workspace/renderer-<name> render
```

One image per renderer under `docker/renderers/<name>/` (`remotion`,
`manim`, `ffmpeg` to start; add a folder to add one), all honouring one
contract: read `/project/artifacts/05-render/`, write
`/project/artifacts/final-candidate.mp4` and `/project/artifacts/05-render.log`,
exit 0 or 1. No network needed at render time; no credentials in the image.

**Publish** (API): `ffprobe` must show H.264 video + AAC audio in MP4,
`yuv420p`, `+faststart` — if not, the API re-muxes with the `ffmpeg`
image; still wrong → `failed`. Then `final.mp4` is moved into place,
`preview.jpg` extracted at 1 s, status `published`. Browser-safe is a
hard requirement, not a wish: the gallery plays `final.mp4` as-is.

## 7. MCP tools (added to `ai-workspace`)

```
create_project(slug, title, format, renderer, mode)   -> POST /projects
list_projects()                                       -> GET /projects
get_project(slug)                                     -> GET /projects/{slug}
start_pipeline(slug)                                  -> POST /projects/{slug}/start
decide(slug, decision, notes)                         -> POST /projects/{slug}/decision  (by = calling session)
export_project(slug, dest_dir)                        -> POST /projects/{slug}/export
delete_project(slug, confirm)                         -> DELETE /projects/{slug}; refuses unless confirm is true
```
Same thin-wrapper style; token required for `decide` (it records who).
The `producer` worker is granted exactly these.

## 8. Gallery

Static page at `/gallery` (vanilla HTML/CSS/JS, per `.claude/rules/ui.md`):

- **Grid**: every project — `preview.jpg` (or a placeholder with the
  status as text, never colour alone), title, format, status, stage.
- **Project page**: `final.mp4` in a `<video>` if published; then every
  artifact grouped by stage, each with its sidecar description, rendered
  by kind — `<video>`/`<audio>`, `<img>`, markdown as text, logs
  collapsed; the decision trail; and, when `awaiting_approval`, the
  checkpoint: maker artifact + reviewer notes + Approve / Revise / Skip.

## 9. Order of work (one PR each, merged as they go)

1. App workers may write inside their own folder (deny writes to `_shared/`).
2. Per-worker grants on spawn: `tools` (→ `--tools`) and `read_from`/`write_to` dirs (→ `--add-dir`).
3. Projects: folder, manifest, sidecars, index, `POST/GET/PATCH/DELETE /projects`, artifact serving.
4. State machine: stages, gates, one-revision rule, `report_result` → advance; `auto` mode end to end with fake workers.
5. Guided mode: checkpoints, decisions, `decisions.jsonl`.
6. Renderer images (`ffmpeg` first, then `remotion`, `manim`) + the render step + publish (ffprobe check, preview).
7. Gallery page.
8. MCP tools + the `producer` worker + `export`/`delete`.
9. Role briefs for the eight stage workers and the first format skill (`social-short`).

Open questions, not blocking 1–5: voice (TTS provider and its key, a
per-worker grant), generated images for storyboards/assets (same), and
whether `assets` should be split into voice / music / images stages.
