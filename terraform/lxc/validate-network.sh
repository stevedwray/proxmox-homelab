#!/usr/bin/env bash
# Run the network-layer validation playbook against a client/service pair.
# Usage: ./validate-network.sh [service-host] [client-host]
# Defaults to net-service-01 and net-client-01.
set -euo pipefail

SERVICE_HOST="${1:-net-service-01}"
CLIENT_HOST="${2:-net-client-01}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="${SCRIPT_DIR}/ansible"

ansible-playbook \
  -i "${SCRIPT_DIR}/stacks/${SERVICE_HOST}/inventory.yml" \
  -i "${SCRIPT_DIR}/stacks/${CLIENT_HOST}/inventory.yml" \
  -e "network_validation_service_host=${SERVICE_HOST}" \
  -e "network_validation_client_host=${CLIENT_HOST}" \
  "${ANSIBLE_DIR}/playbooks/validate-network-layer.yml"
