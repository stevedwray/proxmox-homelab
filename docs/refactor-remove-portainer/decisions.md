# Decisions — Portainer Removal Refactor

These decisions are the binding contract for the Portainer-removal refactor.
If any task, prompt, or background document conflicts with a decision here,
stop and return to the architecture session.

## Decision 0: This package is the operational source of truth

`docs/refactor-remove-portainer/` is the active execution package for this
refactor.

- `README.md`, `decisions.md`, `task-sequence.md`, and `runbook.md` are the
  control documents.
- `tasks/` and `prompts/` define the atomic executor work units.
- `01-revised-architecture.md` and `02-terraform-ansible-separation.md` are
  background reference only.
- `03-refactor-plan.md` is a legacy draft and must not override this package.

## Decision 1: One task equals one branch/session

Each implementation task is intentionally atomic.

- One task per short-lived branch/session.
- Do not combine tasks unless the architecture session explicitly updates the
  sequence to do so.
- When validation exposes a new issue outside the current task boundary, stop
  and report it rather than widening scope.

## Decision 2: Portainer is app-tier only

Portainer stays in the homelab, but only as a management UI for Tier 2
application stacks.

Platform and infrastructure containers do not:

- install a Portainer agent
- register a Portainer endpoint
- deploy via the Portainer API

This applies to Harbor, Authentik, monitoring, proxy, NetBox, step-ca,
CoreDNS, apt-cacher-ng, CI runner, and the Portainer server itself.

## Decision 3: Terraform and Ansible are separate phases

Terraform provisions infrastructure. Ansible configures the inside of the LXC.
Neither phase invokes the other for LXC stack configuration.

Terraform still retains host-level Proxmox automation that is genuinely part of
infrastructure provisioning:

- `configure_network_sdn_attachment`
- `configure_keyctl`
- `prime_sdn_host_route`
- `configure_network_firewall`
- `configure_network_vnet_firewall`

Terraform removes the LXC playbook runner:

- `null_resource.ansible_provision`

## Decision 4: Generated inventory is the explicit handoff artifact

Terraform-generated `stacks/<stack>/inventory.yml` is the handoff from
provisioning to configuration.

It must carry the values Ansible orchestration needs, including:

- connection information
- shared host vars
- `ansible_playbook`

`scripts/provision.sh` consumes generated inventories rather than reading hidden
Terraform internals.

## Decision 5: `stack.yaml` is the single source of execution intent

`stack.yaml` remains canonical for stack identity, dependency metadata, and
orchestration intent.

For this refactor, the important orchestration fields are:

- `deployment_tier`
- `ansible_playbook`
- `depends_on`

The orchestration layer must derive behavior from stack metadata rather than
from hardcoded stack lists wherever practical. If current metadata cannot yet
express a required ordering or rule, the task must document that gap explicitly.

## Decision 6: `deployment_tier` must be explicit

Every active stack that participates in the new orchestration path must declare:

- `deployment_tier: platform`, or
- `deployment_tier: apps`

There are no silent defaults in the target model. Missing `deployment_tier` is
a configuration error for the orchestration layer.

## Decision 7: `direct_stack` is a limited replacement, not a forced rewrite

`direct_stack` exists to replace the Tier 1 use of `app_stack` where a direct
compose deployment abstraction is needed.

It is mandatory for:

- NetBox
- future simple platform stacks that fit the role

It is not mandatory for every existing platform playbook with bespoke logic.
Existing working playbook-specific logic may stay in place when that is the
lower-risk option.

## Decision 8: Tier 1 playbooks must actively suppress the agent service

The single-template model is retained. Tier 1 safety is enforced in playbooks,
not by maintaining two different LXC templates.

Every Tier 1 playbook must contain the standard mask task for
`portainer-agent.service`, including the playbooks that never used the
`portainer_agent` role directly:

- `deploy-harbor-stack.yml`
- `deploy-authentik-stack.yml`
- `deploy-monitoring-stack.yml`
- `deploy-proxy-stack.yml`
- `deploy-netbox-stack.yml`
- `deploy-portainer-stack.yml`
- `deploy-step-ca.yml`
- `deploy-coredns.yml`
- `deploy-apt-cacher-stack.yml`
- `deploy-ci-runner.yml`

The standard task is:

```yaml
- name: Mask portainer-agent service (platform tier — no agent on this host)
  ansible.builtin.systemd:
    name: portainer-agent.service
    masked: true
    enabled: false
  failed_when: false
```

## Decision 9: Platform bootstrap order is explicit and preserved

`scripts/provision.sh` must preserve the approved platform bootstrap order for
`pve-test`:

1. `portainer-stack`
2. `harbor-stack`
3. `apt-cacher-stack`
4. `ci-runner-01`
5. `dns-stack`
6. `step-ca-stack`
7. `authentik-stack`
8. `proxy-stack`
9. `monitoring-stack`
10. `netbox-stack`

Tasks may improve how this order is derived, but they must not silently change
the effective order without architecture approval.

## Decision 10: Validation and rebuild gates are shared, not ad hoc

Validation is part of the method, not an optional appendix.

- Every executor task runs the validation listed in its task document.
- Shared vocabulary, preflight expectations, rebuild checks, and rollback
  handling live in `runbook.md`.
- A task is not complete if it requires violating the runbook or skipping a
  declared stop condition.

## Decision 11: Final success is a full pve-test rebuild

The final gate for the refactor is not just unit validation or a clean plan.
The refactor is only proven when the package can support the documented
end-to-end `pve-test` rebuild flow:

1. destroy infrastructure
2. provision infrastructure
3. run platform configuration explicitly
4. validate platform services
5. confirm Portainer has no platform endpoints
6. re-run configuration and confirm idempotent behavior

## Decision 12: Baseline validation and downstream task validation are distinct

The refactor uses two different dry-plan gates for two different purposes.

- `scripts/validate-portainer-refactor-plan.sh` is the broader baseline helper
  introduced by Task 00a. It proves the shared `pve-test` planning baseline for
  the platform stacks plus `test-docker` and `test-lxc`, while excluding the
  root `terraform/lxc` unit and the legacy `net-*` validation stacks.
- `scripts/validate-portainer-refactor-platform-plan.sh` is the downstream
  task-complete helper introduced by Task 00b. It proves only the ten Tier 1
  platform stacks and intentionally excludes `test-docker` and `test-lxc` so
  downstream tasks are not blocked by legitimate create plans or absent
  apply-time artifacts.
- Task documents must name which helper they require. Executors should stop if
  a downstream task tries to reuse the broader baseline helper as a narrower
  task-complete gate.

## Decision 13: Downstream plan checks may allow orchestration-only null-resource churn

Before Task 08 removes `null_resource.ansible_provision`, some downstream
contract changes legitimately alter the generated inventory content that this
null resource tracks in its `triggers`.

- A task like Task 00 may therefore produce `local_file.ansible_inventory`
  content diffs plus `null_resource.ansible_provision` replacement plans that
  are driven only by `inventory_content`.
- Those diffs are orchestration-only churn, not LXC infrastructure changes, and
  should not block downstream validation by themselves.
- Downstream validation must still stop on any actual LXC infrastructure drift,
  unexpected null-resource behavior beyond the documented orchestration churn,
  or interactive validation paths that prevent a clean non-interactive dry run.
- Shared helper scripts for downstream validation must run non-interactively.
