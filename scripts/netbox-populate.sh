#!/usr/bin/env bash
set -euo pipefail

# Thin operator-facing wrapper for NetBox population work.
# Supported verbs map to concrete underlying actions (no magic):
#  discover -> run discovery read-only (terraform/lxc/stacks/netbox-stack/integrations/discover.py)
#  plan     -> run containerized populate in dry-run (`populate.py --plan`)
#  apply    -> run containerized populate (default, mutates NetBox)
#  clean    -> run containerized cleanup (`populate.py --clean`)

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat <<EOF
Usage: $0 <discover|plan|apply|clean> [args...]

Verbs:
  discover  Run a read-only discovery pass (runs discover.py). Uses ./with-secrets
            if present, otherwise runs python3 directly.
  plan      Run populate in dry-run mode (containerized). Maps to populate.py --plan.
  apply     Run populate (containerized). Maps to populate.py (default apply behavior).
  clean     Run cleanup mode (containerized). Maps to populate.py --clean.

Examples:
  bash $0 discover
  bash $0 plan
  bash $0 apply
  bash $0 clean

Note: The GitHub Actions workflow uses this wrapper as the single supported entrypoint.
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

VERB="${1:-apply}"
shift || true

case "$VERB" in
  discover)
    # Prefer the workspace `with-secrets` helper when available for local runs.
    if [ -x "${ROOT_DIR}/with-secrets" ]; then
      exec "${ROOT_DIR}/with-secrets" python3 "${ROOT_DIR}/terraform/lxc/stacks/netbox-stack/integrations/discover.py" "$@"
    else
      exec python3 "${ROOT_DIR}/terraform/lxc/stacks/netbox-stack/integrations/discover.py" "$@"
    fi
    ;;

  plan)
    exec "${ROOT_DIR}/scripts/run-netbox-populate-container.sh" --plan "$@"
    ;;

  apply)
    exec "${ROOT_DIR}/scripts/run-netbox-populate-container.sh" "$@"
    ;;

  clean)
    exec "${ROOT_DIR}/scripts/run-netbox-populate-container.sh" --clean "$@"
    ;;

  *)
    echo "Unknown verb: ${VERB}" >&2
    usage
    exit 2
    ;;
esac
