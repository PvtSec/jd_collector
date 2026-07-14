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
    [ "${yn:-N}" =~ ^[Yy]$ ] || { echo "aborted"; exit 0; }
    docker compose down -v ;;
  shell)
    docker compose exec job-auto bash ;;
  *)
    echo "unknown command: $cmd" >&2
    sed -n '2,12p' "$0"
    exit 1 ;;
esac