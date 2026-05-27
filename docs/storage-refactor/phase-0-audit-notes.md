# Storage Refactor Phase 0 Audit Notes

Date: 2026-05-27

## Current Source Baseline

 - `terraform/lxc/stacks/test-storage/` exists in this branch as a tracked
   dedicated storage-validation stack. During this Phase 0 pass I executed a
   targeted provider-backed plan non-interactively using the repository's
   `with-secrets` wrapper and a `terragrunt plan` invocation. The run produced
   an OpenTofu/Terraform plan which was converted to machine-readable JSON for
   classification (see classifier output noted below). This verifies the
   stack is usable as a Phase 0 proof target and provides real provider-backed
   evidence for the remaining proof gap.
- The current LXC module still uses the pre-refactor storage shape:
  - one root disk
  - one fixed `mount_point` at `/var/lib/docker`
  - one optional extra `mount_point`
- `terraform/lxc/storage/pve-test.yaml` is still a backend/profile resolution
  manifest. It does not yet model:
  - persistent mount logical identity
  - backup policy
  - backup exceptions
  - mutation policy
  Note: The Phase 1 `mount_contracts` block previously present in
  `pve-test.yaml` has been intentionally isolated into
  `terraform/lxc/storage/pve-test.phase1.yaml` to avoid mixing Phase 1 schema
  work into Phase 0 audits. The `validate-storage-schema.py` tool is a Phase 1
  schema checker and should not be used as part of Phase 0 capability checks.
- `docs/teardown-test/inventory.md` already excludes `test-docker` and
  `test-lxc`, so a dedicated storage-validation stack can stay out of the broad
  teardown/redeploy gate by inventory choice rather than new harness code.

## Current Stack Shapes

### Docker-only shape

Representative stacks with `/var/lib/docker` storage but no extra mount:

- `authentik-stack`
- `monitoring-stack`
- `netbox-stack`
- `portainer-stack`
- `apt-cacher-stack`
- `ci-runner-01`

Validation-only examples also follow this shape:

- `test-docker`
- `test-lxc`
- `net-*` validation stacks

### Docker-plus-extra-mount shape

The only tracked stacks currently using the module's optional extra mount are:

- `harbor-stack`
  - extra mount path: `/var/lib/harbor`
  - extra mount size: `100G`
- `proxy-stack`
  - extra mount path: `/opt/proxy-stack/certs`
  - extra mount size: `5G`

### Direct/rootfs no-op validation targets

These are still normal LXC stacks under the same module path, but they are the
best representative "do not regress non-Docker behavior" checks named in the
plan:

- `dns-stack`
- `step-ca-stack`

## Network / Validation-Target Notes

- `test-docker` and `test-lxc` are legacy bridge-path stacks with no
  `network.zone`.
- Real platform stacks use named zones such as `mgmt_seg`, `edge_seg`,
  `infra_seg`, and `build_seg`.
- `build_seg` is already a normal tracked zone in `terraform/lxc/network/pve-test.yaml`.
- `net-build-01` is the closest existing example of a small tracked stack using
  `network.zone: build_seg`.

Implication:

- `test-storage` is present as a tracked stack under
  `terraform/lxc/stacks/test-storage/` and already uses `network.zone: build_seg`.
  It does not reuse the legacy `lan` path from `test-docker` or `test-lxc`.

## Scope clarifications for this pass

- CPU and memory field transitions (for example, scaling CPU cores or RAM)
  are explicitly treated as out-of-scope for the storage-classifier work in
  this branch's Phase 0 pass. The classifier and Phase 0 capability checks in
  this pass focus on storage-related field transitions only (rootfs and
  mount_point related changes). This narrowing preserves Phase 0's goal of
  producing provider-backed evidence for storage mutation behavior without
  expanding into unrelated compute-change validation.

- The Phase 0 authoritative claims have been reconciled against available
  provider-backed evidence from `test-storage` runs. In particular, no
  provider-backed `terragrunt plan` proving an in-place `rootfs_size` increase
  was produced in this pass; therefore the matrix claim that previously
  labeled `rootfs_size: increase` as `authoritative` has been downgraded to a
  conservative policy mapping in `docs/storage-refactor/capability-matrix.md`.
  That row will be re-authoritatively upgraded only if a provider-backed
  non-replacing plan for `rootfs_size` growth is captured and attached to the
  hand-back.

## Concrete Path-Masking Risk Cases

Source-level evidence already shows two existing persistent extra-mount paths
that must not be treated as anonymous disposable storage:

- `harbor-stack`:
  - `/var/lib/harbor` holds registry blobs, PostgreSQL data, Redis data, and
    the Trivy cache
- `proxy-stack`:
  - `/opt/proxy-stack/certs` holds ACME state and the combined CA bundle

Implication:

- first-extra-mount introduction on a Docker-only stack must check for
  mount-over-existing-data risk before apply
- path changes for an existing extra mount are conservatively `blocked` in
  Phase 0 (rationale: risk of data-masking and provider delete/create semantics;
  Phase 0 lacks provider-backed in-place evidence)

## Guardrail / Workflow Implications

- The broad teardown harness is inventory-driven, not stack-directory-driven.
- `test-storage` can stay out of normal destroy/deploy gates by remaining out
  of `docs/teardown-test/inventory.md` unless a specific validation pass opts in
  to it.
- No special-case Terraform code path is needed just to exclude the dedicated
  storage-validation stack from the broad gate.

## Recommended Next Copilot Pass

Use `docs/storage-refactor/copilot-followup-prompt.md` for Phase 0 follow-up and targeted proof attempts.

What I did in this pass:

- Created the baseline `test-storage` state on `pve-test` (disposable workflow) by
  applying the saved plan under `./with-secrets`.
- Ran targeted mutation plans (provider-backed) and classified them with the
  Phase 0 classifier (tooling present at `terraform/lxc/classify-storage-plan.py`).
  - Docker data mount growth (8G -> 16G): provider plan required a replace
    of the `proxmox_virtual_environment_container` resource — classifier: `replacement-sensitive`.
  - First extra-mount introduction (none -> `/var/lib/extra` 100G): classifier: `blocked`.

Remaining, concrete next step for Phase 0:

1. Based on the above results, the immediate Phase 0 follow-up is:
   - If the goal is to prove safe in-place growth, attempt a controlled test
     that exercises an implementation path known to support in-place expansion
     (different storage backend or provider feature) and produce a provider
     plan that shows a non-replacing size increase. Classify that plan as
     evidence.
   - Otherwise, document the replacement-sensitive and blocked transitions
     as gating policy for Phase 1 contract work (do not attempt schema changes
     in this pass).

Notes:

- Do not mix Phase 1 schema/contract work into this pass. Keep
  `terraform/lxc/storage/pve-test.phase1.yaml` isolated.
- Keep transient artifacts (machine plan JSON, classifier output) out of
  tracked `docs/` paths: write classifier output to `/tmp` or the local
  ephemeral workspace and include its summary in the audit note (as above).

## Phase 0 conclusion: backup-behavior requirement

- Observation: the current `terraform/lxc/storage/pve-test.yaml` manifest does
  not express per-mount backup intent, and the provider/module path does not
  expose an explicit backup inclusion control today. That means the provider
  will not automatically include or exclude persistent mounts from backup
  policies without additional intent metadata.
- Requirement for Phase 1: Phase 1 must make backup behavior explicit for each
  persistent mount in the contract. Concretely, Phase 1 must require a
  per-mount `backup_policy` (for example `include`, `exclude`, or
  `unsupported: <reason>`) and must document whether the implementation will
  attempt Terraform-managed backups, rely on an external PBS policy, or treat
  backup handling as an explicit unsupported exception with a reasoning field.
  This requirement is necessary because the current provider/module path does
  not encode backup intent.
