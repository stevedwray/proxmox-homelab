#!/usr/bin/env bash
# Production external infrastructure preflight.
#
# Tests that all production secrets are present and that external systems
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
# with-secrets-prod loads .env + .env.pve + the pve profile from OpenBao.
if [[ "${!REEXEC_GUARD_VAR:-}" != "1" ]]; then
    # with-secrets-prod checks its own prerequisites (the deploy-pve
    # AppRole credentials in ~/.config/openbao/).
    exec env "${REEXEC_GUARD_VAR}=1" "${REPO_ROOT}/with-secrets-prod" "$0" "$@"
fi

exec python3 "${PYTHON_IMPL}" "$@"
