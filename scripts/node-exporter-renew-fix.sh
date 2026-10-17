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
ENV_NAME="${PVE_ENV:?PVE_ENV is not set; run via a with-secrets wrapper}"
ENV_ROOT="${REPO_ROOT}/terraform/lxc/environments/${ENV_NAME}"
# Generated inventories are gitignored, so a git worktree has none: fall back to
# the main checkout's (the first entry of `git worktree list` is always it).
MAIN_ROOT="$(git -C "$REPO_ROOT" worktree list --porcelain | sed -n 's/^worktree //p;q')"
MAIN_ENV_ROOT="${MAIN_ROOT}/terraform/lxc/environments/${ENV_NAME}"

find_inventory() {  # <stack> -> path of its inventory.yml, or nothing
  local root
  for root in "$ENV_ROOT" "$MAIN_ENV_ROOT"; do
    [[ -f "${root}/$1/inventory.yml" ]] && { echo "${root}/$1/inventory.yml"; return 0; }
  done
  return 1
}

stacks=()
explicit=0
hw_hosts=0
extra=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack) stacks+=("$2"); explicit=1; shift 2 ;;
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
    while IFS= read -r name; do stacks+=("$name"); done < <(
      for inv in "${ENV_ROOT}"/*/inventory.yml "${MAIN_ENV_ROOT}"/*/inventory.yml; do
        [[ -f "$inv" ]] && basename "$(dirname "$inv")"
      done | sort -u)
  fi
  for stack in "${stacks[@]}"; do
    inv="$(find_inventory "$stack")" || {
      echo "=== ${stack}: no inventory in ${ENV_ROOT} or ${MAIN_ENV_ROOT}"
      [[ "$explicit" -eq 1 ]] && failed+=("$stack (no inventory)")  # asked for by name: not a silent skip
      continue
    }
    run_pass "$stack" -i "$inv"
  done
fi

echo; echo "ok:     ${ok[*]:-none}"; echo "failed: ${failed[*]:-none}"
[[ ${#failed[@]} -eq 0 ]]
