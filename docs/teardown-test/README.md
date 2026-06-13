# Teardown/Deploy Test Plan

This directory is the source of truth for planning, executing, and repeating a
controlled `pve-test` teardown/deploy rehearsal after the stack-owned edge
provisioning refactor.

The goal is to prove that the platform can be destroyed and rebuilt from source
in the documented Mode 2 order, including CoreDNS, Traefik, Authentik, and the
stack-owned edge reconciliation path.

This is not a casual validation cycle. It is a destructive platform rehearsal.
Do not execute teardown or deploy commands until the variables in
[variables.md](variables.md) are answered, backups are verified, and the
operator has explicitly approved the destructive window.

## Current Status

On `baseline/teardown-validated` (commit `f4d1f25`).

Two full teardown/rebuild cycles have completed successfully:

- Initial rehearsal (2026-04-22): [artifacts/reports/20260422-044416.md](artifacts/reports/20260422-044416.md)
- Storage-refactor gate (2026-05-17): [artifacts/reports/20260517-033905-storage-refactor-gate.md](artifacts/reports/20260517-033905-storage-refactor-gate.md)
- Multi-source inventory gate (2026-06-13): [artifacts/reports/20260613-pve-test-vm-teardown.md](artifacts/reports/20260613-pve-test-vm-teardown.md)

The June 2026 cycle was run against **pve-test-vm** (`192.168.1.41`), a
VM-hosted Proxmox instance that replaced the retired bare-metal `pve-test`
laptop. All cold-start failures discovered during that cycle were fixed in the
same branch and merged. Durable takeaways are in [lessons-learned.md](lessons-learned.md).

The repeatable harness is documented in [repeatable-test.md](repeatable-test.md)
and implemented at `scripts/teardown-deploy-test.sh`.

**Next action:** cut `fix/ci-pipeline-cleanup` from `baseline/teardown-validated`
and work through CI pipeline items (workflow trigger cleanup, ShellCheck
directives, Harbor image policy, Ansible lint). No teardown gate required for
that branch.

The harness is safe by default: non-destructive validation phases can run during
development, while destroy/apply/publish phases require explicit execution
approval.

## Target Outcome

At the end of the test:

- `pve-test` is rebuilt from repository state.
- All selected platform LXCs are running at their expected VMIDs and IPs.
- Stage 3a edge foundation is rebuilt without hidden Terraform second-pass
  behavior.
- Generated CoreDNS and Traefik state is regenerated from current manifests and
  published from fresh artifacts.
- Authentik discovery/reconciliation is converged without automatic deletes.
- All six browser routes resolve to Traefik at `${lab_ip_proxy}` and show expected
  auth behavior.
- The final edge reconciler dry-run is a no-op.
- Destroy, deploy, validation, and rollback evidence are captured.

## Scope

Default scope is pve-test only.

The default platform stack set is:

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

Disposable network validation stacks, `test-*` stacks, and `.hold/` stacks are
out of scope unless explicitly enabled in [variables.md](variables.md).
`headscale-stack` currently has inventory/state but no active `stack.yaml`; it
is out of scope until it is restored as an active stack or explicitly cleaned up.

Production `pve` is out of scope.

## Safety Rules

- The target guard must confirm the expected non-production node before any
  apply, destroy, or deployment validation command. The active test target is
  `pve-test-vm`; set `PVE_ENV=pve-test-vm` and confirm with:

  ```bash
  PVE_ENV=pve-test-vm ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
  ```

  Any result other than the intended non-production node must stop execution.

- Teardown requires explicit human approval after backups are verified.
- Run from a clean working tree and a known commit.
- Regenerate ignored `.generated/` edge artifacts immediately before publish.
- Do not trust existing ignored `.generated/` files from previous sessions.
- Stop on any failed backup, failed target guard, failed restore dry-run, failed
  edge preflight, or unexpected production target.

## Files

- [decisions.md](decisions.md) records decisions that govern the test.
- [variables.md](variables.md) lists answers required before execution.
- [task-sequence.md](task-sequence.md) lists the atomic test plan.
- [operations-plan.md](operations-plan.md) breaks the test into single-stack
  and single-handoff execution components with file touch sets.
- [lessons-learned.md](lessons-learned.md) captures durable findings that
  should stay current as the rehearsal process evolves.
- [repeatable-test.md](repeatable-test.md) describes the reusable harness for
  repeated preflight, live validation, and approved teardown/deploy cycles.
- [harness-roadmap.md](harness-roadmap.md) lists the remaining work needed to
  turn the current harness prototype into a robust reusable playbook.
- [runbook.md](runbook.md) contains the operator command flow.
- [tasks/](tasks/) contains detailed task documents.
- [prompts/](prompts/) contains matching AI-agent prompts.
- [prompts/index.yaml](prompts/index.yaml) is the ordered prompt registry.

## How Agents Should Use This

1. Read this README, [decisions.md](decisions.md), and
   [variables.md](variables.md).
2. Use [operations-plan.md](operations-plan.md) to identify the next atomic
   component and its allowed file touch set.
3. Select the matching task from [task-sequence.md](task-sequence.md).
4. Use the matching prompt from [prompts/index.yaml](prompts/index.yaml).
5. Keep changes inside that task's declared scope.
6. Stop when a task reaches a destructive gate unless the task explicitly
   includes operator-approved execution.
