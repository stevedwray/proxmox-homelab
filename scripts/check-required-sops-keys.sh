#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_FILE="${ROOT_DIR}/terraform/secrets.common.enc.yaml"

if [[ ! -f "${SECRETS_FILE}" ]]; then
    echo "ERROR: Missing secrets file at ${SECRETS_FILE}" >&2
    exit 1
fi

# Called with explicit key names (e.g. from another script): check only
# those, same as before.
#
# Called with no args (the normal pre-commit case): check EVERY top-level
# key in the file, not just a hardcoded few. This started as a
# MIKROTIK_*-only check; it missed HARBOR_DB_PASSWORD getting silently
# wiped to "" in commit 84ee8c80 (2026-08-24, unrelated docs-rag-mcp
# work that added three other keys in the same sops edit) because
# HARBOR_DB_PASSWORD was never on the hardcoded list. That corruption
# sat dormant for 5 days -- harmless until something finally forced a
# recreate of the container reading it -- then took down harbor-stack
# in production. A hardcoded allowlist can only ever catch keys someone
# already thought to list; scanning every key catches this class of
# mistake regardless of which key it hits next time.
required_keys=("$@")

top_level_keys() {
    # Real secrets in this file are always flush-left "KEY: value" lines
    # (all-caps by convention, but match any valid YAML key so a
    # differently-cased key isn't silently skipped). sops's own metadata
    # block is the one non-secret flush-left key -- its nested children
    # (age:, lastmodified:, mac:, etc.) are indented, so they don't
    # match here at all; only the "sops:" line itself needs excluding.
    grep -E '^[A-Za-z_][A-Za-z0-9_]*:' "${SECRETS_FILE}" | grep -v '^sops:' | cut -d: -f1
}

if [[ ${#required_keys[@]} -eq 0 ]]; then
    mapfile -t required_keys < <(top_level_keys)
fi

bad=()
for key in "${required_keys[@]}"; do
    if ! grep -Eq "^${key}:[[:space:]]+ENC\[" "${SECRETS_FILE}"; then
        bad+=("${key}")
    fi
done

if [[ ${#bad[@]} -gt 0 ]]; then
    {
        echo "ERROR: These keys in terraform/secrets.common.enc.yaml are missing or not a valid encrypted (ENC[...]) value:"
        for key in "${bad[@]}"; do
            echo "- ${key}"
        done
        echo "If one of these was just wiped/blanked by an edit, recover it from git history rather than re-set a new value blind:"
        echo "  git log --follow -p -- terraform/secrets.common.enc.yaml   # find the last commit where it was still ENC[...]"
        echo "  git show <that-commit>:terraform/secrets.common.enc.yaml > /tmp/old.enc.yaml"
        echo "  SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops -d --extract '[\"KEY_NAME\"]' /tmp/old.enc.yaml"
        echo "  SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --set '[\"KEY_NAME\"] \"<recovered value>\"' terraform/secrets.common.enc.yaml"
        echo "To edit multiple keys at once safely, use: SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.common.enc.yaml"
        echo "then re-run this check before committing to confirm nothing else got touched."
    } >&2
    exit 1
fi

echo "OK: All ${#required_keys[@]} key(s) in terraform/secrets.common.enc.yaml are present and encrypted"
