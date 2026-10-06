#!/usr/bin/env bash
# job_auto stack control — thin wrapper over docker compose. Usage: ./run.sh <cmd>
#   build        build the image (no start)
#  up|start      build + start in background → http://localhost:8000
# down|stop      stop + remove containers (data volume preserved)
#   restart      stop + build + start
#   logs         follow container logs (Ctrl-C to detach)
#   status|ps    container state
#   clean        stop + DELETE the jobauto-data volume (discovered jobs die; the
#                host-mounted applied ledger + ./state survive) — prompts
#   shell        open a shell inside the running container
#   smoke        run scripts/smoke_test.py inside the container
#   export-seed  dump the live jobs DB to ./data/jobs_seed.json + .gz — commit the
#                .gz so a fresh volume/machine pre-seeds from it (see below)
set -euo pipefail

cd "$(dirname "$0")"   # run from repo/ so compose finds docker-compose.yml

cmd="${1:-}"
[ -z "$cmd" ] && { sed -n '2,12p' "$0"; exit 1; }

# Bind-mounted state must exist before compose up: Docker creates a DIRECTORY
# for a missing single-file bind source, which SQLite can't open.
ensure_state_files() {
  if [ -d ./data/applied.sqlite ]; then
    echo "ERROR: ./data/applied.sqlite is a directory (stale Docker artifact)." >&2
    echo "  Remove it (rmdir if empty) and re-run — it should be a file." >&2
    exit 1
  fi
  mkdir -p ./data ./state
  touch ./data/applied.sqlite
}

case "$cmd" in
  build)
    docker compose build ;;
  up|start)
    ensure_state_files
    docker compose up -d --build
    echo "→ http://localhost:8000  (first discovery tick starts immediately)" ;;
  down|stop)
    docker compose down ;;
  restart)
    docker compose down
    ensure_state_files
    docker compose up -d --build
    echo "→ http://localhost:8000" ;;
  logs)
    docker compose logs -f ;;
  status|ps)
    docker compose ps ;;
  clean)
    read -rp "This deletes the jobauto-data volume (all discovered jobs — the applied ledger survives). Continue? [y/N] " yn
    [[ "${yn:-N}" =~ ^[Yy]$ ]] || { echo "aborted"; exit 0; }
    docker compose down -v
    echo "→ volume deleted; applied history kept in ./data/applied.sqlite" ;;
  shell)
    docker compose exec job-auto bash ;;
  smoke)
    docker compose exec job-auto python scripts/smoke_test.py ;;
  export-seed)
    docker compose ps --services --filter status=running | grep -q '^job-auto$' \
      || { echo "container not running — start it first: ./run.sh up"; exit 1; }
    # Export via a READ-ONLY sqlite connection: a real DB() would run schema DDL,
    # which fights the tick's write txns for sqlite's single write lock; readers
    # never block writers under WAL.
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
            # a WAL needing recovery can't be opened read-only; a normal
            # connection is safe when nothing else is running
            self._conn = sqlite3.connect(path, timeout=60)
        self._conn.row_factory = sqlite3.Row


db = ReadOnlyDB(settings.abs_jobs_db())
r = export_seed(db, settings.abs_seed_file(), settings.seed_max_rows)
print(f"exported {r['exported']} jobs -> {r['path']}")
PY
    docker compose cp job-auto:/app/data/jobs_seed.json ./data/jobs_seed.json
    # Strip user/role state (applied restored per-machine from the ledger,
    # hidden/matched are personal) so a fresh clone boots state-free; the
    # optional space keeps this working on pre-minification seeds.
    sed -Ei 's/"(applied|hidden|matched)": ?1/"\1":0/g' ./data/jobs_seed.json
    # pigz -11 (zopfli) gives the smallest gzip output; raw + non-.gz forms are
    # gitignored/dockerignored — only the .gz is committed and baked.
    if command -v pigz >/dev/null 2>&1; then
      pigz -11 -p8 -kf ./data/jobs_seed.json
    else
      echo "! pigz not found — falling back to gzip -9 (install pigz for a smaller seed)" >&2
      gzip -9 -kf ./data/jobs_seed.json
    fi
    echo "→ wrote ./data/jobs_seed.json + .gz (raw is gitignored; commit data/jobs_seed.json.gz)" ;;
  *)
    echo "unknown command: $cmd" >&2
    sed -n '2,12p' "$0"
    exit 1 ;;
esac
