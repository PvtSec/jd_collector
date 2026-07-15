# job_auto — centralized job-search centre

Discovers software/IT jobs at startups and mid-size tech companies (not traditional MNCs)
and filters them down to the **target roles in `config.yaml`**. Built around the **ATS form
types** that power each company's career page, since the ATS determines the public job-board
API used for enumeration.

**This project only discovers and filters jobs — it never submits anything.** There is no
apply/submit code path and no candidate profile or resumes live in this repo. The dashboard
lists matching jobs with links to the real job description; you open the JD and apply yourself.

## What's inside

- **`engine/`** — read-only discovery engine: 12 ATS job enumerators (greenhouse, lever,
  ashby, workable, smartrecruiters, personio, rippling, teamtailor, breezyhr, onlyfy, mailto,
  workday), a role/location/work-type matcher, an SQLite applied-jobs ledger, an ATS
  host-pattern registry, and a CLI (`list-companies`, `jobs`, `stats`).
- **`app/`** — dashboard: FastAPI+SSE backend (scheduled discovery ticks, dead-link prune,
  24h automatic new-company discovery) + React+Vite+TS frontend.
- **`scripts/`** — discovery sources (topstartups.io, Wikipedia unicorns, YC Directory,
  Himalayas, BuiltIn.com, `edoardottt/companies-hiring-security-remote`) + `consolidate.py`
  (the single writer of `companies.json`).
- **`data/`** — curated company dataset (~4k companies, ~1.9k automatable), ATS schemas in
  `research/ats_schemas/`.

## Quick start — engine (read-only)

```bash
python -m venv .venv && . .venv/bin/activate          # Python 3.10+
pip install -r requirements.txt                       # requests, PyYAML, rich
python -m engine.cli -c config.yaml list-companies --ats greenhouse
python -m engine.cli -c config.yaml jobs --company "GitLab"   # enumerate + filter
python -m engine.cli -c config.yaml stats
```

`config.yaml` ships with a security-focused default target (pentest / QA / SDET / appsec,
remote-or-India/EU/APAC, US-only rejected). Edit `target.role_keywords` /
`target.exclude_keywords` / `target.location_pref` to retarget.

## Quick start — dashboard (Docker, easiest)

```bash
docker compose up -d --build
# open http://localhost:8000  (first discovery tick starts immediately; jobs land within a minute)
```

Or, without compose:

```bash
docker build -t job-auto .
docker run -d --name job-auto -p 8000:8000 -v jobauto-data:/app/data job-auto
```

The image bundles the curated dataset; the live discovery DB (`data/jobs.db`) is persisted in
the `jobauto-data` volume. The scheduler enumerates 60 automatable companies every 5 min, prunes
dead links every 12h, and grows the company list every 24h.

**Discovered-jobs seed**: the dashboard dumps its discovered jobs to `data/jobs_seed.json`
(default hourly) and re-imports them on an empty jobs DB, so a fresh start isn't empty. On a
**fresh volume** Docker initializes the volume from the image's baked `data/` (so a new machine
pre-seeds from the last-built snapshot); on a DB wipe with the volume kept, it recovers from the
latest runtime seed. To refresh the baked snapshot: `./run.sh export-seed` (writes
`./data/jobs_seed.json`), commit it, then `./run.sh up`. By default the seed is uncapped
(every discovered job; `seed_max_rows=0`). Set `seed_max_rows` / `JOBAUTO_SEED_MAX_ROWS` to cap
it (most-recently-seen); cadence `JOBAUTO_SEED_EXPORT_MINUTES`.

**Closed-job detection**: when a company's board is re-enumerated, jobs that were previously seen
but are absent from the fresh list are tracked; after `stale_grace_misses` (default 2) consecutive
confirmed absences they're marked **closed** (auto-reopen if they reappear; applied jobs are
exempt). Closed jobs are excluded from the default list — use the Open/Closed/All filter to see
them. Only the fully-paginated ATS are reaped (greenhouse/lever/ashby/smartrecruiters/personio/
rippling/teamtailor); capped/scrape enumerators are skipped to avoid false closes. Override
the grace with `JOBAUTO_STALE_GRACE_MISSES` or the `app:` block in `config.yaml`.

## Quick start — dashboard (dev)

```bash
pip install -r app/backend/requirements.txt          # backend deps
python -m uvicorn app.backend.src.main:app --port 8000          # backend
cd app/frontend && npm install && npm run dev                  # frontend (Vite proxies /api→8000)
# production frontend build: npm run build  ->  app/frontend/dist (served by FastAPI)
```

## Refresh / grow the company list

```bash
python scripts/discover_chsr.py        # edoardottt/companies-hiring-security-remote
python scripts/discover_topstartups.py # topstartups.io
python scripts/discover_companies.py    # Wikipedia unicorns + curated seed
python scripts/discover_yc.py           # YC Startup Directory (public JSON API)
python scripts/discover_himalayas.py    # Himalayas API
python scripts/discover_builtin.py      # BuiltIn.com
python scripts/consolidate.py           # merge all data/raw/*.json -> companies.json
```

## Key insight

Greenhouse + Lever + Ashby cover the majority of companies and expose public, auth-free
job-board APIs (Greenhouse/Lever as JSON; Ashby via SSR `__appData`) — so job *enumeration* is
fully automatable. Submission is intentionally out of scope.

See `data/README.md` for the dataset schema and `research/ats_schemas/*.md` for per-ATS
form schemas + worked curl examples.

## License

MIT — see `LICENSE`. The `data/raw/agent6_topstartups.json` dataset was scraped from
topstartups.io and `scripts/discover_chsr.py` ingests the
`edoardottt/companies-hiring-security-remote` list (MIT); respect those upstream sources' terms.