# Stage 1: build the React frontend
FROM node:20-slim AS frontend
WORKDIR /build
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci
COPY app/frontend/ ./
RUN npm run build

# Stage 2: Python backend + scheduler + dashboard
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# TeX Live: resume builder (pdflatex → PDF, written to /tmp, nothing hits the
# volume). pigz: fast decompression of the baked data/*.gz seed on start.
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base texlive-latex-recommended texlive-latex-extra \
        texlive-fonts-recommended \
        latexmk \
        pigz \
    && rm -rf /var/lib/apt/lists/*

COPY app/backend/requirements.txt /tmp/requirements.backend.txt
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.backend.txt

COPY engine/   ./engine/
COPY scripts/  ./scripts/
COPY app/backend/ ./app/backend/
# config.example.yaml always; the gitignored personal config.yaml if present
COPY config*.yaml ./
COPY data/     ./data/
COPY research/ ./research/

# Authoritative always-latest company dataset, kept OUTSIDE the /app/data volume
# mount (a stale volume would otherwise shadow it); the entrypoint refreshes the
# volume from this copy on every start — adds/upgrades only, never downgrades.
RUN mkdir -p /app/data.baked/raw
COPY data/companies.json.gz /app/data.baked/
COPY data/raw/ /app/data.baked/raw/

COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh

COPY --from=frontend /build/dist ./app/frontend/dist

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.backend.src.main:app", "--host", "0.0.0.0", "--port", "8000"]
