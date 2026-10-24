# SatQuery AI in one container: the workspace and the analysis service, served
# by uvicorn on one port. This is the image a Hugging Face Space (or Render,
# Railway, a plain VM) runs; docker-compose.yml is the two-container version
# with nginx in front.
#
#   docker build -t satquery .
#   docker run -p 7860:7860 satquery          then open http://localhost:7860
#
# With no configuration it runs open (no sign-in), reads questions with the
# offline rules, and fetches imagery from Planetary Computer. Set
# SATQUERY_AGENT_API_KEY and SATQUERY_VQA_ENABLED=true for the hosted models.

FROM node:22-alpine AS workspace
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SATQUERY_STORAGE_ROOT=/data \
    SATQUERY_FRONTEND_DIST=/app/workspace \
    PORT=7860

WORKDIR /app

COPY backend/requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY --from=workspace /app/dist ./workspace

# Hugging Face runs Spaces as uid 1000; uploads, fetched scenes and outputs
# live in /data, which is ephemeral there.
RUN useradd --create-home --uid 1000 satquery \
    && mkdir -p /data && chown satquery:satquery /data
USER satquery

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"

# Shell form so a host-provided $PORT (Render, Railway) is honoured.
CMD uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips "*"
