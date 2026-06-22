#!/usr/bin/env bash
set -euo pipefail

if command -v step &>/dev/null; then
  step ca health \
    --ca-url "https://${LAB_IP_STEP_CA}" \
    --root "${REPO_ROOT}/certs/homelab-root.crt"
else
  curl -sf --cacert "${REPO_ROOT}/certs/homelab-root.crt" \
    "https://${LAB_IP_STEP_CA}/health" >/dev/null
fi

echo "step-ca: healthy"
