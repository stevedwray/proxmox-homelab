#!/usr/bin/env bash
set -euo pipefail

curl -sf --cacert "${REPO_ROOT}/certs/homelab-root.crt" \
  "https://${LAB_FQDN_AUTHENTIK}/api/v3/root/config/" >/dev/null

echo "authentik: API responding"
