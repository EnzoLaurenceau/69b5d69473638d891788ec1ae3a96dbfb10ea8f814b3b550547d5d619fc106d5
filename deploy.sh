#!/usr/bin/env bash
# deploy.sh — Build, tag, and prepare Forge images for Coolify deployment.
#
# Usage:
#   ./deploy.sh                    # build + tag with git SHA
#   ./deploy.sh --tag v1.2.3       # build + tag with custom version
#   ./deploy.sh --push registry    # build + tag + push to registry
#
# Requires: docker, docker compose, git

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────
REGISTRY="${REGISTRY:-ghcr.io}"
ORG="${ORG:-laforge}"
API_IMAGE="forge-api:prod"
CONSOLE_IMAGE="forge-console:prod"
PROMETHEUS_IMAGE="prom/prometheus:latest"

# ── Parse args ────────────────────────────────────────────────────────────
CUSTOM_TAG=""
PUSH_REGISTRY=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag) CUSTOM_TAG="$2"; shift 2 ;;
        --push) PUSH_REGISTRY="$2"; shift 2 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

# ── Version tag ───────────────────────────────────────────────────────────
if [[ -n "$CUSTOM_TAG" ]]; then
    VERSION="$CUSTOM_TAG"
else
    VERSION="$(git rev-parse --short HEAD 2>/dev/null || echo 'local')"
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  Forge Deploy — tag: $VERSION"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. Build prod images ─────────────────────────────────────────────────
echo ""
echo "▶ Building API prod image..."
docker build -f docker/api.prod.Dockerfile -t "$API_IMAGE" -t "${REGISTRY}/${ORG}/api:${VERSION}" .

echo ""
echo "▶ Building Console prod image..."
docker build -f console/Dockerfile -t "$CONSOLE_IMAGE" -t "${REGISTRY}/${ORG}/console:${VERSION}" ./console

# ── 2. Tag images ────────────────────────────────────────────────────────
echo ""
echo "▶ Tagging images..."
echo "  ${API_IMAGE}     → ${REGISTRY}/${ORG}/api:${VERSION}"
echo "  ${CONSOLE_IMAGE} → ${REGISTRY}/${ORG}/console:${VERSION}"

# ── 3. Save image sizes ──────────────────────────────────────────────────
echo ""
echo "▶ Image sizes:"
docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -E "forge-(api|console)" | head -4

# ── 4. Push (optional) ──────────────────────────────────────────────────
if [[ -n "$PUSH_REGISTRY" ]]; then
    echo ""
    echo "▶ Pushing to ${PUSH_REGISTRY}..."
    docker tag "${REGISTRY}/${ORG}/api:${VERSION}" "${PUSH_REGISTRY}/${ORG}/api:${VERSION}"
    docker tag "${REGISTRY}/${ORG}/console:${VERSION}" "${PUSH_REGISTRY}/${ORG}/console:${VERSION}"
    docker push "${PUSH_REGISTRY}/${ORG}/api:${VERSION}"
    docker push "${PUSH_REGISTRY}/${ORG}/console:${VERSION}"
    echo "  ✅ Pushed to ${PUSH_REGISTRY}"
fi

# ── 5. Deployment manifest ───────────────────────────────────────────────
MANIFEST="09_TASKS/DEPLOY_${VERSION}.json"
cat > "$MANIFEST" << EOF
{
  "version": "${VERSION}",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "images": {
    "api": "${REGISTRY}/${ORG}/api:${VERSION}",
    "console": "${REGISTRY}/${ORG}/console:${VERSION}",
    "prometheus": "${PROMETHEUS_IMAGE}"
  },
  "compose_file": "docker-compose.prod.yml",
  "services": {
    "api": {
      "port": 7777,
      "healthcheck": "/api/health",
      "env_required": ["POSTGRES_PASSWORD", "WEB_SECRET", "FORGE_ADMIN_TOKEN", "FORGE_CORS_ORIGINS"]
    },
    "console": {
      "port": 8080,
      "healthcheck": "/",
      "proxy": "/v1 → api:7777"
    },
    "postgres": {
      "image": "pgvector/pgvector:pg16",
      "volume": "forge_pgdata"
    },
    "redis": {
      "image": "redis:7-alpine",
      "volume": "forge_redisdata"
    },
    "prometheus": {
      "volume": "forge_promdata"
    }
  },
  "rollback": "docker compose -f docker-compose.prod.yml down && docker compose -f docker-compose.prod.yml up -d"
}
EOF

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ Deploy manifest: ${MANIFEST}"
echo "  📦 API:      ${REGISTRY}/${ORG}/api:${VERSION}"
echo "  🖥️  Console:  ${REGISTRY}/${ORG}/console:${VERSION}"
echo ""
echo "  Next: deploy to Coolify with:"
echo "    python 00_CORE/tools/delivery/coolify.py"
echo "    # or: docker compose -f docker-compose.prod.yml up -d"
echo "═══════════════════════════════════════════════════════════════"
