#!/usr/bin/env bash
# Build the Selko image locally: ./scripts/build-image.sh [tag]
#
# In a cloud dev session, outbound HTTPS goes through a TLS-intercepting proxy
# that build containers neither reach nor trust. This passes the proxy and its
# CA (as an optional build secret, never stored in a layer) when present; with
# neither set it is a plain `docker build`, as in CI.
set -euo pipefail
cd "$(dirname "$0")/.."
tag="${1:-selko:dev}"
args=(--build-arg "GIT_COMMIT_SHA=$(git rev-parse HEAD)" -t "$tag")
ca="${SELKO_BUILD_CA:-/root/.ccr/ca-bundle.crt}"
if [[ -n "${HTTPS_PROXY:-${https_proxy:-}}" ]]; then
  args+=(--network host
    --build-arg "HTTPS_PROXY=${HTTPS_PROXY:-${https_proxy:-}}"
    --build-arg "HTTP_PROXY=${HTTP_PROXY:-${http_proxy:-${HTTPS_PROXY:-${https_proxy:-}}}}")
fi
if [[ -f "$ca" ]]; then
  args+=(--secret "id=ca,src=$ca")
fi
DOCKER_BUILDKIT=1 exec docker build "${args[@]}" .
