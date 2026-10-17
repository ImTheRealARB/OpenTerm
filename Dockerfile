# OpenTerm: one image that serves the API, the WebSocket and the built frontend on :8000.
#   docker build -t openterm .
#   docker run --rm -p 8000:8000 -v openterm-data:/data openterm
# Not verified on the machine that wrote it (Docker was not installed). See docs/RELEASE_NOTES.md.

# --- stage 1: build the frontend ---
FROM node:22-alpine AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- stage 2: backend runtime (uv) ---
FROM python:3.12-slim AS run
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    OPENTERM_HOST=0.0.0.0 \
    OPENTERM_PORT=8000 \
    OPENTERM_DB_PATH=/data/openterm.db \
    OPENTERM_STATIC_DIR=/app/frontend/dist \
    PATH="/app/backend/.venv/bin:$PATH"
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/openterm ./openterm
COPY config.yaml /app/config.yaml
COPY --from=web /src/frontend/dist /app/frontend/dist
RUN uv sync --frozen --no-dev \
    && mkdir -p /data \
    && useradd --system --uid 10001 openterm \
    && chown -R openterm /data
USER openterm
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"
CMD ["python", "-m", "openterm"]
