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
    # 1. generate the seed on the volume from the live jobs DB
    docker compose exec -T job-auto python - <<'PY'
from app.backend.src.settings import settings
from app.backend.src.db import DB
from app.backend.src.seed import export_seed
db = DB(settings.abs_jobs_db())
r = export_seed(db, settings.abs_seed_file(), settings.seed_max_rows)
print(f"exported {r['exported']} jobs -> {r['path']}")
PY
    # 2. copy the volume seed out to the host repo so it can be committed + baked
    docker compose cp job-auto:/app/data/jobs_seed.json ./data/jobs_seed.json
    echo "→ wrote ./data/jobs_seed.json"
    echo "  commit it (git add data/jobs_seed.json) then ./run.sh up to bake into the image"
    echo "  (a fresh volume / new machine will then pre-seed from this snapshot)" ;;
  *)
    echo "unknown command: $cmd" >&2
    sed -n '2,12p' "$0"
    exit 1 ;;
esac