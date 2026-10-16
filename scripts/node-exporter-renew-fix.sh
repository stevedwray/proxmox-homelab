#!/usr/bin/env bash
# Run terraform/lxc/ansible/playbooks/node-exporter-renew-fix.yml against every
# stack inventory of the selected environment, one pass per stack, and report
# which passes failed. See the playbook header for why.
#
#   export TASK_APPROVAL=node-exporter-renew-fix
#   ./with-secrets-prod       scripts/node-exporter-renew-fix.sh            # pve
#   ./with-secrets-prod-tiny  scripts/node-exporter-renew-fix.sh            # pve-tiny
#   ./with-secrets-prod       scripts/node-exporter-renew-fix.sh --stack harbor-stack
#   ./with-secrets-prod       scripts/node-exporter-renew-fix.sh --hw-hosts # bare-metal hosts
#   add --check for a dry run
#
# Stacks whose inventory is missing or unreachable are reported and skipped; the
# exit status is non-zero if any pass failed.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLAYBOOK="${REPO_ROOT}/terraform/lxc/ansible/playbooks/node-exporter-renew-fix.yml"
export ANSIBLE_CONFIG="${REPO_ROOT}/terraform/lxc/ansible/ansible.cfg"
ENV_ROOT="${REPO_ROOT}/terraform/lxc/environments/${PVE_ENV:?PVE_ENV is not set; run via a with-secrets wrapper}"

stacks=()
hw_hosts=0
extra=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack) stacks+=("$2"); shift 2 ;;
    --hw-hosts) hw_hosts=1; shift ;;
    --check) extra+=(--check); shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

failed=()
ok=()
run_pass() {  # <label> <ansible-playbook args...>
  local label="$1"; shift
  echo "=== ${label}"
  if ansible-playbook "$PLAYBOOK" -u root --timeout 15 "${extra[@]}" "$@"; then ok+=("$label"); else failed+=("$label"); fi
}

if [[ "$hw_hosts" -eq 1 ]]; then
  # pve, pve-tiny, pve-test, argon-01/02: not Terraform stacks, so they live in
  # the shared inventory (each host sets its own ansible_user, which overrides -u).
  run_pass "hw_hosts" -i "${REPO_ROOT}/ansible/inventory/inventory.yml" --limit hw_hosts
else
  if [[ ${#stacks[@]} -eq 0 ]]; then
    for inv in "${ENV_ROOT}"/*/inventory.yml; do stacks+=("$(basename "$(dirname "$inv")")"); done
  fi
  for stack in "${stacks[@]}"; do
    inv="${ENV_ROOT}/${stack}/inventory.yml"
    [[ -f "$inv" ]] || { echo "=== ${stack}: no inventory, skipped"; continue; }
    run_pass "$stack" -i "$inv"
  done
fi

echo; echo "ok:     ${ok[*]:-none}"; echo "failed: ${failed[*]:-none}"
[[ ${#failed[@]} -eq 0 ]]
