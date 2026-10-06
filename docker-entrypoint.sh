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
# the volume (-n, never clobbers runtime rewrites), and refresh companies.json when
# the baked snapshot's sha marker changes (a rebuild with a new/edited dataset) or the
# volume copy is missing. A sha marker is used instead of a row-count comparison so a
# DEDUPED snapshot (fewer rows than the stale volume copy) still propagates; the count
# rule would have skipped it. In-container rescan consolidate rewrites companies.json
# freely between restarts; the .gz/marker only changes on image rebuild.
if [ -d /app/data.baked ] && [ -f /app/data.baked/companies.json.gz ]; then
  mkdir -p /app/data/raw
  cp -an /app/data.baked/raw/. /app/data/raw/ 2>/dev/null || true
  bake_sha=$(cat /app/data.baked/dataset.sha 2>/dev/null || echo "")
  vol_sha=$(cat /app/data/dataset.sha 2>/dev/null || echo "")
  if [ ! -f /app/data/companies.json ] || { [ -n "$bake_sha" ] && [ "$vol_sha" != "$bake_sha" ]; }; then
    echo "[entrypoint] companies.json refreshing from baked (marker changed)"
    gz_cat /app/data.baked/companies.json.gz > /app/data/companies.json
    cp /app/data.baked/dataset.sha /app/data/dataset.sha 2>/dev/null || true
    cp /app/data.baked/companies.json.gz /app/data/companies.json.gz 2>/dev/null || true
  fi
fi

# Per-user config: create config.yaml from the template on first start.
if [ ! -f /app/config.yaml ] && [ -f /app/config.example.yaml ]; then
  echo "[entrypoint] creating config.yaml from config.example.yaml (edit it to set your roles)"
  cp /app/config.example.yaml /app/config.yaml
fi

exec "$@"
