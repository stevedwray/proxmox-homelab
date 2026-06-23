#!/usr/bin/env bash
set -euo pipefail

# Authentik exposes its API on HTTP port 9000 directly (TLS is provided by
# Traefik for external access and nginx for the direct-TLS endpoint).
# Check the direct HTTP API so the smoke test works before Traefik is deployed.
curl -sf "http://${LAB_IP_AUTHENTIK}:9000/api/v3/root/config/" >/dev/null

echo "authentik: API responding"
