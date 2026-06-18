#!/usr/bin/env bash
# Production external infrastructure preflight.
#
# Tests that all production SOPS secrets are present and that external systems
# (Proxmox, MikroTik, Cloudflare, SSH, GitHub CLI) are reachable with the
# configured credentials.
#
# Run standalone:
#   ./scripts/preflight-production-external.sh
#   ./scripts/preflight-production-external.sh --save-evidence docs/productionize-refactor/evidence/
#
# Or explicitly via the production wrapper (same result — script self-bootstraps):
#   ./with-secrets-prod scripts/preflight-production-external.sh
#
# All secrets are injected by with-secrets-prod; nothing is written to disk.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_IMPL="${SCRIPT_DIR}/preflight-production-external.py"
REEXEC_GUARD_VAR="PREFLIGHT_PROD_EXTERNAL_BOOTSTRAPPED"

if [[ ! -f "${PYTHON_IMPL}" ]]; then
    echo "ERROR: missing Python implementation: ${PYTHON_IMPL}" >&2
    exit 1
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    exec python3 "${PYTHON_IMPL}" "$@"
fi

# Self-bootstrap: re-exec under with-secrets-prod if not already running inside it.
# with-secrets-prod loads .env + .env.pve + both SOPS files (base + pve overlay).
if [[ "${!REEXEC_GUARD_VAR:-}" != "1" ]]; then
    AGE_KEY_FILE="${HOME}/.config/sops/age/keys.txt"
    PROD_SECRETS_FILE="${REPO_ROOT}/terraform/secrets.pve.enc.yaml"

    if [[ ! -f "${AGE_KEY_FILE}" ]]; then
        echo "ERROR: age private key not found at ${AGE_KEY_FILE}" >&2
        echo "Retrieve from Bitwarden: 'proxmox-homelab age private key'" >&2
        exit 1
    fi

    if [[ ! -f "${PROD_SECRETS_FILE}" ]]; then
        echo "ERROR: production secrets file not found at ${PROD_SECRETS_FILE}" >&2
        exit 1
    fi

    exec env "${REEXEC_GUARD_VAR}=1" "${REPO_ROOT}/with-secrets-prod" "$0" "$@"
fi

exec python3 "${PYTHON_IMPL}" "$@"
