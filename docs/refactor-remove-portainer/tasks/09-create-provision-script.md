# Task 09: Create `scripts/provision.sh`

## Type

Development

## Objective

Create the Ansible orchestration script that replaces `null_resource.ansible_provision`
as the mechanism for running playbooks after `terragrunt apply`. It reads the generated
`inventory.yml` files that Terraform produces and runs each stack's playbook in
dependency order: platform stacks first, then app stacks.

## Files

- `scripts/provision.sh` (create)

## Preconditions

- Task 00 complete — `inventory.tpl` renders `ansible_playbook`.
- Task 08 complete — Terraform no longer invokes Ansible for stack configuration.
- At least one stack with `ansible_playbook` set in `stack.yaml` has had
  `terragrunt apply` run so a real `inventory.yml` exists to test against.

## Background

The script must replicate the environment that `null_resource.ansible_provision`
provided. From `terraform/lxc/main.tf`, the removed local-exec set:
```
ANSIBLE_HOST_KEY_CHECKING    = "False"
ANSIBLE_CONFIG               = local.ansible_cfg          (terraform/lxc/ansible/ansible.cfg)
ANSIBLE_ROLES_PATH           = local.ansible_roles_path   (terraform/lxc/ansible/roles)
ANSIBLE_LOCAL_TEMP           = "/tmp/.ansible/tmp"
ANSIBLE_SSH_CONTROL_PATH_DIR = "/tmp/.ansible/cp"
```

The `ansible_playbook` field is a host var in the generated inventory (after Task 00).
The yq path to read it is:
`.all.children | to_entries | .[0].value.hosts | to_entries | .[0].value.ansible_playbook // ""`

This path handles the inventory structure where the host group name is the stack name
with hyphens replaced by underscores and the hostname is the container hostname.
Verify the path against a real inventory before writing the final script.

Platform stack order (from decisions.md Decision 7):
```
portainer-stack, harbor-stack, apt-cacher-stack, ci-runner-01,
dns-stack, step-ca-stack, authentik-stack, proxy-stack,
monitoring-stack, netbox-stack
```

## Operations

1. Read an existing generated inventory file (e.g.
   `terraform/lxc/stacks/harbor-stack/inventory.yml`) to confirm:
   - Where `ansible_playbook` appears as a host var (confirm Task 00 is reflected)
   - The exact yq path needed to extract it

2. Examine `terraform/lxc/main.tf` git log or the removed local-exec block to
   confirm the exact `ansible_dir`, `ansible_cfg`, `ansible_roles_path` values that
   were used.

3. Create `scripts/provision.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
ANSIBLE_DIR="${REPO_ROOT}/terraform/lxc/ansible"
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"

TIER="all"
TARGET_STACK=""
CHECK_MODE=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --tier)  TIER="$2";         shift 2 ;;
    --stack) TARGET_STACK="$2"; shift 2 ;;
    --check) CHECK_MODE="--check"; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

run_playbook() {
  local stack_dir="$1"
  local stack_name
  stack_name="$(basename "${stack_dir}")"
  local inventory="${stack_dir}/inventory.yml"

  if [[ ! -f "${inventory}" ]]; then
    echo "SKIP ${stack_name}: no inventory.yml (run terragrunt apply first)"
    return 0
  fi

  # Extract ansible_playbook from the generated inventory host vars.
  # Adjust the yq path here if the inventory structure differs.
  local playbook
  playbook="$(yq '.all.children | to_entries | .[0].value.hosts | to_entries | .[0].value.ansible_playbook // ""' \
    "${inventory}" 2>/dev/null || true)"

  if [[ -z "${playbook}" ]]; then
    echo "SKIP ${stack_name}: no ansible_playbook in inventory"
    return 0
  fi

  echo "--- Provisioning ${stack_name} (playbook: ${playbook}) ---"
  ANSIBLE_HOST_KEY_CHECKING=False \
  ANSIBLE_CONFIG="${ANSIBLE_DIR}/ansible.cfg" \
  ANSIBLE_ROLES_PATH="${ANSIBLE_DIR}/roles" \
  ANSIBLE_LOCAL_TEMP="/tmp/.ansible/tmp" \
  ANSIBLE_SSH_CONTROL_PATH_DIR="/tmp/.ansible/cp" \
    ansible-playbook ${CHECK_MODE} \
      -i "${inventory}" \
      "${ANSIBLE_DIR}/playbooks/${playbook}.yml"
}

PLATFORM_STACKS=(
  portainer-stack
  harbor-stack
  apt-cacher-stack
  ci-runner-01
  dns-stack
  step-ca-stack
  authentik-stack
  proxy-stack
  monitoring-stack
  netbox-stack
)

APP_STACKS=(
  pihole-stack
  arr-stack
  jellyfin-stack
  game-stack
)

if [[ -n "${TARGET_STACK}" ]]; then
  run_playbook "${STACKS_DIR}/${TARGET_STACK}"
  exit 0
fi

if [[ "${TIER}" == "platform" || "${TIER}" == "all" ]]; then
  for stack in "${PLATFORM_STACKS[@]}"; do
    [[ -d "${STACKS_DIR}/${stack}" ]] && run_playbook "${STACKS_DIR}/${stack}"
  done
fi

if [[ "${TIER}" == "apps" || "${TIER}" == "all" ]]; then
  for stack in "${APP_STACKS[@]}"; do
    [[ -d "${STACKS_DIR}/${stack}" ]] && run_playbook "${STACKS_DIR}/${stack}"
  done
fi
```

4. If the actual `yq` path to `ansible_playbook` differs from what is shown in step 3,
   use the correct path.

5. Make the script executable: `chmod +x scripts/provision.sh`

6. Run `shellcheck scripts/provision.sh`.

7. Test with:
   ```bash
   ./with-secrets ./scripts/provision.sh --check --stack harbor-stack
   ```

8. Update `stack_apply` in the teardown-test harness to call `provision.sh` after
   `terragrunt apply`. In `scripts/teardown-deploy-test.sh`, find `stack_apply()`
   (at line 956). After the `run_logged "deploy-${stack}"` terragrunt apply block
   and before `validate_stack_smoke "${spec}"`, insert:

   ```bash
   guard_pve_test
   run_logged "provision-${stack}" \
     "${WITH_SECRETS}" "${REPO_ROOT}/scripts/provision.sh" --stack "${stack}"
   ```

   `WITH_SECRETS` is at line 19 (`"${REPO_ROOT}/with-secrets"`), `REPO_ROOT` at line 18.
   This ensures every `deploy-foundation`, `deploy-edge`, and `deploy-platform` phase
   runs Ansible after Terraform. Stacks with no `ansible_playbook` emit a SKIP and
   continue without error.

## Postconditions

- `shellcheck scripts/provision.sh` passes with no errors or warnings.
- `./with-secrets ./scripts/provision.sh --check --stack harbor-stack` exits 0
  (or non-zero only due to a real Ansible finding, not a script error).
- Script outputs a SKIP message for a stack with no inventory.yml and continues.
- Script outputs a SKIP message for a stack with no `ansible_playbook` in inventory
  and continues.
- `stack_apply` in `scripts/teardown-deploy-test.sh` calls `provision.sh --stack <stack>`
  after `terragrunt apply`.

## Validation

```bash
shellcheck scripts/provision.sh

# Test skip behaviour on a stack with no ansible_playbook
./with-secrets ./scripts/provision.sh --check --stack apt-cacher-stack
# Expected: "SKIP apt-cacher-stack: no ansible_playbook in inventory"

# Test against a real stack if pve-test is up
./with-secrets ./scripts/provision.sh --check --stack harbor-stack

grep -A12 "^stack_apply" scripts/teardown-deploy-test.sh | grep "provision.sh"
# Expected: provision.sh appears in the stack_apply function body
```

## Stop Conditions

- Stop if `ansible_playbook` is not present in the generated inventory.yml even after
  Task 00 — report the inventory structure and the `inventory.tpl` content.
- Stop if the yq expression to extract `ansible_playbook` returns the wrong value or
  errors — report the inventory structure and the yq version (`yq --version`).
- Stop if `shellcheck` reports errors — fix them before reporting completion.
