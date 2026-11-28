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

# The official base images, from a registry mirror of Docker Hub's library.
# CI uses mirror.gcr.io: public.ecr.aws refuses anonymous pulls from shared
# runner addresses once their data limit is spent. Cloud sessions keep the
# default, which their network allows.
ARG BASE_REGISTRY=public.ecr.aws/docker/library

# --- the web app: static files, built once ---------------------------------
FROM ${BASE_REGISTRY}/node:22.12.0-bookworm-slim AS web
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
FROM ${BASE_REGISTRY}/python:3.14-slim-bookworm AS deps
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

# --- runtime -----------------------------------------------------------------
FROM ${BASE_REGISTRY}/python:3.14-slim-bookworm
ARG GIT_COMMIT_SHA=""
# Where production reads its keys (selko.keyvault): the Entra app and the two
# vaults, passed by CI from repository variables. Not secrets; a value set in
# the server's env file wins. Empty when built elsewhere.
ARG AZURE_TENANT_ID=""
ARG AZURE_CLIENT_ID=""
ARG SELKO_KEYVAULT_URL=""
ARG SELKO_KEYVAULT_HOSTS_URL=""
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
    GIT_COMMIT_SHA="${GIT_COMMIT_SHA}" \
    AZURE_TENANT_ID="${AZURE_TENANT_ID}" \
    AZURE_CLIENT_ID="${AZURE_CLIENT_ID}" \
    SELKO_KEYVAULT_URL="${SELKO_KEYVAULT_URL}" \
    SELKO_KEYVAULT_HOSTS_URL="${SELKO_KEYVAULT_HOSTS_URL}"
USER 10001:10001
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "selko.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header", "--proxy-headers", "--forwarded-allow-ips", "*"]
