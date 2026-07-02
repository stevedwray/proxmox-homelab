# Teardown/Deploy Test Plan

This directory is the current source of truth for the controlled
`pve-test-vm` teardown/deploy rehearsal after the stack-owned edge refactor.

The purpose is simple: prove the platform can be destroyed and rebuilt from
repository state, in the documented order, without hidden second-pass behavior
or manual drift.

## What This Covers

- destructive rebuild planning for `pve-test-vm`
- stack order, rollback gates, and operator approvals
- reusable harness guidance for preflight, live validation, and full cycle runs
- durable lessons learned from rehearsal passes

Production `pve` is out of scope.

## Current Position

- the harness remains an active part of repo workflow
- historical rehearsal cycles completed successfully, including the 2026-06-13
  `pve-test-vm` cycle
- durable takeaways belong in tracked docs such as
  [lessons-learned.md](lessons-learned.md), not raw evidence

## Safety Rules

- confirm the target before any deploy, destroy, or validation step:

  ```bash
  PVE_ENV=pve-test-vm ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
  ```

- do not proceed unless the command returns `pve-test-vm`
- require explicit backup verification and operator approval before destructive work
- run from a clean working tree and known commit
- regenerate ignored `.generated/` edge artifacts immediately before publish
- stop on any failed target guard, failed backup, failed restore dry-run, failed
  edge preflight, or unexpected production target

## Default Stack Scope

The normal rehearsal scope is:

- `portainer-stack`
- `harbor-stack`
- `apt-cacher-stack`
- `ci-runner-01`
- `dns-stack`
- `proxy-stack`
- `step-ca-stack`
- `authentik-stack`
- `monitoring-stack`
- `netbox-stack`

Disposable test stacks and `.hold/` stacks are out of scope unless explicitly
enabled in [variables.md](variables.md).

## Read In This Order

1. [variables.md](variables.md)
2. [decisions.md](decisions.md)
3. [task-sequence.md](task-sequence.md)
4. [operations-plan.md](operations-plan.md)
5. [runbook.md](runbook.md)
6. [repeatable-test.md](repeatable-test.md)
7. [lessons-learned.md](lessons-learned.md)

## File Roles

- [variables.md](variables.md): destructive-gate answers and execution metadata
- [task-sequence.md](task-sequence.md): atomic test plan index
- [operations-plan.md](operations-plan.md): stack order and execution components
- [runbook.md](runbook.md): operator command flow
- [repeatable-test.md](repeatable-test.md): reusable harness behavior
- [harness-roadmap.md](harness-roadmap.md): remaining harness hardening work
- [lessons-learned.md](lessons-learned.md): durable findings only

## Agent Use

1. Read this README, [variables.md](variables.md), and [decisions.md](decisions.md).
2. Use [operations-plan.md](operations-plan.md) to find the next atomic component.
3. Open the matching task in [tasks/](tasks/).
4. Stop at destructive gates unless the task explicitly includes approved execution.

## Workflow Note

Branch and promotion rules live in:

- [docs/workflow/branch-model.md](../workflow/branch-model.md)
- [docs/workflow/environments.md](../workflow/environments.md)
