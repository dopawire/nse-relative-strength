# syntax=docker/dockerfile:1
# NSE Relative Strength — one image, two targets:
#   web     FastAPI + the React app (small: no browser)
#   worker  the daily data pipeline + scheduler (adds Chromium for NSE's listing page)
# Build:  docker compose build      (see docker-compose.yml, DEPLOY.md)

# ---------------------------------------------------------------- React app
FROM node:22.11.0-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- shared base
FROM python:3.12.8-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata \
    NSE_RS_DATA_DIR=/data \
    NSE_RS_CACHE_DIR=/cache \
    NSE_RS_WATCHLIST=/data/watchlist.txt \
    NSE_RS_LOG=/data/run.log \
    PUBLISH_SITE=0
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app \
 && mkdir -p /data /cache && chown app:app /data /cache
WORKDIR /app
COPY requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt
COPY --chown=app:app . .
COPY --from=frontend --chown=app:app /src/dist /app/frontend/dist
ENTRYPOINT ["/bin/sh", "/app/deploy/entrypoint.sh"]

# ---------------------------------------------------------------- web
FROM base AS web
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]

# ---------------------------------------------------------------- worker
FROM base AS worker
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir playwright==1.64.1 \
 && python -m playwright install --with-deps chromium \
 && chmod -R a+rX /ms-playwright
USER app
CMD ["python", "deploy/scheduler.py"]
