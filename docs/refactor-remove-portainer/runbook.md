# Portainer Removal Validation Runbook

This runbook is the shared validation, rebuild, and rollback contract for the
Portainer-removal refactor.

All executor sessions should use the same vocabulary and validation style when
reporting progress or stop conditions.

## Scope and Safety

- Scope is `pve-test` only.
- Prefer source-only and dry validation before any live mutation.
- Do not widen task scope because a validation command surfaced an unrelated
  issue.
- If a validation step would require a risky live action outside the task
  boundary, stop and return options to the architecture session.

## Shared Vocabulary

Use these terms consistently in task notes and handoff:

- Preflight: target and environment checks before task validation.
- Source-only validation: checks that inspect code, docs, plans, lint, or unit
  tests without mutating live systems.
- Task-complete validation: the task-specific commands that prove the scoped
  change works.
- Rebuild gate: the final full `pve-test` destroy/apply/provision sequence.
- No-op: a second explicit configuration run that reports no meaningful changes.
- Stop condition: a documented condition that pauses execution and returns
  control to the architecture session.
- Rollback: restoring the previous known-good implementation path or backing out
  the incomplete task branch.

## 1. Preflight

Run from repository root for any task that touches provisioning behavior,
validation harnesses, or live `pve-test` instructions:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

Expected outcome:

- output is exactly `pve-test`

Stop condition:

- any other output

## 2. Shared Source-Only Validation

Use the task document as the source of truth for exact commands, but the common
patterns are:

- `./scripts/validate-portainer-refactor-plan.sh` for the broader `00a`
  baseline dry-plan proof
- `./scripts/validate-portainer-refactor-platform-plan.sh` for downstream
  platform-refactor task-complete dry-plan checks
  Before Task 08 removes `null_resource.ansible_provision`, downstream checks
  may allow orchestration-only null-resource churn that is driven by inventory
  content changes, but they must still reject any actual LXC infrastructure
  drift and must run non-interactively.
- `terraform fmt -check` for Terraform edits
- `ansible-lint` for playbook or role edits
  Run it from `terraform/lxc/ansible/` so local roles resolve via the repo's
  `ansible.cfg`.
- `shellcheck` for shell-script edits
- `python3 -m unittest ...` for added regression tests
- `rg`/`grep` assertions for removed Portainer references or required mask tasks
- documentation consistency checks after doc-only tasks

Expected outcome:

- only the diffs described by the task appear
- no unrelated LXC infrastructure changes appear in Terraform plans
- documented orchestration-only null-resource churn is acceptable only when the
  task doc explicitly allows it
- lint and unit checks pass

Stop condition:

- validation reveals a wider architectural inconsistency not already covered by
  the task

## 3. Task Class Guidance

### Documentation tasks

Expected validation:

- internal references resolve
- source-of-truth ordering is clear
- no doc still claims Terraform invokes Ansible for LXC configuration once the
  separation tasks are complete

### Playbook migration tasks

Expected validation:

- required Portainer role calls are removed or retained exactly as the task says
- the standard Tier 1 service mask is present where required
- `ansible-lint` passes for the edited playbook

### Orchestration-boundary tasks

Expected validation:

- generated inventory still carries required orchestration metadata
- `null_resource.ansible_provision` is removed only when all dependent playbooks
  are ready
- `scripts/provision.sh` passes lint and uses the documented orchestration
  contract

## 4. Final Rebuild Gate

After all implementation tasks are complete, validate the full explicit
two-phase flow:

Use the stack-only Terragrunt entrypoint. Do not run repo-root all-units
commands against `terraform/lxc`, because the root unit requires
`stack_name` and `stack_yaml_path` and is not the rebuild-gate target.
For `terragrunt run --all`, pass OpenTofu/Terraform flags after `--` so they
are forwarded to the underlying command.

```bash
# 1. Destroy all LXCs
./with-secrets terragrunt --working-dir terraform/lxc/stacks --non-interactive run --all -- destroy -auto-approve

# 2. Provision infrastructure
./with-secrets terragrunt --working-dir terraform/lxc/stacks --non-interactive run --all -- apply -auto-approve

# 3. Configure platform tier explicitly
./with-secrets ./scripts/provision.sh --tier platform

# 4. Smoke test platform services
curl -skf https://10.57.3.10/api/v2.0/ping
curl -skf https://10.57.1.11/health
curl -skf https://10.57.2.10/ping

# 5. Confirm Portainer has no platform agent endpoints
./with-secrets bash -lc '
  token="$(
    curl -fsS http://10.57.1.20:9000/api/auth \
      -H "Content-Type: application/json" \
      -d "{\"Username\":\"admin\",\"Password\":\"${PORTAINER_ADMIN_PASSWORD}\"}" |
    python3 -c "import json,sys; print(json.load(sys.stdin)[\"jwt\"])"
  )"
  curl -fsS http://10.57.1.20:9000/api/endpoints \
    -H "Authorization: Bearer ${token}" |
  python3 -c "
import json, sys
platform = {
    'portainer-stack',
    'harbor-stack',
    'apt-cacher-stack',
    'ci-runner-01',
    'dns-stack',
    'step-ca-stack',
    'authentik-stack',
    'proxy-stack',
    'monitoring-stack',
    'netbox-stack',
}
names = {item.get('Name', '') for item in json.load(sys.stdin)}
unexpected = sorted(name for name in names if name in platform)
if unexpected:
    raise SystemExit('platform endpoints still registered: ' + ', '.join(unexpected))
print('no platform endpoints registered')
"
'

# 6. Re-run platform configuration to confirm idempotent behavior
./with-secrets ./scripts/provision.sh --tier platform
```

Expected outcome:

- infrastructure provisions successfully
- destroy/apply run non-interactively from `terraform/lxc/stacks`
- platform playbooks configure the expected stacks
- Harbor, step-ca, and Traefik smoke tests pass
- Portainer contains no platform agent endpoints after platform provisioning
- the second `provision.sh --tier platform` run is effectively a no-op

Stop condition:

- any platform stack still depends on Portainer to deploy
- any Tier 1 playbook starts or re-enables the agent service
- the second provision run reports unresolved drift caused by the refactor

## 5. Rollback Guidance

If a task fails after partial implementation:

- do not invent a wider remediation inside the same task
- restore the previous branch state or back out the incomplete task branch
- report the failing validation step, file, and stop condition to the
  architecture session

If the full rebuild gate fails:

- treat the refactor as incomplete
- do not merge the implementation sequence as complete
- record the exact failing stack, command, and observed behavior before opening
  the next architecture iteration
