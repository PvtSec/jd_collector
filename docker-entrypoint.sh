#!/bin/sh
# docker-entrypoint.sh — refresh the volume from the baked dataset, then exec CMD.
#
# Hefty data files (data/jobs_seed.json, data/companies.json) are shipped
# compressed in the image (to stay under GitHub's 100 MB file limit + keep the
# image small) and decompressed into the volume on first start.
#
# The /app/data volume persists across container recreations, so a stale volume
# (e.g. one created before the latest company bake) can shadow the image's newer
# data — and the scheduler's in-container consolidate.py would then rebuild
# companies.json from an incomplete raw/ set and shrink it. To prevent that, an
# authoritative copy of the company dataset lives at /app/data.baked (outside the
# volume). On every start we (1) merge any baked raw files missing from the
# volume and (2) upgrade companies.json if the volume copy is missing or smaller
# than the baked one. This only ever ADDS/UPGRADES — it never downgrades runtime
# growth the scheduler discovered.
set -e

# Decompress with pigz (parallel, 8 threads) — the seed is hundreds of MB and
# single-threaded zcat dominates startup. Falls back to zcat if pigz is absent.
gz_cat() {
  if command -v pigz >/dev/null 2>&1; then
    pigz -dc -p8 "$1"
  else
    zcat "$1"
  fi
}

# Recursively decompress any *.gz under /app/data whose target is absent.
find /app/data -name '*.gz' -type f 2>/dev/null | while read -r gz; do
  out="${gz%.gz}"
  if [ ! -f "$out" ]; then
    echo "[entrypoint] decompressing ${gz#/app/data/} -> ${out#/app/data/}"
    gz_cat "$gz" > "$out"
  fi
done

# --- Always boot from the latest baked company dataset (no stale revert) ---
if [ -d /app/data.baked ] && [ -f /app/data.baked/companies.json.gz ]; then
  mkdir -p /app/data/raw
  # Merge baked raw files into the volume: copy only those ABSENT on the volume
  # (-n = no-clobber), so runtime copies the scheduler's discover_* scripts
  # rewrote are preserved while any missing baked files (e.g. the 50k bulk
  # importers) are restored.
  cp -an /app/data.baked/raw/. /app/data/raw/ 2>/dev/null || true

  # Upgrade companies.json only if the volume copy is missing or smaller than
  # the baked one (never downgrade runtime growth).
  baked_n=$(gz_cat /app/data.baked/companies.json.gz | python -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)
  vol_n=$(python -c 'import json;print(len(json.load(open("/app/data/companies.json"))))' 2>/dev/null || echo 0)
  if [ "${vol_n:-0}" -lt "${baked_n:-0}" ]; then
    echo "[entrypoint] companies.json ${vol_n} < baked ${baked_n} -> refreshing from baked"
    gz_cat /app/data.baked/companies.json.gz > /app/data/companies.json
  fi
fi

# --- Per-user config: create config.yaml from the template on first start ---
# config.yaml is gitignored (each user customizes their own roles); a fresh
# clone has only config.example.yaml baked into the image.
if [ ! -f /app/config.yaml ] && [ -f /app/config.example.yaml ]; then
  echo "[entrypoint] creating config.yaml from config.example.yaml (edit it to set your roles)"
  cp /app/config.example.yaml /app/config.yaml
fi

exec "$@"