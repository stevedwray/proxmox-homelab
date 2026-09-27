#!/usr/bin/env bash
# Read-only production MikroTik preflight for pve canaries.
#
# This script bootstraps the production env and secrets for a read-only
# verification pass, then delegates to the Python implementation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_IMPL="${SCRIPT_DIR}/preflight-production-mikrotik.py"

if [[ ! -f "${PYTHON_IMPL}" ]]; then
    echo "ERROR: missing Python implementation: ${PYTHON_IMPL}" >&2
    exit 1
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    exec python3 "${PYTHON_IMPL}" "$@"
fi

REEXEC_GUARD_VAR="PREFLIGHT_PROD_MIKROTIK_BOOTSTRAPPED"

missing_required_vars() {
    local missing=()

    [[ "${PVE_ENV:-}" == "pve" ]] || missing+=("PVE_ENV=pve")
    [[ "${TF_VAR_proxmox_node:-}" == "pve" ]] || missing+=("TF_VAR_proxmox_node=pve")
    [[ -n "${PROXMOX_HOST:-}" ]] || missing+=("PROXMOX_HOST")
    [[ -n "${MIKROTIK_HOST:-}" ]] || missing+=("MIKROTIK_HOST")
    [[ -n "${MIKROTIK_USER:-}" ]] || missing+=("MIKROTIK_USER")
    [[ -n "${MIKROTIK_PASSWORD:-}" ]] || missing+=("MIKROTIK_PASSWORD")

    if [[ ${#missing[@]} -gt 0 ]]; then
        printf '%s\n' "${missing[@]}"
    fi
}

needs_bootstrap=false
[[ -z "${PVE_ENV:-}" || "${PVE_ENV:-}" != "pve" ]] && needs_bootstrap=true
[[ -z "${TF_VAR_proxmox_node:-}" || "${TF_VAR_proxmox_node:-}" != "pve" ]] && needs_bootstrap=true
[[ -z "${PROXMOX_HOST:-}" ]] && needs_bootstrap=true
[[ -z "${MIKROTIK_HOST:-}" ]] && needs_bootstrap=true
[[ -z "${MIKROTIK_USER:-}" ]] && needs_bootstrap=true
[[ -z "${MIKROTIK_PASSWORD:-}" ]] && needs_bootstrap=true

if [[ "${needs_bootstrap}" == true ]]; then
    if [[ "${!REEXEC_GUARD_VAR:-}" == "1" ]]; then
        echo "ERROR: production MikroTik preflight bootstrap did not populate required environment variables" >&2
        echo "Missing requirements:" >&2
        while IFS= read -r item; do
            echo "  - ${item}" >&2
        done < <(missing_required_vars)
        echo "Expected source: ./with-secrets-prod (.env, .env.pve and the pve secrets profile)" >&2
        exit 1
    fi

    # Bootstrap through the production wrapper so secrets come from whichever
    # backend it uses (OpenBao since docs/secrets-refactor/ cutover). python3
    # is on with-secrets-prod's read-only allowlist.
    exec env "${REEXEC_GUARD_VAR}=1" "${REPO_ROOT}/with-secrets-prod" python3 "${PYTHON_IMPL}" "$@"
fi

exec python3 "${PYTHON_IMPL}" "$@"
