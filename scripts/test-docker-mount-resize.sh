#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"
RESIZE_SCRIPT="${REPO_ROOT}/scripts/resize-lxc-mount.sh"
DEFAULT_STACKS=(
  proxy-stack
  authentik-stack
  harbor-stack
  monitoring-stack
  netbox-stack
  portainer-stack
)

usage() {
  cat <<'EOF'
Usage: scripts/test-docker-mount-resize.sh [--stack <name>]... [--log-dir <path>]

Preconditions:
  1. update docker_mount.size and legacy docker_storage_size in stack.yaml to a larger value
  2. run this script under ./with-secrets so pve-test targeting and secrets are present

What this test does for each stack:
  1. require a real grow on /var/lib/docker
  2. run the operational resize workflow
  3. confirm terragrunt plan -detailed-exitcode reports no drift
  4. confirm the container is still healthy
EOF
}

fail() {
  printf '[test-docker-mount-resize] ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[test-docker-mount-resize] %s\n' "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

stack_inventory_ip() {
  local stack="$1"
  local inventory_file="${STACKS_DIR}/${stack}/inventory.yml"
  python3 - "$inventory_file" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import yaml

inventory_path = Path(sys.argv[1])
data = yaml.safe_load(inventory_path.read_text(encoding="utf-8")) or {}
children = ((data.get("all") or {}).get("children") or {})

for child in children.values():
    hosts = child.get("hosts") or {}
    for host_data in hosts.values():
        ansible_host = host_data.get("ansible_host")
        if ansible_host:
            print(ansible_host)
            raise SystemExit(0)

raise SystemExit("could not resolve ansible_host from inventory")
PY
}

stack_vmid() {
  local stack="$1"
  local stack_yaml="${STACKS_DIR}/${stack}/stack.yaml"
  python3 - "$stack_yaml" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import yaml

stack_path = Path(sys.argv[1])
data = yaml.safe_load(stack_path.read_text(encoding="utf-8")) or {}
vmid = data.get("vmid")
if vmid is None:
    raise SystemExit("stack intent missing vmid")
print(vmid)
PY
}

run_terragrunt_no_drift() {
  local stack="$1"
  local logfile="$2"
  local status=0

  pushd "${STACKS_DIR}/${stack}" >/dev/null
  set +e
  env TF_WORKSPACE=default terragrunt plan -detailed-exitcode -no-color >"${logfile}" 2>&1
  status=$?
  set -e
  popd >/dev/null

  case "${status}" in
    0)
      log "${stack}: terragrunt plan reports no drift"
      ;;
    2)
      fail "${stack}: terragrunt plan reports drift; see ${logfile}"
      ;;
    *)
      fail "${stack}: terragrunt plan failed with exit ${status}; see ${logfile}"
      ;;
  esac
}

run_stack_health_check() {
  local stack="$1"
  local ip="$2"
  local vmid="$3"
  local logfile="$4"

  {
    printf 'stack=%s\n' "${stack}"
    printf 'vmid=%s\n' "${vmid}"
    printf 'ip=%s\n' "${ip}"

    ssh -F /dev/null "root@${PVE_TEST_FQDN:-pve-test.gibbsgreatly.xyz}" "pct status '${vmid}' | grep -F 'status: running'"

    case "${stack}" in
      proxy-stack)
        curl -skI --resolve "${LAB_FQDN_TRAEFIK}:443:${LAB_IP_PROXY}" "https://${LAB_FQDN_TRAEFIK}/"
        ;;
      authentik-stack)
        curl -fsS "http://${ip}:9000/-/health/live/"
        ;;
      harbor-stack)
        bash -lc "code=\$(curl -sS -o /dev/null -w '%{http_code}' 'http://${ip}/v2/'); printf 'http_status=%s\\n' \"\${code}\"; [[ \"\${code}\" == '200' || \"\${code}\" == '301' || \"\${code}\" == '302' || \"\${code}\" == '401' ]]"
        ;;
      monitoring-stack)
        bash -lc "curl -fsS 'http://${ip}:3000/login' >/dev/null && curl -fsS 'http://${ip}:8428/-/ready'"
        ;;
      netbox-stack)
        bash -lc "code=\$(curl -sS -o /dev/null -w '%{http_code}' 'http://${ip}:8080/'); printf 'http_status=%s\\n' \"\${code}\"; [[ \"\${code}\" =~ ^(200|301|302)$ ]]"
        ;;
      portainer-stack)
        curl -fsS "http://${ip}:9000/api/system/status"
        ;;
      *)
        fail "unsupported stack health check: ${stack}"
        ;;
    esac
  } >"${logfile}" 2>&1

  log "${stack}: smoke health passed"
}

stacks=()
log_dir="/tmp/docker-mount-resize-$(date -u +%Y%m%dT%H%M%SZ)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack)
      [[ $# -ge 2 ]] || fail "--stack requires a value"
      stacks+=("$2")
      shift 2
      ;;
    --log-dir)
      [[ $# -ge 2 ]] || fail "--log-dir requires a value"
      log_dir="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

if [[ ${#stacks[@]} -eq 0 ]]; then
  stacks=("${DEFAULT_STACKS[@]}")
fi

require_command python3
require_command terragrunt
require_command ansible-playbook
require_command curl
require_command ssh

[[ -n "${TF_VAR_proxmox_node:-}" ]] || fail "TF_VAR_proxmox_node is not set; run under ./with-secrets"
[[ "${TF_VAR_proxmox_node}" == "pve-test" ]] || fail "TF_VAR_proxmox_node=${TF_VAR_proxmox_node}; expected pve-test"
[[ -n "${PVE_TEST_FQDN:-}" ]] || fail "PVE_TEST_FQDN is not set; run under ./with-secrets"

mkdir -p "${log_dir}"
log "Writing logs under ${log_dir}"

for stack in "${stacks[@]}"; do
  stack_dir="${STACKS_DIR}/${stack}"
  [[ -d "${stack_dir}" ]] || fail "stack not found: ${stack}"

  resize_log="${log_dir}/${stack}-resize.log"
  plan_log="${log_dir}/${stack}-plan.log"
  health_log="${log_dir}/${stack}-health.log"

  ip="$(stack_inventory_ip "${stack}")"
  vmid="$(stack_vmid "${stack}")"

  log "${stack}: requiring docker mount grow"
  "${RESIZE_SCRIPT}" --stack "${stack}" --require-grow >"${resize_log}" 2>&1

  run_terragrunt_no_drift "${stack}" "${plan_log}"
  run_stack_health_check "${stack}" "${ip}" "${vmid}" "${health_log}"
done

log "All docker mount resize checks passed"
