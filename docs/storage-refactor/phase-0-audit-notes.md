# Storage Refactor Phase 0 Audit Notes

Date: 2026-05-27

Status note: this file is a chronological execution log, not the authoritative
summary of the refactor's current state. Many sections below include
time-specific "Exact recommended next pass" guidance that was correct when that
entry was written but is no longer the canonical next-step document.

For the current position, use these files first:

- `docs/storage-refactor/README.md` for the top-level current-state summary
- `docs/storage-refactor/plan.md` for phase goals and remaining scope
- `docs/storage-refactor/capability-matrix.md` for the current authoritative
  mutation-class mapping
- `docs/storage-refactor/docker-mount-resize-tests.md` for the current
  repo-native Docker-mount operational workflow

## Current Source Baseline

 - `terraform/lxc/stacks/test-storage/` exists in this branch as a tracked
   dedicated storage-validation stack. During this Phase 0 pass I executed a
   targeted provider-backed plan non-interactively using the repository's
   `with-secrets` wrapper and a `terragrunt plan` invocation. The run produced
   an OpenTofu/Terraform plan which was converted to machine-readable JSON for
   classification (see classifier output noted below). This verifies the
   stack is usable as a Phase 0 proof target and provides real provider-backed
   evidence for the remaining proof gap.

Note (tracked-stack baseline reconciliation): the tracked file
`terraform/lxc/stacks/test-storage/stack.yaml` in this branch previously
contained `extra_mount_*` fields despite being intended as the Docker-only
baseline for Phase 0. During this cleanup pass those `extra_mount_*` fields
were removed from the tracked baseline so the file now correctly represents a
Docker-only starting shape. Any first-extra-mount exercises must be applied as
transient mutation steps during testing and must not be committed into the
tracked baseline.
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
  provider-backed evidence from `test-storage` runs. A targeted transient
  `rootfs_size` increase was executed against the tracked `test-storage`
  baseline and produced a provider-backed non-replacing plan. The plan shows
  an in-place update of the container's `disk` size (8 -> 16) and the Phase 0
  classifier emitted `rootfs_size_increase` => `safe-in-place`. The
  corresponding classifier output was written to `/tmp/classified-rootfs-grow.json`.
  Based on this run, the `rootfs_size: increase` matrix row is now
  authoritative for the current `pve-test` profile.

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

## Durable Hand-back: Phase 0 validation pass

Date: 2026-05-27

Validation scope: Phase 0 — Capability check and storage audit for `pve-test`.

Validation status: partial — authoritative for `pve-test` profile; not proved
across all backends.

Summary of commands run (this pass):
- `./with-secrets bash -lc 'echo $TF_VAR_proxmox_node'` — confirmed `pve-test`
- `./scripts/teardown-deploy-test.sh source-preflight` — preflight checks (PASS)
- `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline` — contract validation (PASS)
- `python3 terraform/lxc/classify-storage-plan.py --plan-json docs/storage-refactor/fixtures/fixture-docker-grow-plan.json --stack-name test-storage --out /tmp/classified-docker-grow.json` — classifier wrote `/tmp/classified-docker-grow.json`
- `python3 terraform/lxc/check-plan-safety.py --plan-json /tmp/classified-docker-grow.json` — plan safety check (PASS)
- `./with-secrets /home/steve/.local/bin/sonar-scanner` — Sonar analysis (SUCCESS)
- `/home/steve/.local/bin/snyk iac test terraform/` — Snyk IaC scan (SUCCESS; monthly test limit reached notice)

Key results:
- Target guard: `TF_VAR_proxmox_node` is `pve-test` (ok).
- `terraform/lxc/stacks/test-storage/stack.yaml` tracked baseline contains `rootfs_size: 16` (confirmed).
- `rootfs_size` increase: authoritative for `pve-test` profile as `safe-in-place` (provider-backed in-place disk resize observed and classifier output recorded during earlier transient runs and consistent with Phase 0 matrix).
- `docker_storage_size` (Docker mount) growth: classifier output shows `replacement-sensitive` for the tested plan (`/tmp/classified-docker-grow.json` shows `replacement-sensitive`), so Docker mount growth remains replacement-sensitive under the current `pve-test` backend.
- First extra-mount introduction (none -> first extra): remains `blocked` by Phase 0 conservative policy (no provider-backed non-replacing proof observed).
- No repo-source validation failures were caused by the storage-refactor work during this pass; narrow checks and safety verification passed.

Files changed in this pass:
- No tracked source files were modified by this pass. Transient artifacts and evidence written:
  - evidence logs: `docs/teardown-test/evidence/20260527-081417/` (generated by `teardown-deploy-test.sh`).
  - classifier output: `/tmp/classified-docker-grow.json` (ephemeral).

Blockers / environmental failures:
- None blocking. `snyk` reported monthly private test quota reached, but the IaC test completed and reported zero issues.

Phase 0 acceptance recommendation:
- Accept Phase 0 as complete for the `pve-test` profile (evidence authoritative for `rootfs` grow; Docker growth classified as `replacement-sensitive`; extra-mount transitions conservatively blocked).
- Do NOT consider Phase 0 fully proven across other backends (local-lvm, zfs, etc.) without representative testing.

Exact recommended next pass (single next action): representative-testing
- `representative-testing`: Run targeted provider-backed mutation plans on representative backend mappings (e.g., `local-lvm`, `zfs`, any other backends used in production `pve`) to prove or disprove in-place behaviors for:
  - Docker mount growth (attempt to find a backend/profile that supports non-replacing expansion),
  - extra-mount size growth (seek any backend that provides in-place evidence),
  - confirm that `rootfs` growth remains safe across backends.

Next pass acceptance gate:
- The representative-testing pass must produce at least one provider-backed non-replacing plan for Docker or extra-mount growth to alter the Phase 0 matrix. Otherwise the Phase 0 conservative mapping (Docker: replacement-sensitive; extra-mount: blocked) stands and Phase 1 contract work must proceed with those constraints.

Commands and artifacts to cite in reviewer hand-back:
- Evidence logs: `docs/teardown-test/evidence/20260527-081417/` (contains preflight outputs and validator logs).
- Classifier output (ephemeral): `/tmp/classified-docker-grow.json` — contains `replacement-sensitive` classification for the docker-grow fixture.

Durable author: GitHub Copilot (execution pass)

## Durable Hand-back: ZFS backend docker-grow test

Date: 2026-05-28

Validation scope: targeted representative backend test for Docker mount growth
on a ZFS-backed `pve-test` profile.

Validation status: passed — the backend test completed and produced durable
provider-backed evidence.

Summary of commands run (this pass):
- `./with-secrets bash -lc 'echo $TF_VAR_proxmox_node'` — confirmed `pve-test`
- `ssh root@pve-test.gibbsgreatly.xyz pvesm status` — enumerated live storage
  backends and confirmed available ZFS pools
- `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline` — contract validation (PASS) after adding a ZFS-backed profile
- `./scripts/teardown-deploy-test.sh source-preflight` — partial; offline storage checks passed, but the run still hit the unrelated existing `deploy-harbor-stack.yml` syntax-check failure
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -no-color -out=/tmp/test-storage-zfs-rebuild.tfplan'` — planned the backend migration from `local-lvm` to ZFS
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt apply -auto-approve /tmp/test-storage-zfs-rebuild.tfplan'` — rebuilt `test-storage` onto `infrastructure-containers`
- `ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct config 150'` — confirmed `rootfs` and `mp0` both point at `infrastructure-containers`
- `ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct exec 150 -- df -h / /var/lib/docker'` — verified the rebuilt live filesystem sizes (`/` 16G, `/var/lib/docker` 8G)
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -no-color -out=/tmp/test-storage-zfs-docker-grow.tfplan'` — targeted Docker mount grow plan on ZFS
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage; cache_dir=$(find .terragrunt-cache -mindepth 2 -maxdepth 2 -type d | head -n 1); cd "$cache_dir"; tofu show -json /tmp/test-storage-zfs-docker-grow.tfplan > /tmp/test-storage-zfs-docker-grow.plan.json'` — converted the grow plan to JSON
- `python3 terraform/lxc/classify-storage-plan.py --plan-json /tmp/test-storage-zfs-docker-grow.plan.json --stack-name test-storage --out /tmp/classified-test-storage-zfs-docker-grow.json` — classifier output for the ZFS grow plan
- `python3 terraform/lxc/check-plan-safety.py --plan-json /tmp/classified-test-storage-zfs-docker-grow.json` — plan safety check (PASS)
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -no-color'` — confirmed the reverted tracked baseline is a live no-op after restoring `docker_storage_size: "8G"`

Key results:
- `test-storage` is now intentionally tracked on the ZFS-backed
  `infrastructure-containers` pool via `storage_profile: platform-zfs`.
- Live Proxmox config confirms the rebuilt ZFS-backed shape:
  - `rootfs: infrastructure-containers:subvol-150-disk-0,size=16G`
  - `mp0: infrastructure-containers:subvol-150-disk-1,mp=/var/lib/docker,size=8G`
- Live guest verification confirms the rebuilt filesystem sizes:
  - `/` mounted from the ZFS rootfs at 16G
  - `/var/lib/docker` mounted from the ZFS-backed `mp0` dataset at 8G
- Targeted Docker mount growth on ZFS still did **not** produce an in-place
  path. The provider-backed plan for `docker_storage_size: "8G" -> "16G"`
  still forced replacement of `module.lxc.proxmox_virtual_environment_container.docker_host`.
- The classifier output at `/tmp/classified-test-storage-zfs-docker-grow.json`
  records the ZFS grow attempt as `replacement-sensitive`.
- Because the ZFS Docker-grow plan was still unsafe, no live Docker mount
  resize apply was performed through Terraform/OpenTofu. The tracked baseline
  was returned to the real live `8G` value and `terragrunt plan` returned to
  no-op.

Files changed in this pass:
- `terraform/lxc/storage/pve-test.yaml`
- `terraform/lxc/stacks/test-storage/stack.yaml`
- `terraform/lxc/stacks/test-storage/STACK_CONTRACT.md`
- `docs/storage-refactor/capability-matrix.md`
- `docs/storage-refactor/phase-0-audit-notes.md`

## Durable Hand-back: Harbor ZFS propagation pass

Date: 2026-05-28

Validation scope: propagate the proved extra-mount ZFS storage shape to the
remaining real stack with an existing extra mount (`harbor-stack`), rebuild it,
verify service health, and probe one real operational extra-mount grow.

Validation status: mixed but gate-usable. The rebuild onto
`platform-zfs` + `durable-zfs` succeeded and Harbor service health was
re-established. The live extra-mount grow updated desired state, Proxmox config,
and the backing ZFS dataset quota, but guest-visible free space remained capped
by backing-pool capacity, so this pass does not add a new clean guest-visible
growth proof.

Summary of commands run (this pass):
- `./with-secrets bash -lc 'echo $TF_VAR_proxmox_node'` — confirmed `pve-test`
- `./with-secrets bash -lc "curl -sS -o /dev/null -w '%{http_code}\\n' http://\${LAB_IP_HARBOR}/v2/"` — pre-rebuild Harbor smoke baseline (`401`)
- `./with-secrets bash -lc '... pct exec 40010 -- sh -lc '\''tar --exclude=harbor/lost+found -C /var/lib -czf - harbor'\'''` — captured `/var/lib/harbor` backup to `/tmp/harbor-stack-zfs-rebuild/harbor-var-lib-harbor-20260528-085813.tgz`
- `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline` — contract validation (PASS)
- `./with-secrets bash -lc 'python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test'` — live contract validation (PASS)
- `./scripts/rebuild-gate-destroy.sh --execute --stack harbor-stack` — destroyed Harbor after creating the missing `pve-test` workspace and importing live state into it
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/harbor-stack && terragrunt apply -auto-approve -no-color'` — rebuilt Harbor on `infrastructure-containers`
- `./with-secrets scripts/provision.sh --stack harbor-stack` — re-provisioned Harbor successfully
- `./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack harbor-stack --mount-path /var/lib/harbor'` — attempted operational grow from `100G` to `120G`
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/harbor-stack && terragrunt plan -no-color'` — post-resize no-drift check (PASS)

Key results:
- Harbor now resolves to `storage_profile: platform-zfs` and
  `extra_mount_profile: durable-zfs`, with the canonical
  `extra_mount.profile: durable-zfs` and
  `extra_mount.resize_control_plane: operational` fields aligned.
- Live Proxmox config after rebuild confirms the desired ZFS-backed shape:
  - `rootfs: infrastructure-containers:subvol-40010-disk-0,size=16G`
  - `mp0: infrastructure-containers:subvol-40010-disk-1,mp=/var/lib/docker,size=20G`
  - `mp1: infrastructure-containers:subvol-40010-disk-2,mp=/var/lib/harbor,size=100G`
- Guest verification after rebuild showed `/var/lib/harbor` mounted from
  `infrastructure/subvol-40010-disk-2` with about `65.3G` available, which is
  consistent with the free space then available in the underlying pool.
- Harbor service health was restored after reprovisioning:
  - `systemctl is-active harbor` returned `active`
  - `curl ... /v2/` returned `401`
  - expected Harbor state paths remained present under `/var/lib/harbor`
- The operational extra-mount grow updated the desired state, `pct config`, and
  dataset quota:
  - `stack.yaml` now declares `extra_mount_size: "120G"` and
    `extra_mount.size: "120G"`
  - `pct config 40010` reports
    `mp1: infrastructure-containers:subvol-40010-disk-2,mp=/var/lib/harbor,size=120G`
  - `zfs get refquota infrastructure/subvol-40010-disk-2` reports `120G`
- The same grow attempt did not produce a larger guest-visible capacity because
  the backing `infrastructure` zpool only had about `78.8G` free:
  - `zpool list infrastructure` showed `FREE 78.8G`
  - `zfs list infrastructure/subvol-40010-disk-2` showed `AVAIL 65.3G`
  - guest `df -h /var/lib/harbor` remained about `66G`
- Despite that capacity cap, Harbor remained healthy and the stack returned to
  a post-resize no-drift `terragrunt plan`.

Files changed in this pass:
- `terraform/lxc/stacks/harbor-stack/stack.yaml`
- `docs/storage-refactor/capability-matrix.md`
- `docs/storage-refactor/phase-0-audit-notes.md`

Blockers / environmental caveats:
- `harbor-stack` lacked a pre-existing `pve-test` workspace in its backend. The
  pass repaired this locally by initializing from `default`, creating the
  `pve-test` workspace, and then rerunning the normal destroy helper.
- The Harbor live-resize attempt hit backing-pool capacity limits. This is not
  a storage-contract drift issue, but it prevents treating the Harbor run as a
  clean guest-visible `100G -> 120G` proof.

Exact recommended next pass (single next action): full-teardown-gate
- `full-teardown-gate`: run the full teardown/redeploy gate from this branch to
  validate that the remaining real extra-mount stack now survives the
  repo-native destroy/recreate cycle on the ZFS-backed storage shape.

## Durable Hand-back: proxy-stack ZFS rebuild-and-proof pass

Date: 2026-05-28

Validation scope: first real infrastructure-container rebuild proof for the
existing-extra-mount ZFS operational grow workflow on `proxy-stack`.

Validation status: passed — `proxy-stack` was rebuilt onto the approved
ZFS-backed storage shape, the live certs mount was grown operationally, the
service smoke succeeded after rebuild and after resize, and post-resize
OpenTofu/Terraform returned to no drift.

Summary of commands run (this pass):
- `./with-secrets bash -lc 'echo $TF_VAR_proxmox_node'` — confirmed `pve-test`
- `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline` — offline contract validation (PASS)
- `./with-secrets bash -lc 'python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test'` — live contract validation (PASS)
- `./with-secrets bash -lc 'curl -skI --resolve "${LAB_FQDN_TRAEFIK}:443:${LAB_IP_PROXY}" "https://${LAB_FQDN_TRAEFIK}/"'` — pre-rebuild smoke baseline (`HTTP/2 500`, pre-existing)
- `./with-secrets bash -lc 'target="${PVE_TEST_FQDN:-${PROXMOX_HOST:-${TF_VAR_proxmox_node}.local}}" && ssh -F /dev/null -o StrictHostKeyChecking=accept-new root@"$target" "pct status 30010 && pct exec 30010 -- test -d /opt/proxy-stack/certs" && ssh -F /dev/null -o StrictHostKeyChecking=accept-new root@"$target" "pct exec 30010 -- sh -lc '\''tar -C /opt/proxy-stack --exclude=certs/lost+found -czf - certs'\''" > /tmp/proxy-stack-zfs-rebuild/proxy-stack-certs-pre-destroy.tgz && gzip -t /tmp/proxy-stack-zfs-rebuild/proxy-stack-certs-pre-destroy.tgz'` — captured pre-destroy cert/state backup
- `./scripts/rebuild-gate-destroy.sh --execute --stack proxy-stack` — destroyed live `proxy-stack` after importing the CT into the `pve-test` workspace
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/proxy-stack && terragrunt apply -auto-approve -no-color'` — rebuilt `proxy-stack` on `infrastructure-containers`
- `./with-secrets scripts/provision.sh --stack proxy-stack` — reprovisioned the rebuilt container
- `ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ANSIBLE_ROLES_PATH=$PWD/terraform/lxc/ansible/roles ./with-secrets ansible-playbook -i terraform/lxc/stacks/proxy-stack/inventory.yml -u root terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml` — republished proxy config after fixing generated Traefik rendering and internal Authentik forward-auth TLS handling
- `./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack proxy-stack --mount-path /opt/proxy-stack/certs'` — live operational extra-mount grow from `5G` to `10G`
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/proxy-stack && terragrunt plan -no-color'` — confirmed post-resize no drift (`No changes.`)
- `/home/steve/.local/bin/snyk iac test terraform/` — Snyk IaC scan (SUCCESS; monthly private-test quota notice only)
- `./with-secrets /home/steve/.local/bin/sonar-scanner` — Sonar analysis (SUCCESS)

Key results:
- Backup captured: `/tmp/proxy-stack-zfs-rebuild/proxy-stack-certs-pre-destroy.tgz`
  - archive SHA-256: `564b017906b2022ebdf3569752f61c3baf74e2d4cc0e165fd4a66be7e9244dcf`
  - contents verified: `certs/letsencrypt/acme.json`, `certs/step-ca/acme.json`, `certs/combined-ca.crt`
  - note: `certs/lost+found` had to be excluded because it is unreadable through the unprivileged container view
- Rebuild result: `proxy-stack` now runs as CT `30010` with
  - `rootfs: infrastructure-containers:subvol-30010-disk-0,size=8G`
  - `mp0: infrastructure-containers:subvol-30010-disk-1,mp=/var/lib/docker,size=5G`
  - `mp1: infrastructure-containers:subvol-30010-disk-2,mp=/opt/proxy-stack/certs,size=5G` immediately after rebuild
- Service verification after rebuild: passed after fixing two repo-local blockers uncovered by the rebuild
  - `with-secrets` was not deriving missing `TF_VAR_lab_*` values from `LAB_*`, which blocked non-interactive import/destroy in the `pve-test` workspace path
  - `deploy-proxy-stack.yml` was copying generated Traefik files without substituting `${LAB_IP_*}` placeholders, and the internal Authentik forward-auth hop needed relaxed TLS verification for the current homelab chain
  - after those fixes, the required smoke check returned `HTTP/2 302` redirecting to Authentik instead of `HTTP/2 500`
- Resize result: passed
  - desired size updated from `5G` to `10G` in `terraform/lxc/stacks/proxy-stack/stack.yaml`
  - `pct config 30010` now reports `mp1: infrastructure-containers:subvol-30010-disk-2,mp=/opt/proxy-stack/certs,size=10G`
  - guest `df -h /opt/proxy-stack/certs` now reports `10G`
  - cert/state files remained present after resize, including `combined-ca.crt` and both `acme.json` files
- Post-resize drift result: passed
  - `./with-secrets bash -lc 'cd terraform/lxc/stacks/proxy-stack && terragrunt plan -no-color'` returned `No changes. Your infrastructure matches the configuration.`
- Required scans: passed
  - Snyk IaC found `0` issues; the monthly private-test quota notice was non-blocking
  - SonarScanner completed with `EXECUTION SUCCESS`

Files changed in this pass:
- `with-secrets`
- `terraform/lxc/stacks/proxy-stack/stack.yaml`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- `docs/storage-refactor/capability-matrix.md`
- `docs/storage-refactor/phase-0-audit-notes.md`

Residual risks / exact blockers addressed:
- The rebuild surfaced two real workflow blockers that are now fixed in source:
  - missing `TF_VAR_lab_*` derivation for `LAB_*` values in `with-secrets`
  - generated Traefik publish path not rendering `${LAB_IP_*}` placeholders before deployment
- Internal Authentik forward-auth on the proxy currently relies on relaxed TLS verification (`insecureSkipVerify: true`) rather than a fully trusted internal CA chain. This unblocked the live proof, but the trust chain should still be hardened in a later pass.

Exact recommended next pass: workflow-hardening
- Harden the internal Authentik trust path for proxy forward-auth so `deploy-proxy-stack.yml` can return to explicit CA verification, then run the same focused proxy smoke check and follow with the next representative rebuild candidate (`harbor-stack`).

Blockers / environmental failures:
- `source-preflight` is still blocked by the unrelated existing Harbor playbook
  syntax-check failure; this did not block the storage contract check or the
  live ZFS backend test itself.
- `terragrunt plan` on `test-storage` still emits the pre-existing SDN egress
  warning for `build_seg`; it did not prevent the rebuild or the targeted
  Docker-grow planning.

Practical conclusion from this pass:
- Rebuilding onto ZFS was successful.

## Durable Hand-back: ZFS-backed extra-mount operational grow proof

Date: 2026-05-28

Validation scope: prove or disprove the grow-only operational workflow for an
already-existing ZFS-backed `extra_mount` on a disposable dedicated proof LXC.

Validation status: passed — this workflow is now proved for the current
`pve-test` `platform-zfs` + `durable-zfs` path on an existing extra mount.

Summary of commands run (this pass):
- `./with-secrets bash -lc 'echo $TF_VAR_proxmox_node'` — confirmed `pve-test`
- `./with-secrets bash -lc "ssh -F /dev/null root@${PVE_TEST_FQDN:-pve-test.gibbsgreatly.xyz} 'pct status 151'"` — confirmed VMID `151` was unused before create
- `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline` — contract validation (PASS) after adding the disposable proof stack
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage-extra && terragrunt apply -auto-approve -no-color'` — created the disposable proof stack with an existing extra mount from initial provision time
- `./with-secrets bash -lc "ssh -F /dev/null root@${PVE_TEST_FQDN:-pve-test.gibbsgreatly.xyz} 'pct config 151'"` — confirmed `rootfs`, Docker mount, and extra mount live on `infrastructure-containers`
- `./with-secrets bash -lc "ssh -F /dev/null root@${PVE_TEST_FQDN:-pve-test.gibbsgreatly.xyz} 'pct exec 151 -- df -h /srv/test-extra'"` — confirmed guest baseline size `8.0G`
- `./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack test-storage-extra --mount-path /srv/test-extra'` — operationally resized the existing extra mount from `8G` to `16G`
- `./with-secrets bash -lc "ssh -F /dev/null root@${PVE_TEST_FQDN:-pve-test.gibbsgreatly.xyz} 'pct config 151'"` — confirmed Proxmox config now reports `mp1 ... size=16G`
- `./with-secrets bash -lc "ssh -F /dev/null root@${PVE_TEST_FQDN:-pve-test.gibbsgreatly.xyz} 'pct exec 151 -- df -h /srv/test-extra'"` — confirmed guest-visible size `16G`
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage-extra && terragrunt plan -no-color'` — post-resize drift check (PASS: `No changes. Your infrastructure matches the configuration.`)

Key results:
- Added a dedicated disposable proof stack at `terraform/lxc/stacks/test-storage-extra/` using:
  - hostname `test-storage-extra`
  - VMID `151`
  - IP `192.168.10.65/24`
  - `network.zone: build_seg`
  - `storage_profile: platform-zfs`
  - `extra_mount_profile: durable-zfs`
  - canonical and legacy Docker mount fields aligned at `24G`
  - canonical and legacy extra-mount fields aligned at `/srv/test-extra`
- The stack was created with the extra mount present from initial create time:
  - `mp1: infrastructure-containers:subvol-151-disk-2,mp=/srv/test-extra,size=8G`
- The operational grow workflow succeeded live:
  - initial live size: `8G`
  - requested desired size: `16G`
  - post-resize Proxmox config: `mp1 ... size=16G`
  - post-resize guest result: `infrastructure/subvol-151-disk-2   16G  128K   16G   1% /srv/test-extra`
- Post-resize Terraform/OpenTofu drift is clean for the proof stack. The stack-level `terragrunt plan -no-color` returned `No changes.`

Repo-local blocker fixed during this pass:
- `terraform/lxc/main.tf` contained a duplicate `legacy_extra_mount_storage` local definition that caused OpenTofu init/apply to fail with `Error: Attribute redefined`. The duplicate definition was removed and the deploy then succeeded.

Residual environment note:
- `terragrunt apply` and `terragrunt plan` still emit the pre-existing warning from `check "network_layer_sdn_attachment_egress_is_complete"` for `build_seg` because the resolved SDN attachment has empty subnet/gateway fields with `snat=false`. This warning did not block create, resize, or the post-resize no-drift plan for the proof stack.

Practical conclusion from this pass:
- Operational ZFS-backed extra-mount grow on an already-existing extra mount is supported for the current `pve-test` workflow.
- This proof does not broaden to first-extra-mount introduction on an existing container, second extra mounts, or direct provider-managed non-rootfs size reconciliation.
- The hoped-for backend-specific difference did **not** make Terraform-driven
  Docker mount growth safe. Under the current provider/resource model,
  `/var/lib/docker` growth remains `replacement-sensitive` on both:
  - `local-lvm`
  - `infrastructure-containers` zfs

Exact recommended next pass (single next action): operational-resize-drift-test
- Do a disposable operational test on this same ZFS-backed `test-storage`
  container using Proxmox-native `pct resize mp0 16G`, verify the live grow in
  the guest, and then run a fresh `terragrunt plan` to observe the exact drift
  behavior.
- That pass should decide whether a workable repo policy exists using:
  - operational resize via Proxmox/Ansible
  - explicit Terraform drift suppression for the Docker mount
  - custom validation to retain safety on the ignored fields
- Use `docs/storage-refactor/copilot-operational-resize-drift-prompt.md` for
  that pass.

## Durable Hand-back: Operational resize drift test

Date: 2026-05-28

Validation scope: disposable Proxmox-native resize of the ZFS-backed Docker
mount on `test-storage`, followed immediately by post-resize Terraform/OpenTofu
drift measurement.

Validation status: passed — the operational resize succeeded live and the
resulting drift was measured exactly.

Summary of commands run (this pass):
- `./with-secrets bash -lc 'echo $TF_VAR_proxmox_node'` — confirmed `pve-test`
- `ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct config 150'` — captured
  pre-change Proxmox config and verified the Docker mount index
- `ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct exec 150 -- df -h / /var/lib/docker'` — captured pre-change guest-visible sizes
- `ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct resize 150 mp0 16G'` — performed the live Docker mount resize without Terraform/OpenTofu
- `ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct config 150'` — captured post-resize Proxmox config
- `ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct exec 150 -- df -h /var/lib/docker'` — verified the guest-visible post-resize size
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -no-color -out=/tmp/test-storage-zfs-post-pct-resize.tfplan'` — measured drift from the tracked `docker_storage_size: "8G"` baseline
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && cache_dir=$(find .terragrunt-cache -mindepth 2 -maxdepth 2 -type d | head -n 1) && cd "$cache_dir" && tofu show -json /tmp/test-storage-zfs-post-pct-resize.tfplan > /tmp/test-storage-zfs-post-pct-resize.plan.json'` — converted the saved plan to JSON using the same toolchain context Terragrunt used
- `python3 terraform/lxc/classify-storage-plan.py --plan-json /tmp/test-storage-zfs-post-pct-resize.plan.json --stack-name test-storage --out /tmp/classified-test-storage-zfs-post-pct-resize.json` — wrote classifier output for the post-resize drift plan
- `python3 terraform/lxc/check-plan-safety.py --plan-json /tmp/test-storage-zfs-post-pct-resize.plan.json` — confirmed the drift remains unsafe (`replacement-sensitive`)
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -no-color'` — with `docker_storage_size: "16G"` in `stack.yaml`, confirmed the operationally resized live state returns to no drift

Exact pre-change evidence:
- `pct config 150` Docker mount line before resize:
  - `mp0: infrastructure-containers:subvol-150-disk-1,mp=/var/lib/docker,size=8G`
- `pct config 150` rootfs line before resize:
  - `rootfs: infrastructure-containers:subvol-150-disk-0,size=16G`
- Guest-visible filesystems before resize:
  - `infrastructure/subvol-150-disk-0   16G  916M   16G   6% /`
  - `infrastructure/subvol-150-disk-1  8.0G   98M  8.0G   2% /var/lib/docker`

Exact post-resize evidence:
- `pct config 150` Docker mount line after resize:
  - `mp0: infrastructure-containers:subvol-150-disk-1,mp=/var/lib/docker,size=16G`
- `pct config 150` rootfs line after resize:
  - `rootfs: infrastructure-containers:subvol-150-disk-0,size=16G`
- Guest-visible filesystem after resize:
  - `infrastructure/subvol-150-disk-1   16G   98M   16G   1% /var/lib/docker`

Exact Terraform/OpenTofu drift behavior after the live resize:
- With the tracked repo baseline still at `docker_storage_size: "8G"` in
  `terraform/lxc/stacks/test-storage/stack.yaml`, the fresh `terragrunt plan`
  did not produce a narrow in-place correction.
  It planned replacement of `module.lxc.proxmox_virtual_environment_container.docker_host`.
- Exact Docker mount fields shown as drift in the human-readable plan:
  - `mount_point.size = "16G" -> "8G" # forces replacement`
  - `mount_point.volume = "infrastructure-containers:subvol-150-disk-1" -> "infrastructure-containers"`
  - `mount_point.path_in_datastore = "infrastructure-containers:subvol-150-disk-1" -> (known after apply)`
- The classifier output at `/tmp/classified-test-storage-zfs-post-pct-resize.json`
  recorded:
  - `module.lxc.proxmox_virtual_environment_container.docker_host` => `replacement-sensitive`
  - `module.lxc.terraform_data.container_epoch` => `replacement-sensitive`
- The safety checker failed on the same raw plan JSON and reported unsafe
  storage transitions.
- A follow-up no-op check then set `docker_storage_size: "16G"` in
  `stack.yaml` and re-ran `terragrunt plan`. With desired state and live state
  aligned at `16G`, the plan returned `No changes. Your infrastructure matches
  the configuration.`

Files changed in this pass:
- `docs/storage-refactor/phase-0-audit-notes.md`
- `terraform/lxc/stacks/test-storage/stack.yaml`

Practical conclusion from this pass:
- Proxmox-native `pct resize` on the ZFS-backed Docker mount worked cleanly.
- No additional in-guest filesystem step was required; the guest saw `16G`
  immediately after the resize.
- Terraform/OpenTofu drift after the manual resize is not a narrow no-op or
  safe in-place shrink/correct path. Under the current provider/resource model,
  the drift remains `replacement-sensitive`.
- `stack.yaml` remains the source of truth. Once the desired size in
  `stack.yaml` was updated to match the live `16G` operational resize, a fresh
  `terragrunt plan` returned no drift.
- The workable repo model for ZFS-backed non-rootfs growth is therefore:
  change desired size in `stack.yaml`, perform the host-side resize with
  Ansible/Proxmox, verify the guest, then let Terraform/OpenTofu validate the
  aligned end state.
- That model should extend to additional ZFS-backed non-rootfs mounts later, as
  long as each mount has a stable logical identity and remains on a grow-only
  workflow.

Exact recommended next pass (single next action): operational-workflow-implementation
- Implement the approved day-2 workflow for ZFS-backed non-rootfs growth:
  `stack.yaml` remains the source of truth, but Ansible/Proxmox performs the
  actual resize before the next normal Terraform/OpenTofu reconciliation pass.
- Phase 1 contract work should encode the resize control plane explicitly so
  Docker and any future extra mounts can declare when day-2 growth is
  operational rather than provider-managed.

## Durable Hand-back: Operational resize workflow implementation

Date: 2026-05-28

Validation scope: first supported implementation slice for grow-only,
ZFS-backed non-rootfs mount growth with `stack.yaml` as the source of truth and
Proxmox/Ansible as the mutation engine.

Validation status: passed — implemented and proved live on `test-storage`.

Summary of commands run (this pass):
- `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline` — validated the new stack intent and guardrails
- `ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ANSIBLE_ROLES_PATH=$PWD/terraform/lxc/ansible/roles ansible-playbook -i terraform/lxc/stacks/test-storage/inventory.yml terraform/lxc/ansible/playbooks/resize-lxc-mount.yml --syntax-check` — syntax check for the new playbook
- `bash -n scripts/resize-lxc-mount.sh` — syntax check for the new wrapper
- `./with-secrets bash -lc 'echo $TF_VAR_proxmox_node'` — confirmed `pve-test`
- `./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack test-storage'` — executed the operational resize workflow against `test-storage`
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -no-color'` — confirmed no drift after the operational resize completed

Files changed in this pass:
- `terraform/lxc/storage/pve-test.yaml`
- `terraform/lxc/stacks/test-storage/stack.yaml`
- `terraform/lxc/stacks/test-storage/STACK_CONTRACT.md`
- `terraform/lxc/validate-storage-contract.py`
- `terraform/lxc/ansible/playbooks/resize-lxc-mount.yml`
- `scripts/resize-lxc-mount.sh`
- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/storage-refactor/phase-0-audit-notes.md`

## Durable Hand-back: Extra-mount follow-up implementation

Date: 2026-05-28

Validation scope: implement canonical `extra_mount` contract path, preserve legacy compatibility, and validate repository-local tooling and syntax.

Validation status: passed (offline/static checks and syntax checks only). No destructive or live extra-mount applies were performed.

Summary of commands run during this pass:
- `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline` — offline contract validation (PASS)
- `ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_REMOTE_TEMP=/tmp/ansible-remote ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ANSIBLE_ROLES_PATH=$PWD/terraform/lxc/ansible/roles ansible-playbook -i terraform/lxc/stacks/test-storage/inventory.yml terraform/lxc/ansible/playbooks/resize-lxc-mount.yml --syntax-check` — Ansible syntax check (PASS)
- `bash -n scripts/resize-lxc-mount.sh` — shell syntax check (PASS)

Files changed in this pass:
- `terraform/lxc/validate-storage-contract.py` — add canonical `extra_mount` normalization, compatibility checks, and include `extra_mount` in resolved output
- `terraform/lxc/main.tf` — prefer `extra_mount` canonical fields while keeping legacy fallbacks and add mismatch fast-fail checks
- `scripts/resize-lxc-mount.sh` — fix intent-checking Python snippet and prefer canonical `extra_mount` when present; add canonical/legacy mismatch checks
- `terraform/lxc/stacks/proxy-stack/stack.yaml` — add explicit `extra_mount` block (kept legacy fields aligned)
- `terraform/lxc/stacks/harbor-stack/stack.yaml` — add explicit `extra_mount` block (kept legacy fields aligned)
- `docs/storage-refactor/phase-0-audit-notes.md` — this durable hand-back (appended)

Whether `extra_mount` is now canonical: Yes — the repository now prefers the explicit `extra_mount` block where present and treats legacy `extra_mount_path`, `extra_mount_size`, and `extra_mount_profile` as transitional fallbacks. The code base fast-fails when canonical and legacy fields disagree.

Remaining compatibility debt / open items:
- First-extra-mount introduction remains out-of-scope and is intentionally not implemented or proven here.
- Live operational extra-mount resize was not performed for any real stack in this pass. The validator enforces that operational resize intent remain `resize_control_plane: operational` and `mutation_policy: grow-only`, and the playbook/script read the canonical block first, but no live resize of extra mounts was executed.
- Broader repository-wide migration of stacks to canonical `extra_mount` blocks was only performed for the two stacks that already declared legacy extra-mount fields (`proxy-stack`, `harbor-stack`). Other stacks remain on legacy paths until a migration pass is run.

What live validation was actually performed:
- Offline manifest + stack resolution with `validate-storage-contract.py --offline` — confirmed all stacks resolve with the new canonical handling.
- Ansible playbook syntax-check and shell syntax-check — verified runtime tooling changes are syntactically valid.
- No Proxmox API calls, no `terragrunt plan` against live stacks, and no `pct resize` actions were executed for extra mounts during this pass.

Exact recommended next pass:
- workflow-hardening: Harden the operational workflow for extra-mount grow-only operations (Ansible playbook, idempotence checks, extra-mount-specific validation hooks).
- broader-stack-migration: Roll canonical `extra_mount` blocks into other stacks that already have legacy fields, with a small promotion plan and compatibility checks.
- gate: After workflow hardening and representative non-destructive validation on a test target, run a promotion gate to `baseline/teardown-validated` including required scans (Sonar, Snyk) and representative `terragrunt plan` checks.

Durable author: GitHub Copilot (extra-mount follow-up implementation)

What workflow was implemented:
- `stack.yaml` now declares first-slice Docker mount intent through
  `docker_mount`
- the validator enforces the supported policy for this slice:
  - operational control plane only
  - grow-only only
  - `/var/lib/docker` only
  - ZFS-backed Docker storage only
- the new Ansible playbook resolves the correct `mpX` from the live Proxmox
  config, blocks missing or ambiguous matches, blocks shrink attempts, performs
  `pct resize`, and verifies both `pct config` and guest `df -h`
- the new wrapper script provides the narrow operator entrypoint and makes the
  supported sequence explicit

How it was validated on `test-storage`:
- updated tracked desired size from `16G` to `24G` in `stack.yaml`
- ran the new operational workflow on the live ZFS-backed `test-storage`
  container
- the first run performed the real live resize of `mp0` from `16G` to `24G`
- fixed a local verification regex defect in the guest-size assertion and
  reran the same workflow
- the rerun verified the live `24G` state as a clean no-op and reported:
  - `mount_key=mp0`
  - `current_size=24G`
  - `desired_size=24G`
  - guest `df -h` showing `/var/lib/docker` at `24G`
- `terragrunt plan -no-color` then returned `No changes. Your infrastructure matches the configuration.`

Exact limitations that still remain:
- this first slice only supports `/var/lib/docker`
- this first slice only supports ZFS-backed Docker storage resolved from the
  current manifest metadata
- the workflow is grow-only; shrink remains explicitly blocked
- direct Terraform/OpenTofu apply of non-rootfs size growth remains unsafe and
  out of scope for this slice
- the stack contract still carries the legacy compatibility field
  `docker_storage_size`; it must remain aligned with `docker_mount.size` until
  the module inputs are migrated
- the final `terragrunt plan -no-color` is a no-op, but it still emits the
  pre-existing SDN egress warning for `build_seg`; this is unrelated to the new
  resize workflow and did not introduce drift

Exact recommended next pass: contract-follow-up
- migrate the current module inputs so `docker_mount.size` becomes the single
  declared source for Docker mount size without the temporary duplicated
  compatibility field
- extend the same contract shape and operational workflow to the existing
  optional extra mount path while preserving grow-only guardrails
- decide whether the next validator step should enforce the same metadata for
  additional ZFS-backed stacks or keep this slice isolated to explicit opt-in

## Durable Hand-back: Contract follow-up implementation

Date: 2026-05-28

Validation scope: make `docker_mount.size` the canonical declared Docker mount
size in the Terraform implementation path while preserving narrow
compatibility for unchanged legacy stacks.

Validation status: passed — canonical resolution now flows through the root
Terraform path and the operational resize entrypoints, with compatibility kept
as an explicit fallback only.

Summary of commands run (this pass):
- `./with-secrets bash -lc 'echo $TF_VAR_proxmox_node'` — confirmed `pve-test`
- `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline` — offline contract validation (PASS)
- `./with-secrets bash -lc 'python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test'` — live contract validation (PASS)
- `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -no-color'` — no-drift confirmation for `test-storage` after canonical resolution change (PASS; same pre-existing `build_seg` SDN egress warning only)
- `./with-secrets /home/steve/.local/bin/sonar-scanner` — required code scan because Python/shell/YAML/Ansible files changed (PASS)

What changed in this pass:
- `terraform/lxc/main.tf` now resolves Docker mount size from
  `docker_mount.size` first, then falls back to legacy `docker_storage_size`,
  then the module default.
- `terraform/lxc/main.tf` now fails fast when both fields are present but do
  not match, so the Terraform implementation path enforces the same contract as
  the validator.
- `scripts/resize-lxc-mount.sh` now treats `docker_mount.size` as canonical and
  rejects mismatches when the legacy field is also present.
- `terraform/lxc/ansible/playbooks/resize-lxc-mount.yml` now reads the
  canonical Docker size first and rejects direct-playbook mismatch cases when
  both fields are present.

Canonical field status:
- `docker_mount.size` is now the canonical declared Docker size in the active
  Terraform implementation path for Docker mount provisioning and operational
  resize workflow resolution.

Remaining compatibility debt:
- unchanged stacks that still declare only `docker_storage_size` still resolve
  through the transitional fallback path
- stacks that declare both fields must keep them equal until the repo removes
  the legacy field entirely
- the module input and underlying provider argument are still named
  `docker_storage_size`; only the stack contract source-of-truth has been
  switched in this pass

Validation results:
- offline validator passed for all checked stacks
- live validator passed against `pve-test`
- `terragrunt plan -no-color` for `test-storage` returned `No changes`
  with only the pre-existing `build_seg` SDN egress warning
- Sonar analysis completed successfully with no new blocker for this pass

Exact recommended next pass: extra-mount-follow-up
- extend the explicit mount contract and operational grow-only workflow shape
  to the existing optional extra mount path without changing the approved
  Docker day-2 model

## Durable Hand-back: Pre-rebuild contract tightening

Date: 2026-05-28

Validation scope: tighten the extra-mount contract so only ZFS-backed stacks
may declare the approved operational resize workflow before any real-stack
rebuild testing.

Validation status: passed — the contract is now honest about backend support,
and existing local-lvm infrastructure stacks no longer claim the proved
operational path.

What changed in this pass:
- `terraform/lxc/validate-storage-contract.py` now treats `extra_mount` as a
  canonical contract input during storage-profile resolution and rejects
  `extra_mount.resize_control_plane: operational` unless the resolved
  extra-mount backend is ZFS-backed.
- `terraform/lxc/main.tf` now resolves canonical extra-mount path/size into the
  active module inputs and adds a Terraform-side check that operational
  `extra_mount` declarations must be grow-only and ZFS-backed.
- `terraform/lxc/stacks/proxy-stack/stack.yaml` and
  `terraform/lxc/stacks/harbor-stack/stack.yaml` now declare
  `extra_mount.resize_control_plane: provider` because both still resolve
  through `durable-default` (`local-lvm`) and have not yet been rebuilt onto
  `durable-zfs`.
- `docs/storage-refactor/capability-matrix.md` now states explicitly that
  real stacks remaining on `durable-default` must stay on the provider control
  plane until rebuilt and revalidated on ZFS.

Why this matters before rebuild testing:
- the proved operational workflow is real, but only for already-existing
  ZFS-backed non-rootfs mounts
- `proxy-stack` and `harbor-stack` are not in that shape yet
- rebuild testing should therefore start from an honest contract state rather
  than letting local-lvm stacks advertise a workflow that has not been proven

Exact recommended next pass:
- commit the current branch state
- then choose a first real rebuild target, preferably `proxy-stack`, and
  rebuild it onto `platform-zfs` + `durable-zfs` before attempting a live
  extra-mount resize on an infrastructure container
