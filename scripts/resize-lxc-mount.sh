#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"
ANSIBLE_DIR="${REPO_ROOT}/terraform/lxc/ansible"
PLAYBOOK_FILE="${ANSIBLE_DIR}/playbooks/resize-lxc-mount.yml"

usage() {
  cat <<'EOF'
Usage: scripts/resize-lxc-mount.sh --stack <name> [--mount-path <path>] [--check] [--require-grow] [--allow-nonempty-target]

Supported sequence:
  1. update desired size in stack.yaml
  2. run this operational mount workflow
  3. verify pct config and guest df output
  4. confirm terragrunt plan -no-color returns no drift
EOF
}

fail() {
  printf '[resize-lxc-mount] ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[resize-lxc-mount] %s\n' "$*"
}

stack_name=""
mount_path="/var/lib/docker"
check_mode=false
require_grow=false
allow_nonempty_target=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack)
      [[ $# -ge 2 ]] || fail "--stack requires a value"
      stack_name="$2"
      shift 2
      ;;
    --mount-path)
      [[ $# -ge 2 ]] || fail "--mount-path requires a value"
      mount_path="$2"
      shift 2
      ;;
    --check)
      check_mode=true
      shift
      ;;
    --require-grow)
      require_grow=true
      shift
      ;;
    --allow-nonempty-target)
      allow_nonempty_target=true
      shift
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

[[ -n "$stack_name" ]] || fail "--stack is required"

stack_dir="${STACKS_DIR}/${stack_name}"
stack_yaml="${stack_dir}/stack.yaml"
inventory_file="${stack_dir}/inventory.yml"

[[ -f "$PLAYBOOK_FILE" ]] || fail "playbook not found: ${PLAYBOOK_FILE}"
[[ -f "$stack_yaml" ]] || fail "stack.yaml not found: ${stack_yaml}"
[[ -f "$inventory_file" ]] || fail "inventory file not found: ${inventory_file}; run terragrunt apply or refresh inventory first"

effective_proxmox_node="${TF_VAR_proxmox_node:-}"
[[ -n "$effective_proxmox_node" ]] || fail "TF_VAR_proxmox_node is required; run via ./with-secrets"

storage_manifest="${REPO_ROOT}/terraform/lxc/storage/${effective_proxmox_node}.yaml"
[[ -f "$storage_manifest" ]] || fail "storage manifest not found: ${storage_manifest}"

intent_output="$(python3 - "$stack_yaml" "$mount_path" "$storage_manifest" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import yaml

stack_path = Path(sys.argv[1])
mount_path = sys.argv[2]
manifest_path = Path(sys.argv[3])
data = yaml.safe_load(stack_path.read_text(encoding="utf-8")) or {}
manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


def resolve_extra_mount_storage(stack: dict, manifest: dict) -> str | None:
  extra_mount = stack.get("extra_mount") or {}
  profile = (
    extra_mount.get("profile")
    or stack.get("extra_mount_profile")
    or (manifest.get("defaults") or {}).get("extra_mount_profile")
    or stack.get("storage_profile")
    or (manifest.get("defaults") or {}).get("storage_profile")
  )
  if not profile:
    return None
  profile_mapping = (manifest.get("extra_mount_profiles") or {}).get(profile) or {}
  return profile_mapping.get("storage")


docker_mount = data.get("docker_mount") or {}
if mount_path == "/var/lib/docker":
  declared_path = docker_mount.get("path", "/var/lib/docker")
  legacy_size = data.get("docker_storage_size")
  desired_size = docker_mount.get("size") or legacy_size
  control_plane = docker_mount.get("resize_control_plane", "provider")
  mutation_policy = docker_mount.get("mutation_policy", "grow-only")

  if declared_path != mount_path:
    raise SystemExit(f"stack intent path mismatch: requested {mount_path}, stack declares {declared_path}")
  if legacy_size and docker_mount.get("size") and str(legacy_size) != str(docker_mount["size"]):
    raise SystemExit(
      "stack intent mismatch: docker_mount.size must match legacy docker_storage_size while both are present"
    )
  if not desired_size:
    raise SystemExit("stack intent missing docker mount size")
  if control_plane != "operational":
    raise SystemExit(f"stack intent declares resize_control_plane={control_plane!r}, expected 'operational'")
  if mutation_policy != "grow-only":
    raise SystemExit(f"stack intent declares mutation_policy={mutation_policy!r}, expected 'grow-only'")
  print(f"resolved_mount_storage={''}")
else:
  extra_mount = data.get("extra_mount") or {}
  declared_path = extra_mount.get("path") or data.get("extra_mount_path")
  declared_size_canonical = extra_mount.get("size")
  declared_size_legacy = data.get("extra_mount_size")
  desired_size = declared_size_canonical or declared_size_legacy
  control_plane = extra_mount.get("resize_control_plane", "provider")
  mutation_policy = extra_mount.get("mutation_policy", "grow-only")
  resolved_storage = resolve_extra_mount_storage(data, manifest)

  if declared_path != mount_path:
    raise SystemExit(f"stack intent does not declare mount path {mount_path}")
  if declared_size_canonical and declared_size_legacy and str(declared_size_canonical) != str(declared_size_legacy):
    raise SystemExit("stack intent mismatch: extra_mount.size must match legacy extra_mount_size while both are present")
  if not desired_size:
    raise SystemExit(f"stack intent missing desired size for {mount_path}")
  if control_plane != "operational":
    raise SystemExit(f"stack intent declares resize_control_plane={control_plane!r}, expected 'operational'")
  if mutation_policy != "grow-only":
    raise SystemExit(f"stack intent declares mutation_policy={mutation_policy!r}, expected 'grow-only'")
  if not resolved_storage:
    raise SystemExit(f"could not resolve extra mount storage for {mount_path}")
  print(f"resolved_mount_storage={resolved_storage}")

print(f"desired_size={desired_size}")
PY
)"

printf '%s\n' "$intent_output"

resolved_mount_storage="$(printf '%s\n' "$intent_output" | awk -F= '/^resolved_mount_storage=/{print substr($0, index($0, "=") + 1)}')"

cmd=(ansible-playbook -i "$inventory_file" "$PLAYBOOK_FILE" -e "stack_yaml_path=${stack_yaml}" -e "resize_mount_path=${mount_path}")

if [[ -n "$resolved_mount_storage" ]]; then
  cmd+=(-e "resize_mount_storage=${resolved_mount_storage}")
fi

if [[ "$require_grow" == "true" ]]; then
  cmd+=(-e "resize_require_grow=true")
fi

if [[ "$allow_nonempty_target" == "true" ]]; then
  cmd+=(-e "resize_allow_nonempty_target=true")
fi

if [[ -n "${PVE_TEST_FQDN:-}" ]]; then
  cmd+=(-e "proxmox_delegate_host=${PVE_TEST_FQDN}")
fi

if [[ "$check_mode" == "true" ]]; then
  cmd+=(--check)
fi

log "Running operational mount workflow for stack=${stack_name} mount_path=${mount_path}"
ANSIBLE_CONFIG="${ANSIBLE_DIR}/ansible.cfg" \
ANSIBLE_ROLES_PATH="${ANSIBLE_DIR}/roles" \
"${cmd[@]}"
