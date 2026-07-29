#!/bin/bash
# Start ds2api container for Forge
# Config: 00_CORE/ds2api/config.json

FORGE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="$FORGE_ROOT/00_CORE/ds2api/config.json"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: config.json not found at $CONFIG"
  echo "Fill in your DeepSeek web account credentials first."
  exit 1
fi

if grep -q "REMPLIR_EMAIL" "$CONFIG"; then
  echo "ERROR: config.json has placeholder credentials."
  echo "Edit $CONFIG and fill in your DeepSeek web email/password."
  exit 1
fi

# Stop existing if running
docker rm -f ds2api 2>/dev/null

docker run -d \
  --name ds2api \
  --restart unless-stopped \
  -p 5001:5001 \
  -v "$CONFIG":/app/config.json:ro \
  -e DS2API_ADMIN_KEY=forge-admin \
  ghcr.io/cjackhwang/ds2api:latest

echo "ds2api starting on http://localhost:5001"
echo "Health check: curl http://localhost:5001/healthz"
echo "Models: curl http://localhost:5001/v1/models -H 'Authorization: Bearer forge-local-key'"
