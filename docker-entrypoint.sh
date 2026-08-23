#!/bin/sh
# docker-entrypoint.sh — refresh the data volume from the baked dataset, then exec.
set -e

# pigz (parallel) decompresses the multi-hundred-MB seed far faster than zcat.
gz_cat() {
  if command -v pigz >/dev/null 2>&1; then
    pigz -dc -p8 "$1"
  else
    zcat "$1"
  fi
}

# Decompress any *.gz under /app/data whose target is absent.
find /app/data -name '*.gz' -type f 2>/dev/null | while read -r gz; do
  out="${gz%.gz}"
  if [ ! -f "$out" ]; then
    echo "[entrypoint] decompressing ${gz#/app/data/} -> ${out#/app/data/}"
    gz_cat "$gz" > "$out"
  fi
done

# Boot from the latest baked company dataset: merge baked raw files missing from
# the volume (-n, never clobbers runtime rewrites), and upgrade companies.json
# only if the volume copy is missing or smaller — adds/upgrades, never downgrades.
if [ -d /app/data.baked ] && [ -f /app/data.baked/companies.json.gz ]; then
  mkdir -p /app/data/raw
  cp -an /app/data.baked/raw/. /app/data/raw/ 2>/dev/null || true
  baked_n=$(gz_cat /app/data.baked/companies.json.gz | python -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)
  vol_n=$(python -c 'import json;print(len(json.load(open("/app/data/companies.json"))))' 2>/dev/null || echo 0)
  if [ "${vol_n:-0}" -lt "${baked_n:-0}" ]; then
    echo "[entrypoint] companies.json ${vol_n} < baked ${baked_n} -> refreshing from baked"
    gz_cat /app/data.baked/companies.json.gz > /app/data/companies.json
  fi
fi

# Per-user config: create config.yaml from the template on first start.
if [ ! -f /app/config.yaml ] && [ -f /app/config.example.yaml ]; then
  echo "[entrypoint] creating config.yaml from config.example.yaml (edit it to set your roles)"
  cp /app/config.example.yaml /app/config.yaml
fi

exec "$@"
