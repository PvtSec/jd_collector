# job_auto

Discovers software/IT jobs across a large catalog of startups and mid-size tech
companies, filters them to **your target roles**, and shows the matches on a web
dashboard. **Discovery only — it never submits anything.** You open a job link
and apply yourself.

## Prerequisites

Docker (with Docker Compose / the `docker compose` plugin).

## Quick start

```bash
./run.sh up          # build + start  →  http://localhost:8000
```

The first discovery tick runs immediately; matching jobs appear within a minute.
The discovery DB and caches live in the `jobauto-data` Docker volume and persist
across restarts. Two pieces of user state live **outside** the volume as host
bind mounts (both gitignored), so they survive even `./run.sh clean`,
`docker system prune`, and no-cache rebuilds: the **applied-history ledger**
(`data/applied.sqlite`) and the **dashboard state dir** (`state/` — applied/hidden
restore records). Fresh clones start with neither — your marks stay on your machine.

It boots with a **generic software-engineering** role set (auto-created from
`config.example.yaml`). **Set your own roles (below) to get relevant matches.**

## Set your target roles

`config.yaml` is **per-user and gitignored** — your role preferences stay local
and are never committed. To customize:

```bash
cp config.example.yaml config.yaml     # create your config (skip if it already exists)
$EDITOR config.yaml                    # set your roles
./run.sh up                            # rebuild to apply (config is baked at build time)
```

Edit the `target:` block:

- **`role_keywords`** — a job matches only if its **title** contains one of these
  (case-insensitive substring). This is the main knob — replace the examples with
  the roles you want.
- **`exclude_keywords`** — reject titles containing these (e.g. `manager`,
  `director`, `intern`).
- **`location_pref`** — keep jobs whose location contains one of these (`remote`
  always qualifies; US-only roles are auto-rejected). Add your country/city tokens.
- **`work_types`** — `remote` / `hybrid` / `onsite`.
- **`skip_companies`** / **`allow_companies`** — exclude specific companies, or
  restrict to an allowlist.

> The matcher matches **title keywords only** — it does not parse years-of-
> experience from descriptions. The shipped `exclude_keywords` blocks
> manager/director/lead/principal/staff/architect/intern titles; `engine/match.py`
> additionally keeps **Senior/Sr** titles even if `senior` is listed as an exclude.
> Tune seniority via `exclude_keywords` (and `engine/match.py`'s `SENIORITY_PREFIXES`).

Any value under `app:` can also be set via a `JOBAUTO_*` environment variable
(env wins over the file). After editing `config.yaml`, rebuild: `./run.sh up`.

## Commands

```
./run.sh up            build + start
./run.sh logs          follow logs
./run.sh stop          stop (data kept)
./run.sh status        container state
./run.sh clean         stop + delete the data volume (prompts)
./run.sh smoke         end-to-end suite inside the container (run after changes)
./run.sh export-seed   snapshot live jobs (commit + ./run.sh up to bake for others)
```

## How it works

The scheduler enumerates companies' public job boards (Greenhouse, Lever, Ashby,
Workable, SmartRecruiters, Personio, Teamtailor, Workday, …) on a rotation,
matches new postings against your `target:`, and marks jobs closed when they
disappear. Your **applied** and **hidden** actions are stored locally (ledger +
state dir on the host; see Quick start) — a fresh clone starts with none. See
`data/README.md` for internals.
