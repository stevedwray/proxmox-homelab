# Task 09: Create `scripts/provision.sh`

## Type

Development

## Objective

Create the Ansible orchestration script that replaces `null_resource.ansible_provision`
as the mechanism for running playbooks after `terragrunt apply`. It reads the generated
`inventory.yml` files that Terraform produces and runs each stack's playbook in
dependency order: platform stacks first, then app stacks.

This task should follow the same contract-driven method used in
`docs/provisioning-refactor/`: derive orchestration intent from declared
metadata where possible, fail clearly on ambiguity, and keep apply behavior
explicit.

## Files

- `scripts/provision.sh` (create)

## Preconditions

- Task 00 complete — `inventory.tpl` renders `ansible_playbook`.
- Task 07 complete — active stacks now declare `deployment_tier`.
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

The `ansible_playbook` field is a host var in the generated inventory (after
Task 00). Because `yq` is not guaranteed to be present in the execution
environment, use `python3` to extract it. The inventory structure (from
`inventory.tpl`) nests the host under `all.children.<stack_name>.hosts.<hostname>`.
The corresponding Python3 one-liner is:

```bash
python3 -c "
import yaml, sys
inv = yaml.safe_load(sys.stdin)
grp = next(iter(inv['all']['children'].values()))
host = next(iter(grp['hosts'].values()))
print(host.get('ansible_playbook', ''))
" < inventory.yml
```

Verify the output against a real generated inventory before writing the final script.
`python3` with the `yaml` module is available in this environment; `yq` is not
required.

`stack.yaml` remains the source of execution intent. The script should discover
candidate stacks from `terraform/lxc/stacks/*/stack.yaml`, use
`deployment_tier` to filter platform vs apps, and use `depends_on` plus the
documented platform bootstrap order from `decisions.md` to preserve the current
approved sequence.

## Operations

1. Read an existing generated inventory file (e.g.
   `terraform/lxc/stacks/harbor-stack/inventory.yml`) to confirm:
   - Where `ansible_playbook` appears as a host var (confirm Task 00 is reflected)
   - The Python3 extraction path produces the expected value

2. Examine `terraform/lxc/main.tf` git log or the removed local-exec block to
   confirm the exact `ansible_dir`, `ansible_cfg`, `ansible_roles_path` values that
   were used.

3. Create `scripts/provision.sh`.

   Required behavior:
   - discover stack directories from `terraform/lxc/stacks/`
   - read `deployment_tier` and `depends_on` from `stack.yaml`
   - read `ansible_playbook` from generated `inventory.yml`
   - support `--tier`, `--stack`, and `--check`
   - skip stacks with no inventory or no `ansible_playbook`
   - preserve the approved current platform bootstrap order from `decisions.md`
     for `pve-test`
   - fail clearly if the discovered metadata cannot produce a valid order

4. If the actual Python3 path to `ansible_playbook` returns an unexpected result
   against the real inventory, correct the extraction expression and document
   the actual inventory structure in the script comments.

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
- Script outputs a SKIP message for a stack with no `ansible_playbook` in
  inventory and continues.
- Script derives target stacks from stack metadata rather than from a stale
  hardcoded list.
- `stack_apply` in `scripts/teardown-deploy-test.sh` calls `provision.sh --stack <stack>`
  after `terragrunt apply`.

## Validation

```bash
shellcheck scripts/provision.sh

# Test skip behaviour on a stack with no ansible_playbook
./with-secrets ./scripts/provision.sh --check --stack test-lxc
# Expected: "SKIP test-lxc: no ansible_playbook in inventory" (if inventory exists)

# Test against a real stack if pve-test is up
./with-secrets ./scripts/provision.sh --check --stack harbor-stack

grep -A12 "^stack_apply" scripts/teardown-deploy-test.sh | grep "provision.sh"
# Expected: provision.sh appears in the stack_apply function body
```

## Stop Conditions

- Stop if `ansible_playbook` is not present in the generated inventory.yml even after
  Task 00 — report the inventory structure and the `inventory.tpl` content.
- Stop if the orchestration logic requires a hardcoded stack list that cannot be
  justified from current stack metadata and `decisions.md` — report the gap
  rather than hardcoding silently.
- Stop if the Python3 expression to extract `ansible_playbook` returns the wrong
  value or errors against a real generated inventory — report the inventory
  structure and the Python3 version (`python3 --version`).
- Stop if `shellcheck` reports errors — fix them before reporting completion.
