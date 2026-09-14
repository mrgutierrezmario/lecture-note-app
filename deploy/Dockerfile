# Production image: React UI built and served by the FastAPI backend on :8000.
# Build context is the repository root (see deploy/compose.yml).

# ── Stage 1: build the UI ─────────────────────────────────────────────────────
FROM node:24-alpine AS ui
WORKDIR /ui
COPY app/ui_frontend/package.json app/ui_frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/ui_frontend ./
RUN npm run build

# ── Stage 2: backend ──────────────────────────────────────────────────────────
FROM python:3.11-slim

# ffmpeg: audio chunk decoding + MP3 export. postgresql-client: pg_isready for the
# startup wait. curl: healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg postgresql-client curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/ui_backend
COPY app/ui_backend/requirements.txt ./
# anthropic is optional in dev (Claude vision tier) but always present here.
RUN pip install --no-cache-dir -r requirements.txt anthropic==0.96.0

COPY app/ui_backend ./
COPY --from=ui /ui/dist /app/ui_frontend/dist
COPY deploy/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Runtime-written state (saved API key, model overrides) — mounted as a volume.
ENV STATE_DIR=/app/state
RUN mkdir -p /app/state

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fs http://localhost:8000/health || exit 1
ENTRYPOINT ["/entrypoint.sh"]
