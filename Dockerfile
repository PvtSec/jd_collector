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

# Backend + engine deps (incl. playwright for the breezyhr/onlyfy/yc scrapers)
COPY app/backend/requirements.txt /tmp/requirements.backend.txt
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.backend.txt \
    && python -m playwright install --with-deps chromium

# Application code + dataset
COPY engine/   ./engine/
COPY scripts/  ./scripts/
COPY app/backend/ ./app/backend/
COPY config.yaml config.example.yaml ./
COPY data/     ./data/
COPY research/ ./research/

# Built frontend (served by FastAPI at /)
COPY --from=frontend /build/dist ./app/frontend/dist

EXPOSE 8000
# Persist the discovery DB + caches across container recreations via a volume on /app/data.
CMD ["python", "-m", "uvicorn", "app.backend.src.main:app", "--host", "0.0.0.0", "--port", "8000"]