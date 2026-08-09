# ---- Stage 1: build the React frontend ----
FROM node:20-slim AS frontend
WORKDIR /build
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci
COPY app/frontend/ ./
# tsc -b && vite build -> /build/dist
RUN npm run build

# ---- Stage 2: Python backend + scheduler + dashboard ----
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# TeX Live for the in-dashboard resume builder (pdflatex → PDF, real time).
# The resume template (app/backend/src/resume_template.tex) needs base/recommended/
# extra + fonts (charter, paracol, titlesec, eso-pic, enumitem, lastpage, hyperref…).
# fontawesome was stripped from the template so we avoid the heavy texlive-fonts-extra.
# Compiled PDFs are written to /tmp and removed immediately — nothing hits the volume.
# pigz: parallel gzip — decompresses the baked data/*.gz (multi-hundred-MB seed)
# on start far faster than single-threaded zcat.
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base texlive-latex-recommended texlive-latex-extra \
        texlive-fonts-recommended \
        latexmk \
        pigz \
    && rm -rf /var/lib/apt/lists/*

# Backend + engine deps (all job boards enumerate via plain requests; no browser)
COPY app/backend/requirements.txt /tmp/requirements.backend.txt
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.backend.txt

# Application code + dataset
COPY engine/   ./engine/
COPY scripts/  ./scripts/
COPY app/backend/ ./app/backend/
# Copy the config template (always) + the user's personal config.yaml if present
# (it's gitignored per-user; a fresh clone has only config.example.yaml, and the
# entrypoint creates config.yaml from it on first start).
COPY config*.yaml ./
COPY data/     ./data/
COPY research/ ./research/

# Authoritative always-latest copy of the company dataset, kept OUTSIDE the
# /app/data volume mount. A stale volume (e.g. one created before the 50k bake)
# shadows the image's /app/data and can make the in-container consolidate shrink
# companies.json. docker-entrypoint.sh refreshes the volume from this copy on
# every start, so the app always boots from the latest committed dataset.
RUN mkdir -p /app/data.baked/raw
COPY data/companies.json.gz /app/data.baked/
COPY data/raw/ /app/data.baked/raw/

# Entrypoint: decompress baked *.gz data files (jobs_seed.json, companies.json)
# into the volume on start, then exec the app. Hefty files ship compressed to
# stay under GitHub's 100 MB limit and keep the image small.
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh

# Built frontend (served by FastAPI at /)
COPY --from=frontend /build/dist ./app/frontend/dist

EXPOSE 8000
# Persist the discovery DB + caches across container recreations via a volume on /app/data.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.backend.src.main:app", "--host", "0.0.0.0", "--port", "8000"]