# job_auto dashboard

A single-page dashboard over the `job_auto` engine: a backend that discovers
jobs every 5 minutes via the engine's ATS enumerators, stores them in SQLite,
and streams live task status over SSE; a React frontend that lists jobs, lets
you jump to the JD, marks jobs as applied, and force-fires the discovery task.

```
app/
  Dockerfile              build from repo root: docker build -f app/Dockerfile -t job-auto-app .
  frontend/               React + Vite + TypeScript (built dist served by the backend)
  backend/                FastAPI + APScheduler
    src/
      settings.py          AppSettings (env JOBAUTO_* + config.yaml `app:` block)
      db.py               SQLite jobs/task_runs/daily_stats/discovery_cursor
      companies.py         automatable-company selection (re-implements cli._companies_filtered)
      discovery.py         the 5-min tick: rotate subset -> engine.boards.CLIENTS -> engine.match -> upsert
      tasks.py             TaskManager: single-flight gate + SSE pub/sub
      scheduler.py         APScheduler interval job + manual force/rescan
      repository.py        bridge to engine.ledger (mark-applied writes the ledger)
      app.py               FastAPI routes + SSE + static serving
      main.py              uvicorn entrypoint
```

## What the backend does
- Fires a discovery task every 5 minutes (configurable via `app.tick_minutes`).
- Each tick enumerates a rotating slice of ~60 automatable companies (all ~550
  covered ~hourly) via `engine.boards.CLIENTS[ats]`, filters with
  `engine.match.matches`, and upserts into `data/jobs.db`. `first_seen` is the
  "recently found by backend" signal.
- Records `task_runs` + `daily_stats` so the frontend status bar can show
  per-day rollups.
- Heavy company-discovery scripts (`discover_slugs` / `discover_topstartups` /
  `consolidate`) are NOT in the loop — they run only via the manual
  **Rescan companies** button.

## What the frontend shows
- A list of job listings with ATS badge, matched tag, "found X ago", and an
  **Apply now** link that opens the JD page.
- **Status bar (top-right)**: running/idle pill, current task progress, last
  run, per-day discovery chips, and two buttons:
  - **Force reload** — fires the discovery task if idle; disabled while a task
    is running.
  - **Rescan companies** — runs the heavy slug/topstartups/consolidate sweep.
- Filters: search, ATS, time-of-listing (recently found), sort, applied state,
  matched-only toggle.
- **Mark applied** writes through `engine.ledger.record` so the engine's
  `applied.sqlite` stays the source of truth even when you apply outside the bot.

## Run (dev)

Two terminals from the repo root:

```bash
# 1. backend (uses the project venv so engine.* imports cleanly)
.venv/bin/pip install -r app/backend/requirements.txt
.venv/bin/python -m uvicorn app.backend.src.main:app --host 127.0.0.1 --port 8000

# 2. frontend (Vite dev server proxies /api -> 127.0.0.1:8000)
cd app/frontend && npm install && npm run dev
# open http://127.0.0.1:5173
```

On first boot the dashboard DB is seeded from `data/topstartups_jobs_flat.json`
if present (override with `SEED_JSON=…`); otherwise the first tick populates it.

## Run (production / single container)

```bash
# build from the REPO ROOT (engine/ and scripts/ are outside app/)
docker build -f app/Dockerfile -t job-auto-app .

# config.yaml / profile.yaml / resumes / data are PII — mount them, don't bake them
docker run -p 8000:8000 \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/profile.yaml:/app/profile.yaml:ro" \
  -v "$PWD/resumes:/app/resumes:ro" \
  -v "$PWD/data:/data" \
  job-auto-app
# open http://localhost:8000  (FastAPI serves the built SPA + /api)
```

## Configuration

Backend settings read from (env wins) `JOBAUTO_*` env vars and the optional
`app:` block in `config.yaml`:

```yaml
app:
  tick_minutes: 5     # discovery cadence
  rotate_size: 60     # companies per tick
  port: 8000
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness + job count |
| GET | `/api/jobs?q=&ats=&matched=&applied=&recent=&sort=&limit=&offset=` | filtered job list |
| GET | `/api/jobs/{id}` | single job (JD link = `url`) |
| GET | `/api/stats` | count tiles + by-ats + last_run + applied ledger |
| GET | `/api/daily?days=14` | per-day rollup (status bar) |
| GET | `/api/ats` | distinct ATS values (filter dropdown) |
| GET | `/api/tasks/current` | current-run snapshot (`running`, progress…) |
| GET | `/api/tasks/history` | recent task_runs |
| POST | `/api/tasks/force-reload` | kick discovery now → 409 if one is running |
| POST | `/api/tasks/rescan-companies` | kick the heavy rescan → 409 if running |
| POST | `/api/jobs/{id}/mark-applied` | write to engine ledger + flip `applied` flag |
| GET | `/api/applied` | recent engine-ledger rows |
| GET | `/api/events` | SSE stream: `task_started` / `task_progress` / `task_completed` / `task_failed` |

## Notes
- **No live apply from the dashboard** — "Apply now" opens the JD page (per
  spec). The bot's `engine apply --manual` flow remains CLI-only.
- The engine `applied.sqlite` schema is unchanged; the dashboard only reads it
  (plus `mark-applied` writes through `ledger.record`, idempotent on the
  UNIQUE key).
- The Docker image installs Chromium for the `breezyhr`/`onlyfy` enumerators;
  if you exclude those ATS from the rotation you can drop that layer.
- `config.yaml` / `profile.yaml` / `resumes/` are **PII** — never bake them
  into the image; mount them as volumes.