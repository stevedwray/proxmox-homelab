#!/usr/bin/env bash
set -euo pipefail

# merge-sops-env.sh <base-file> [prod-file] -- <command> [args...]
# Decrypts the provided SOPS files (base first, then prod) and sources
# their keys into the current shell as exported environment variables,
# then execs the provided command. Uses process substitution to avoid
# writing plaintext to disk.

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <secrets-file> -- <command> [args...]" >&2
    exit 2
fi

BASE_FILE="$1"
shift

PROD_FILE=""
if [[ $# -ge 1 && "$1" != "--" ]]; then
    PROD_FILE="$1"
    shift
fi

if [[ $# -ge 1 && "$1" == "--" ]]; then
    shift
fi

if [[ -f "$BASE_FILE" ]]; then
    source <(sops --decrypt --output-type json "$BASE_FILE" | jq -r 'to_entries|map("export \(.key)=\(.value|@sh)")|.[]')
fi

if [[ -n "$PROD_FILE" && -f "$PROD_FILE" ]]; then
    source <(sops --decrypt --output-type json "$PROD_FILE" | jq -r 'to_entries|map("export \(.key)=\(.value|@sh)")|.[]')
fi

if [[ $# -eq 0 ]]; then
    echo "No command provided after --" >&2
    exit 2
fi

exec "$@"
