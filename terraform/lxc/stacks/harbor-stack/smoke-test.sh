#!/usr/bin/env bash
set -euo pipefail

curl -sf --cacert "${REPO_ROOT}/certs/homelab-root.crt" \
  "https://${LAB_FQDN_HARBOR}/api/v2.0/health" \
  | grep -q '"status":"healthy"'

echo "harbor: healthy"
