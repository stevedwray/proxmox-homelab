# Teardown/Deploy Test Plan

This directory is the source of truth for planning and executing a controlled
`pve-test` teardown/deploy rehearsal after the stack-owned edge provisioning
refactor.

The goal is to prove that the platform can be destroyed and rebuilt from source
in the documented Mode 2 order, including CoreDNS, Traefik, Authentik, and the
stack-owned edge reconciliation path.

This is not a casual validation cycle. It is a destructive platform rehearsal.
Do not execute teardown or deploy commands until the variables in
[variables.md](variables.md) are answered, backups are verified, and the
operator has explicitly approved the destructive window.

## Target Outcome

At the end of the test:

- `pve-test` is rebuilt from repository state.
- All selected platform LXCs are running at their expected VMIDs and IPs.
- Stage 3a edge foundation is rebuilt without hidden Terraform second-pass
  behavior.
- Generated CoreDNS and Traefik state is regenerated from current manifests and
  published from fresh artifacts.
- Authentik discovery/reconciliation is converged without automatic deletes.
- All six browser routes resolve to Traefik at `10.57.2.10` and show expected
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

Production `pve` is out of scope.

## Safety Rules

- The target guard must return exactly `pve-test` before any apply, destroy, or
  deployment validation command:

  ```bash
  ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
  ```

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
- [runbook.md](runbook.md) contains the operator command flow.
- [tasks/](tasks/) contains detailed task documents.
- [prompts/](prompts/) contains matching AI-agent prompts.
- [prompts/index.yaml](prompts/index.yaml) is the ordered prompt registry.

## How Agents Should Use This

1. Read this README, [decisions.md](decisions.md), and
   [variables.md](variables.md).
2. Select exactly one task from [task-sequence.md](task-sequence.md).
3. Use the matching prompt from [prompts/index.yaml](prompts/index.yaml).
4. Keep changes inside that task's declared scope.
5. Stop when a task reaches a destructive gate unless the task explicitly
   includes operator-approved execution.
