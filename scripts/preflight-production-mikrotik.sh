#!/usr/bin/env bash
# Read-only production MikroTik preflight for pve canaries.
#
# This script bootstraps the production env and secrets for a read-only
# verification pass, then delegates to the Python implementation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROD_SECRETS_FILE="${REPO_ROOT}/terraform/secrets.pve.enc.yaml"
AGE_KEY_FILE="${HOME}/.config/sops/age/keys.txt"
PROD_ENV_FILE="${REPO_ROOT}/.env.pve"
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
        echo "Expected source: terraform/secrets.pve.enc.yaml and/or .env.pve" >&2
        exit 1
    fi

    if [[ ! -f "${AGE_KEY_FILE}" ]]; then
        echo "ERROR: age private key not found at ${AGE_KEY_FILE}" >&2
        exit 1
    fi

    if [[ ! -f "${PROD_SECRETS_FILE}" ]]; then
        echo "ERROR: production secrets file not found at ${PROD_SECRETS_FILE}" >&2
        exit 1
    fi

    if [[ -f "${PROD_ENV_FILE}" ]]; then
        set -a
        # shellcheck source=/dev/null
        source "${PROD_ENV_FILE}"
        set +a
    fi

    export PVE_ENV="pve"
    export TF_VAR_proxmox_node="${TF_VAR_proxmox_node:-pve}"
    export "${REEXEC_GUARD_VAR}=1"

    exec env SOPS_AGE_KEY_FILE="${AGE_KEY_FILE}" \
        sops exec-env "${PROD_SECRETS_FILE}" "$(printf '%q ' "$0" "$@")"
fi

exec python3 "${PYTHON_IMPL}" "$@"
