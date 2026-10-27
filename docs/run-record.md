# Run records

Every worker run leaves one JSON document behind, so nobody has to watch a
terminal to know what happened. Same schema for both sides; different
writer.

| | App workers | Crew workers |
|---|---|---|
| Where | `workers/<name>/runs/<run_id>.json` | `.claude/crew/runs/<role>/<run_id>.json` |
| Writer | the API (`POST /sessions` → `report_result` → end/reconcile) | the lead, via `/spawn-worker` and `/end-worker` |
| Index | `runs` table in `data/sessions.db`, queried with `GET /runs` | none (few files; `grep`/`jq`) |

Files are the truth; the SQLite table is an index built in the same code
path, so it can always be rebuilt from the files. Neither is committed.

## Record

```json
{
  "run_id": "news-digest-2026-10-28T08-00-03Z-8f3e1a2b",
  "worker": "news-digest",
  "trigger": "manual",
  "attempt": 1,
  "started_at": "2026-10-28T08:00:03Z",
  "ended_at": "2026-10-28T08:00:51Z",
  "status": "success",
  "tags": ["worker:news-digest", "trigger:manual", "env:local",
           "scope:research", "topic:ai-news"],
  "prompt_version": "a1b2c3d",
  "result": { "summary": "5 bullets ..." },
  "metrics": { "turns": 6, "duration_ms": 48210, "cost_usd": 0.07 },
  "error": null,
  "session_id": "8f3e1a2b"
}
```

- `run_id` is `<worker>-<started_at>-<session_id>` with `:` → `-`: a
  worker's runs sort by time, the session id keeps two runs started in
  the same second distinct, and it's a safe filename.
- `prompt_version` is the first 7 hex chars of the SHA-256 of the
  `CLAUDE.md` the run actually started with — it changes exactly when the
  instructions do.
- `metrics.duration_ms` is computed by the writer at end. `turns` and
  `cost_usd` are whatever the worker reports; Claude Code doesn't expose
  them to the API, so they stay `null` rather than be invented.
- `error` is a short string when `status` is `failed`/`timeout`, else
  `null`.

## Status

`queued · running · success · failed · timeout · skipped · missed · needs_input`

How a record moves (app side):

| Event | status |
|---|---|
| `POST /sessions` | `running` |
| worker calls `report_result(status=…)` | `success`, `failed`, `skipped` or `needs_input` — the worker's own verdict |
| `POST /sessions/{id}/end` before any report | `failed`, error `"ended before reporting a result"` |
| startup reconciliation finds the process gone before any report | `failed`, error `"process gone before reporting a result"` |
| `POST /sessions/{id}/end` after a report | unchanged; `ended_at` and `duration_ms` filled in |

`queued`, `timeout` and `missed` are reserved for a scheduler, which
doesn't exist yet.

## Tags

`key:value`, keys and most values from a fixed list — anything else is
refused with `400 bad_tag`, because free-form tags turn into noise within a
week.

| key | values | set by |
|---|---|---|
| `worker` | the worker's name | writer, always |
| `trigger` | `manual` · `schedule` · `event` · `loop` | writer, always |
| `env` | `local` · `cloud` · `ci` | writer, always (`local` today) |
| `scope` | `research` · `code` · `docs` · `ops` | spawner or worker |
| `topic` | free text, `[a-z0-9-]`, ≤ 40 chars | spawner or worker |
| `severity` | `info` · `warn` · `error` | worker |

Filter with `GET /runs?worker=…&status=…&tag=scope:research&since=<ISO>`.
Each query parameter narrows; `tag` may repeat.

## Activity log

Next to the records, each worker has a timeline: `workers/<name>/activity.jsonl`
(crew: `.claude/crew/runs/<role>/activity.jsonl`), one JSON object per line,
appended by the same writer as the records. Where a record says what a run
produced, the log says what happened, when, and with whom:

| event | fields |
|---|---|
| `spawned` | `session_id`, `run_id`, `trigger`, `spawned_by`, `task` |
| `result_reported` | `session_id`, `run_id`, `status` |
| `message_out` / `message_in` | `to` / `from`, `outcome` (`accepted`, `not_allowed`, `bad_token`, `session_ended`) — written on **both** workers' logs, refusals included |
| `ended` | `session_id`, `run_id`, `status` (the run's final status) |
| `reconciled` | `session_id`, `run_id`, `status`, `reason` |

Every line has `at` (UTC, `…Z`). Read the tail with
`GET /workers/{name}/activity?limit=100` (oldest first). The global
`runs/messages.jsonl` keeps the cross-worker message audit as before.
