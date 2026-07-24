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

# Backend + engine deps (all job boards enumerate via plain requests; no browser)
COPY app/backend/requirements.txt /tmp/requirements.backend.txt
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.backend.txt

# Application code + dataset
COPY engine/   ./engine/
COPY scripts/  ./scripts/
COPY app/backend/ ./app/backend/
COPY config.yaml config.example.yaml ./
COPY data/     ./data/
COPY research/ ./research/

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