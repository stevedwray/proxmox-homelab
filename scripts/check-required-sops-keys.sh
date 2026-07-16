#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_FILE="${ROOT_DIR}/terraform/secrets.common.enc.yaml"

if [[ ! -f "${SECRETS_FILE}" ]]; then
    echo "ERROR: Missing secrets file at ${SECRETS_FILE}" >&2
    exit 1
fi

required_keys=("$@")
if [[ ${#required_keys[@]} -eq 0 ]]; then
    required_keys=(
        MIKROTIK_USER
        MIKROTIK_PASSWORD
        MIKROTIK_ADMIN
        MIKROTIK_ADMIN_PASSWORD
    )
fi

missing=()
for key in "${required_keys[@]}"; do
    if ! grep -Eq "^${key}:[[:space:]]+ENC\[" "${SECRETS_FILE}"; then
        missing+=("${key}")
    fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
    {
        echo "ERROR: Required SOPS keys are missing from terraform/secrets.common.enc.yaml"
        for key in "${missing[@]}"; do
            echo "- ${key}"
        done
        echo "Repair with: SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.common.enc.yaml"
    } >&2
    exit 1
fi

echo "OK: Required SOPS keys are present in terraform/secrets.common.enc.yaml"
