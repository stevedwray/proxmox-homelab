# Storage Refactor Phase 0 Audit Notes

Date: 2026-05-27

## Current Source Baseline

- `terraform/lxc/stacks/test-storage/` does not exist yet.
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

- `test-storage` should be a normal tracked stack under
  `terraform/lxc/stacks/test-storage/`
- it should use `network.zone: build_seg`
- it should not reuse the legacy `lan` path from `test-docker` or `test-lxc`

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
- path changes for an existing extra mount should start as blocked /
  replacement-sensitive unless Phase 0 evidence proves otherwise

## Guardrail / Workflow Implications

- The broad teardown harness is inventory-driven, not stack-directory-driven.
- `test-storage` can stay out of normal destroy/deploy gates by remaining out
  of `docs/teardown-test/inventory.md` unless a specific validation pass opts in
  to it.
- No special-case Terraform code path is needed just to exclude the dedicated
  storage-validation stack from the broad gate.

## Recommended Next Copilot Pass

Use `docs/storage-refactor/copilot-init-prompt.md` for Phase 0 only.

The next large pass should:

1. confirm the highest completed phase is still Phase 0 / not started
2. create the dedicated `test-storage` stack as a normal tracked stack shape
3. write the mutation matrix and classifier-design note
4. run the Phase 0 source checks
5. run the targeted `terragrunt plan` / `apply` capability exercises on
   `test-storage`
6. hand back exact evidence for:
   - Docker mount growth
   - first extra-mount introduction
   - existing extra-mount growth
   - blocked or replacement-sensitive mount edits
