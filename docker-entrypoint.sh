#!/bin/sh
# docker-entrypoint.sh — decompress baked *.gz data files on start, then exec CMD.
#
# Hefty data files (data/jobs_seed.json, data/companies.json) are shipped
# compressed in the image (to stay under GitHub's 100 MB file limit + keep the
# image small) and decompressed into the volume on first start. The uncompressed
# form is only (re)created if it is missing — so an existing volume that already
# has the raw files is left untouched (idempotent, fast).
set -e

# Recursively decompress any *.gz under /app/data whose target is absent.
find /app/data -name '*.gz' -type f 2>/dev/null | while read -r gz; do
  out="${gz%.gz}"
  if [ ! -f "$out" ]; then
    echo "[entrypoint] decompressing ${gz#/app/data/} -> ${out#/app/data/}"
    zcat "$gz" > "$out"
  fi
done

exec "$@"