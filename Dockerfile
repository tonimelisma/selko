# Selko: one process serving the web app, the API and the background workers,
# with all state in /data (the SQLite database and the attachments).
#
#   docker run --read-only --cap-drop ALL --security-opt no-new-privileges \
#     --memory 400m -v selko-data:/data --env-file selko.env -p 8000:8000 \
#     ghcr.io/tonimelisma/selko:<sha>
#
# The image is built and cosign-signed by .github/workflows/image.yml on main.
# Its root filesystem is never written: /data is the only volume, and /tmp is
# expected to be a tmpfs (the image's own runs give it one).
#
# Behind a TLS-intercepting proxy (a cloud dev session), build with
# scripts/build-image.sh: it passes the proxy and the proxy's CA as an optional
# build secret, so the CA is used for downloads and never stored in a layer.

# --- the web app: static files, built once ---------------------------------
FROM public.ecr.aws/docker/library/node:22.12.0-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
# Same origin: the web app calls the API that serves it.
ENV VITE_API_URL=""
RUN npm run build

# --- Python dependencies ----------------------------------------------------
FROM public.ecr.aws/docker/library/python:3.14-slim-bookworm AS deps
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/README.md backend/
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    mkdir -p backend/selko && touch backend/selko/__init__.py \
    && uv sync --frozen --no-dev --no-install-workspace --package selko
COPY backend/selko backend/selko
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --frozen --no-dev --package selko --no-editable

# --- the one-time importer (docker build --target importer) ------------------
# Copies the old hosted database and its attachment files into a data
# directory, once, at cutover. A separate image so the app image never carries
# a Postgres driver: it is the selko package plus selko_import and asyncpg.
FROM public.ecr.aws/docker/library/python:3.14-slim-bookworm AS importer-deps
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/README.md backend/
COPY backend/selko backend/selko
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --frozen --no-dev --no-editable --no-install-project

FROM public.ecr.aws/docker/library/python:3.14-slim-bookworm AS importer
ARG GIT_COMMIT_SHA=""
LABEL org.opencontainers.image.source="https://github.com/tonimelisma/selko" \
      org.opencontainers.image.revision="${GIT_COMMIT_SHA}" \
      org.opencontainers.image.description="Selko one-time importer: hosted Postgres and Storage into a data directory"
RUN groupadd --gid 10001 selko && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin selko
COPY --from=importer-deps /app/.venv /app/.venv
COPY selko_import /app/selko_import
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
WORKDIR /app
ENTRYPOINT ["python", "-m", "selko_import"]

# --- runtime (the default target) ---------------------------------------------
FROM public.ecr.aws/docker/library/python:3.14-slim-bookworm
ARG GIT_COMMIT_SHA=""
LABEL org.opencontainers.image.source="https://github.com/tonimelisma/selko" \
      org.opencontainers.image.revision="${GIT_COMMIT_SHA}" \
      org.opencontainers.image.description="Selko: web app, API and workers over one SQLite file"
RUN groupadd --gid 10001 selko && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin selko \
    && mkdir /data && chown selko:selko /data
COPY --from=deps /app/.venv /app/.venv
COPY --from=web /src/frontend/build /app/web
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SELKO_DATA_DIR=/data \
    SELKO_WEB_DIR=/app/web \
    GIT_COMMIT_SHA="${GIT_COMMIT_SHA}"
USER 10001:10001
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "selko.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header", "--proxy-headers", "--forwarded-allow-ips", "*"]
