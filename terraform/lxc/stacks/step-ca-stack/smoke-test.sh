#!/usr/bin/env bash
set -euo pipefail

# Prefer environment-specific root CA cert (written by deploy-step-ca.yml for
# non-production envs); fall back to the shared root for production.
ENV_CERT="${REPO_ROOT}/certs/homelab-root.${PVE_ENV:-}.crt"
ROOT_CERT="${REPO_ROOT}/certs/homelab-root.crt"
if [[ -f "$ENV_CERT" ]]; then
  ROOT_CERT="$ENV_CERT"
fi

if command -v step &>/dev/null; then
  step ca health \
    --ca-url "https://${LAB_IP_STEP_CA}" \
    --root "$ROOT_CERT"
else
  curl -sf --cacert "$ROOT_CERT" \
    "https://${LAB_IP_STEP_CA}/health" >/dev/null
fi

echo "step-ca: healthy"
