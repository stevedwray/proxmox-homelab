#!/bin/bash
# with-secrets-prod-lib.sh — shared engine behind every per-node production
# wrapper (with-secrets-prod, with-secrets-prod-framework, ...).
#
# Do not call this script directly. Each production node gets a thin
# entrypoint at the repo root (e.g. ./with-secrets-prod) that sets
# PVE_PROD_NODE and execs this file. Keeping the logic in one place means
# adding a new production node never means copy-pasting the approval gate,
# command classifier, or secrets-loading logic — see
# docs/framework-integration/decisions.md Decision 6.
#
# Required caller contract:
#   PVE_PROD_NODE   the target Proxmox node (e.g. "pve", "pve-framework")
#   REPO_ROOT       absolute path to the repo root
#
# This wrapper enforces production credential controls:
# - loads shared non-secret config plus this node's production overrides
# - loads this node's production secrets ONLY (never dev secrets)
# - enforces TF_VAR_proxmox_node=${PVE_PROD_NODE}
# - uses a conservative read-only allowlist
# - blocks mutating or ambiguous commands unless explicit operator approval is present
#
# To acknowledge an approved mutating task, set:
#   export TASK_APPROVAL="task-name-from-docs"
#   ./with-secrets-prod <mutating-command>          # node = pve
#   ./with-secrets-prod-framework <mutating-command> # node = pve-framework

set -euo pipefail

if [[ -z "${PVE_PROD_NODE:-}" || -z "${REPO_ROOT:-}" ]]; then
    echo "ERROR: with-secrets-prod-lib.sh must not be called directly." >&2
    echo "Use ./with-secrets-prod or ./with-secrets-prod-framework." >&2
    exit 2
fi

SCRIPT_DIR="${REPO_ROOT}"
PROD_NODES_FILE="${SCRIPT_DIR}/terraform/PRODUCTION_NODES"
BASE_SECRETS_FILE="${SCRIPT_DIR}/terraform/secrets.common.enc.yaml"
PROD_SECRETS_FILE="${SCRIPT_DIR}/terraform/secrets.${PVE_PROD_NODE}.enc.yaml"
AGE_KEY_FILE="${HOME}/.config/sops/age/keys.txt"
BASE_ENV_FILE="${SCRIPT_DIR}/.env"
PROD_ENV_FILE="${SCRIPT_DIR}/.env.${PVE_PROD_NODE}"

# Refuse to run at all for a node that isn't declared production. This is
# the one guard that must never be silently bypassed — it's what stops a
# typo'd PVE_PROD_NODE from picking up a dev secrets file and calling it
# "production".
if [[ ! -f "${PROD_NODES_FILE}" ]] || ! grep -qxF "${PVE_PROD_NODE}" <(grep -v '^\s*#' "${PROD_NODES_FILE}" | grep -v '^\s*$'); then
    echo "ERROR: '${PVE_PROD_NODE}' is not listed in terraform/PRODUCTION_NODES" >&2
    echo "Add it there first if this node is genuinely production-trust." >&2
    exit 1
fi

if [[ ! -f "${AGE_KEY_FILE}" ]]; then
    echo "ERROR: age private key not found at ${AGE_KEY_FILE}" >&2
    echo "Retrieve from Bitwarden: 'proxmox-homelab age private key'" >&2
    echo "Then: mkdir -p ~/.config/sops/age && install -m 600 /dev/stdin ${AGE_KEY_FILE}" >&2
    exit 1
fi

if [[ ! -f "${PROD_SECRETS_FILE}" ]]; then
    echo "ERROR: production secrets file not found at ${PROD_SECRETS_FILE}" >&2
    echo "Production secrets must be stored separately from dev secrets." >&2
    echo "Ensure terraform/secrets.${PVE_PROD_NODE}.enc.yaml exists and is encrypted with SOPS." >&2
    exit 1
fi

if [[ $# -eq 0 ]]; then
    echo "Usage: $(basename "$0") <command> [args...]" >&2
    exit 1
fi

# Load shared non-secret config first, then this node's production
# overrides. Keeps every production node on the same baseline while each
# still uses its own separate SOPS secrets.
if [[ -f "${BASE_ENV_FILE}" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "${BASE_ENV_FILE}"
    set +a
fi

if [[ -f "${PROD_ENV_FILE}" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "${PROD_ENV_FILE}"
    set +a
else
    echo "ERROR: production env overlay not found at ${PROD_ENV_FILE}" >&2
    echo "Every production node needs its own .env.<node> overlay — see .env.pve for the shape." >&2
    exit 1
fi

# Force this node's environment
export PVE_ENV="${PVE_PROD_NODE}"
export TF_VAR_proxmox_node="${TF_VAR_proxmox_node:-${PVE_PROD_NODE}}"

# Validate targeting — .env.<node> must agree with the wrapper it was loaded by.
if [[ "${TF_VAR_proxmox_node}" != "${PVE_PROD_NODE}" ]]; then
    echo "ERROR: TF_VAR_proxmox_node=${TF_VAR_proxmox_node} (expected '${PVE_PROD_NODE}')" >&2
    echo "This wrapper must target '${PVE_PROD_NODE}', not other nodes." >&2
    echo "Check .env.${PVE_PROD_NODE} for a stale TF_VAR_proxmox_node value." >&2
    exit 1
fi

# Guard against cross-environment LAB_DOMAIN contamination. If LAB_DOMAIN is
# set to a test-environment value the shell inherited from a prior
# pve-test-vm session, an Ansible provision would issue step-ca certs for
# the wrong domain on a production host. Every .env.<production-node> must
# declare LAB_DOMAIN explicitly so this sourcing order always wins.
if [[ "${LAB_DOMAIN:-}" =~ ^(test\.gibbsgreatly\.xyz|.*\.test\.gibbsgreatly\.xyz)$ ]]; then
    echo "ERROR: LAB_DOMAIN='${LAB_DOMAIN}' is a test-environment domain but this is the '${PVE_PROD_NODE}' production wrapper." >&2
    echo "Shell env is contaminated from a prior pve-test-vm session." >&2
    echo "Fix: ensure .env.${PVE_PROD_NODE} explicitly sets LAB_DOMAIN." >&2
    exit 1
fi

# Production Harbor uses the standard LE cert; step-ca is for non-prod only.
export HARBOR_TLS_RESOLVER="letsencrypt"

normalize_lab_tfvars() {
    local var_name value ref_name ref_value tf_var_name
    local placeholder_pattern='^\$\{([A-Z0-9_]+)\}$'

    for var_name in $(compgen -A variable LAB_); do
        value="${!var_name}"
        [[ -n "${value}" ]] || continue
        tf_var_name="TF_VAR_${var_name,,}"
        # Always override TF_VAR_lab_* from LAB_* for the selected environment.
        # Stale TF_VAR_ values inherited from a previous shell session must not
        # win over the current production env file.
        export "${tf_var_name}=${value}"
    done

    for var_name in $(compgen -A variable TF_VAR_lab_); do
        value="${!var_name}"
        if [[ "${value}" =~ ${placeholder_pattern} ]]; then
            ref_name="${BASH_REMATCH[1]}"
            ref_value="${!ref_name-}"
            if [[ "${ref_name}" == LAB_* && -n "${ref_value}" ]]; then
                export "${var_name}=${ref_value}"
            fi
        fi
    done
}

# Command classification: determine if the command is explicitly allowed read-only
# or must be treated as mutating/approval-required.
classify_command() {
    local cmd="$1"
    shift

    case "${cmd}" in
        pct)
            if [[ "${1:-}" == "list" ]]; then
                echo "read-only"
                return 0
            fi
            ;;
        qm)
            if [[ "${1:-}" == "list" ]]; then
                echo "read-only"
                return 0
            fi
            ;;
        pvesm)
            if [[ "${1:-}" == "status" ]]; then
                echo "read-only"
                return 0
            fi
            ;;
        pvesh)
            if [[ "${1:-}" == "get" ]]; then
                echo "read-only"
                return 0
            fi
            ;;
        terraform)
            if [[ "${1:-}" == "plan" ]] || [[ "${1:-}" == "validate" ]] || [[ "${1:-}" == "version" ]]; then
                echo "read-only"
                return 0
            fi
            ;;
        terragrunt)
            if [[ "${1:-}" == "plan" ]] || [[ "${1:-}" == "validate" ]] || [[ "${1:-}" == "show" ]] || [[ "${1:-}" == "output" ]]; then
                echo "read-only"
                return 0
            fi
            ;;
        dig|ping|ansible-inventory|printenv|python3)
            echo "read-only"
            return 0
            ;;
    esac

    echo "mutating"
    return 0
}

# Determine if this is a mutating operation
FULL_CMD="${*}"
CMD_CLASS="$(classify_command "$(basename "$1")" "${@:2}")"

# Block mutating commands without explicit approval
if [[ "${CMD_CLASS}" == "mutating" ]]; then
    if [[ -z "${TASK_APPROVAL:-}" ]]; then
        echo "ERROR: Mutating command requires explicit operator approval" >&2
        echo "" >&2
        echo "This command would alter '${PVE_PROD_NODE}' production state:" >&2
        echo "  ${FULL_CMD}" >&2
        echo "" >&2
        echo "To proceed, you must:" >&2
        echo "  1. Review the preflight summary in the chat session" >&2
        echo "  2. Explicitly approve in chat (e.g., 'proceed with task XYZ')" >&2
        echo "  3. Set the approval environment variable to acknowledge that approved task:" >&2
        echo "     export TASK_APPROVAL=\"<task-name-from-docs>\"" >&2
        echo "  4. Run the command again" >&2
        echo "" >&2
        echo "Note: this wrapper cannot verify chat history on its own; it relies on" >&2
        echo "the operator to set TASK_APPROVAL only after chat approval." >&2
        exit 1
    fi

    echo "=== PRODUCTION MUTATION APPROVED (${PVE_PROD_NODE}) ===" >&2
    echo "Task: ${TASK_APPROVAL}" >&2
    echo "Command: ${FULL_CMD}" >&2
    echo "" >&2
fi

normalize_lab_tfvars

# Load this node's production secrets overlaying the base (dev) secrets,
# then execute the command. Decrypts both SOPS files to JSON and sources
# them as shell exports (without writing plaintext to disk), in order, so
# this node's values override the shared base.
if [[ -f "${BASE_SECRETS_FILE}" ]]; then
    exec env SOPS_AGE_KEY_FILE="${AGE_KEY_FILE}" bash "${SCRIPT_DIR}/scripts/merge-sops-env.sh" "${BASE_SECRETS_FILE}" "${PROD_SECRETS_FILE}" -- "$@"
else
    exec env SOPS_AGE_KEY_FILE="${AGE_KEY_FILE}" bash "${SCRIPT_DIR}/scripts/merge-sops-env.sh" "${PROD_SECRETS_FILE}" -- "$@"
fi
