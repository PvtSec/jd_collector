# job_auto

Discovers software/IT jobs at startups and mid-size tech companies, filters them to the
target roles in `config.yaml`, and shows them on a web dashboard. **Discovery only — it
never submits anything.** You open a job link and apply yourself.

## Run

```bash
docker compose up -d --build          # → http://localhost:8000
```

Or use the helper script (from this folder):

```
./run.sh up          build + start
./run.sh logs        follow logs
./run.sh stop        stop (data kept)
./run.sh status      container state
./run.sh export-seed snapshot live jobs into ./data/jobs_seed.json (commit + ./run.sh up to bake)
./run.sh clean       stop + delete the data volume (prompts)
```

The discovery DB and caches live in the `jobauto-data` Docker volume and persist across
restarts. The first discovery tick starts immediately; jobs appear within a minute.

## Adjust

Edit `config.yaml`:

- **`target.role_keywords` / `exclude_keywords`** — what roles to match / skip. Ships with a
  security + QA/SDET default.
- **`target.location_pref` / `work_types`** — accepted locations and work types
  (default: remote or India/EU/APAC/worldwide).
- **`skip_companies` / `allow_companies`** — exclude companies, or restrict to an allowlist.
- **`app:` block** — `tick_minutes` (discovery cadence), `rotate_size` (companies per tick),
  `stale_grace_misses` (absences before a job is marked closed), `port`.

Any `app:` value can also be set via a `JOBAUTO_*` env var (env wins). After editing, rebuild:
`./run.sh up`.