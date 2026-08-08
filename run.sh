#!/usr/bin/env bash
# job_auto stack control — thin wrapper over docker compose.
# Usage:  ./run.sh <command>
#   build      build the image (no start)
#  up|start    build + start in background
# down|stop    stop + remove containers (data volume preserved)
#   restart    stop + start
#   logs       follow container logs (Ctrl-C to detach)
#   status     show container state
#   ps         alias for status
#   clean      stop + DELETE the jobauto-data volume (loses the discovery DB) — prompts
#   shell      open a shell inside the running container
#   export-seed  dump the live jobs DB to ./data/jobs_seed.json (commit it + ./run.sh up
#                to bake the snapshot into the image, so a fresh volume/machine pre-seeds)
set -euo pipefail

cd "$(dirname "$0")"   # run from repo/ so compose finds docker-compose.yml

cmd="${1:-}"
[ -z "$cmd" ] && { sed -n '2,12p' "$0"; exit 1; }

case "$cmd" in
  build)
    docker compose build ;;
  up|start)
    docker compose up -d --build
    echo "→ http://localhost:8000  (first discovery tick starts immediately)" ;;
  down|stop)
    docker compose down ;;
  restart)
    docker compose down
    docker compose up -d --build
    echo "→ http://localhost:8000" ;;
  logs)
    docker compose logs -f ;;
  status|ps)
    docker compose ps ;;
  clean)
    read -rp "This deletes the jobauto-data volume (all discovered jobs). Continue? [y/N] " yn
    [[ "${yn:-N}" =~ ^[Yy]$ ]] || { echo "aborted"; exit 0; }
    docker compose down -v ;;
  shell)
    docker compose exec job-auto bash ;;
  export-seed)
    docker compose ps --services --filter status=running | grep -q '^job-auto$' \
      || { echo "container not running — start it first: ./run.sh up"; exit 1; }
    # 1. generate the seed on the volume from the live jobs DB.
    #    Exporting is a pure SELECT, so it opens the DB READ-ONLY. Constructing a real DB()
    #    here would run its schema DDL (executescript + ALTER TABLE migrations), which needs
    #    sqlite's single write lock -- and upsert_job commits once per job, so a running tick
    #    issues thousands of rapid write txns and starves the exporter into
    #    "database is locked". Readers never block writers under WAL, so ro sidesteps it.
    docker compose exec -T job-auto python - <<'PY'
import sqlite3, threading
from app.backend.src.settings import settings
from app.backend.src.seed import export_seed


class ReadOnlyDB:
    """Minimal stand-in for DB: export_seed only touches ._lock and ._conn."""

    def __init__(self, path):
        self._lock = threading.Lock()
        try:
            self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)
        except sqlite3.OperationalError:
            # a WAL needing recovery can't be opened read-only (it must write -shm/-wal);
            # fall back to a normal connection, which is safe when nothing else is running
            self._conn = sqlite3.connect(path, timeout=60)
        self._conn.row_factory = sqlite3.Row


db = ReadOnlyDB(settings.abs_jobs_db())
r = export_seed(db, settings.abs_seed_file(), settings.seed_max_rows)
print(f"exported {r['exported']} jobs -> {r['path']}")
PY
    # 2. copy the volume seed out to the host repo so it can be committed + baked
    docker compose cp job-auto:/app/data/jobs_seed.json ./data/jobs_seed.json
    # 3. STRIP user/role state so the committed seed carries only job listings.
    #    applied is restored per-machine from the (gitignored) ledger on startup;
    #    hidden is a personal action; matched is role-specific (re-derived by each
    #    user's config + matcher on enumeration). Zeroing them keeps a fresh clone
    #    state-free. closed (job liveness) is kept.
    sed -i 's/"applied": 1/"applied": 0/g; s/"hidden": 1/"hidden": 0/g; s/"matched": 1/"matched": 0/g' ./data/jobs_seed.json
    # 4. compress it (the raw file is gitignored + dockerignored; only the .gz
    #    is committed + baked — keeps the repo under GitHub's 100 MB file limit;
    #    docker-entrypoint.sh decompresses it into the volume on start)
    gzip -kf ./data/jobs_seed.json
    echo "→ wrote ./data/jobs_seed.json + .gz (raw is gitignored; commit data/jobs_seed.json.gz)"
    echo "  also compress the curated dataset if regenerated: gzip -kf data/companies.json"
    echo "  then: git add data/jobs_seed.json.gz data/companies.json.gz && ./run.sh up"
    echo "  (a fresh volume / new machine pre-seeds from this snapshot)" ;;
  *)
    echo "unknown command: $cmd" >&2
    sed -n '2,12p' "$0"
    exit 1 ;;
esac