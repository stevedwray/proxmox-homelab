#!/usr/bin/env bash
# Run the full disposable network matrix validation on pve-test.
# Usage: ./validate-network-matrix.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAYBOOK_PATH="${SCRIPT_DIR}/ansible/playbooks/validate-network-matrix.yml"

mkdir -p /tmp/.ansible/tmp /tmp/.ansible/cp

INVENTORIES=(
  "${SCRIPT_DIR}/stacks/net-app-01/inventory.yml"
  "${SCRIPT_DIR}/stacks/net-svc-01/inventory.yml"
  "${SCRIPT_DIR}/stacks/net-client-01/inventory.yml"
  "${SCRIPT_DIR}/stacks/net-service-01/inventory.yml"
  "${SCRIPT_DIR}/stacks/net-client-02/inventory.yml"
  "${SCRIPT_DIR}/stacks/net-service-02/inventory.yml"
  "${SCRIPT_DIR}/stacks/net-build-01/inventory.yml"
  "${SCRIPT_DIR}/stacks/net-artifacts-01/inventory.yml"
  "${SCRIPT_DIR}/stacks/net-isolated-01/inventory.yml"
)

for inventory in "${INVENTORIES[@]}"; do
  if [[ ! -f "${inventory}" ]]; then
    printf 'Missing inventory: %s\n' "${inventory}" >&2
    exit 1
  fi
done

ANSIBLE_LOCAL_TEMP=/tmp/.ansible/tmp \
ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/.ansible/cp \
ansible-playbook \
  -i "${INVENTORIES[0]}" \
  -i "${INVENTORIES[1]}" \
  -i "${INVENTORIES[2]}" \
  -i "${INVENTORIES[3]}" \
  -i "${INVENTORIES[4]}" \
  -i "${INVENTORIES[5]}" \
  -i "${INVENTORIES[6]}" \
  -i "${INVENTORIES[7]}" \
  -i "${INVENTORIES[8]}" \
  "${PLAYBOOK_PATH}"
