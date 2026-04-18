#!/usr/bin/env bash
# Run zone DNS validation against one or more generated stack inventories.
# Usage: ./validate-zone-dns.sh <stack-name> [stack-name...]
set -euo pipefail

if [[ $# -lt 1 ]]; then
  printf 'Usage: %s <stack-name> [stack-name...]\n' "$(basename "$0")" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAYBOOK_PATH="${SCRIPT_DIR}/ansible/playbooks/validate-zone-dns.yml"

mkdir -p /tmp/.ansible/tmp /tmp/.ansible/cp

INVENTORY_ARGS=()

for stack in "$@"; do
  inventory="${SCRIPT_DIR}/stacks/${stack}/inventory.yml"
  if [[ ! -f "${inventory}" ]]; then
    printf 'Missing inventory: %s\n' "${inventory}" >&2
    exit 1
  fi
  INVENTORY_ARGS+=( -i "${inventory}" )
done

ANSIBLE_LOCAL_TEMP=/tmp/.ansible/tmp \
ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/.ansible/cp \
ansible-playbook \
  "${INVENTORY_ARGS[@]}" \
  "${PLAYBOOK_PATH}"
