# Phase 0 — Storage Mutation Capability Matrix

This matrix captures observed provider/module behavior for storage-related
field transitions. It is the Phase 0 authoritative source for mapping provider
plan actions to mutation classes.

Columns:
- field_transition: short key for the change
- expected_provider_action: what the provider typically reports in `terraform show -json`/plan
- mutation_class: one of `safe-in-place`, `reboot-required`, `replacement-sensitive`, `blocked`
- evidence: how to reproduce on `test-storage` (plan sequence)

Matrix
------

- rootfs_size: increase
  - expected_provider_action: in-place update (resize)
  - mutation_class: safe-in-place
  - authority: authoritative (observed on current `pve-test` profile)
  - evidence: Provider-backed targeted plan for `rootfs_size` increase on
    `test-storage` produced an in-place `disk` size update (8 -> 16). The
    Phase 0 classifier recorded `rootfs_size_increase` => `safe-in-place`.
    Reproduction: transiently increase `rootfs_size` in
    `terraform/lxc/stacks/test-storage/stack.yaml`, run a targeted
    `terragrunt plan -out=/tmp/test-storage-rootfs-grow.tfplan`, convert the
    plan to JSON with the planner used by Terragrunt (e.g. `tofu show -json`),
    and classify with `terraform/lxc/classify-storage-plan.py` (see
    `/tmp/classified-rootfs-grow.json`).

- docker_mount: increase size
  - expected_provider_action: provider reports replacement for the current
    `pve-test` Docker-mount backends tested so far (replace of the container
    resource)
  - mutation_class: replacement-sensitive
  - authority: authoritative (observed on current `pve-test` local-lvm and
    `infrastructure-containers` zfs profiles)
  - evidence: `docker_storage_size` increase on `test-storage` produced a
    provider replace in the observed plan output on both backends tested so
    far:
    - `local-lvm` via the original `platform-default` profile
    - `infrastructure-containers` zfs via the rebuilt `platform-zfs` profile,
      where `mount_point.size = "8G" -> "16G"` still showed `# forces
      replacement` and classified as `replacement-sensitive`

- extra_mount: introduce (none -> first extra_mount)
  - expected_provider_action: create+attach (provider may report create of mount_point)
  - mutation_class: blocked
  - authority: conservative policy (Phase 0 blocks first-additive mounts until explicit in-place proof exists)
  - evidence: attempted introduction on `test-storage` classified and treated as blocked in Phase 0

- extra_mount: increase size
  - expected_provider_action: for the approved ZFS-backed operational workflow,
    desired-state update plus Proxmox-native `pct resize` returns the stack to
    a post-resize no-op `terragrunt plan`; direct provider-managed
    `mount_point.size` reconciliation remains unsafe under the current provider
  - mutation_class: safe-in-place
  - authority: authoritative for the current `pve-test` ZFS-backed
    `platform-zfs` + `durable-zfs` workflow on an already-existing extra mount
  - evidence: `test-storage-extra` was created with
    `mp1=/srv/test-extra,size=8G` on `infrastructure-containers`, then the
    desired size in `terraform/lxc/stacks/test-storage-extra/stack.yaml` was
    updated to `16G` and the operational workflow
    `./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack test-storage-extra --mount-path /srv/test-extra'`
    completed successfully. Live verification showed
    `pct config 151` reporting
    `mp1: infrastructure-containers:subvol-151-disk-2,mp=/srv/test-extra,size=16G`,
    guest `df -h /srv/test-extra` reported `16G`, and the post-resize
    `terragrunt plan -no-color` for the stack returned `No changes.`
    The same operational grow-only path is now also proved on the first real
    infrastructure stack: `proxy-stack` was rebuilt onto
    `platform-zfs` + `durable-zfs`, its existing extra mount at
    `/opt/proxy-stack/certs` was grown live from `5G` to `10G` with
    `./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack proxy-stack --mount-path /opt/proxy-stack/certs'`,
    `pct config 30010` reported
    `mp1: infrastructure-containers:subvol-30010-disk-2,mp=/opt/proxy-stack/certs,size=10G`,
    guest `df -h /opt/proxy-stack/certs` reported `10G`, the expected cert/state
    files remained present, and the post-resize
    `terragrunt plan -no-color` for `terraform/lxc/stacks/proxy-stack` returned
    `No changes.`
    On `harbor-stack`, the same operational sequence was attempted after the
    stack was rebuilt onto `platform-zfs` + `durable-zfs` and the desired extra
    mount size was increased from `100G` to `120G`. The live run updated
    `pct config 40010` to
    `mp1: infrastructure-containers:subvol-40010-disk-2,mp=/var/lib/harbor,size=120G`,
    the backing dataset `infrastructure/subvol-40010-disk-2` reported
    `refquota=120G`, Harbor health still passed, and the post-resize
    `terragrunt plan -no-color` returned `No changes.` However, guest-visible
    capacity at `/var/lib/harbor` remained capped at about `65.3G` because the
    underlying `infrastructure` zpool only had about `78.8G` free at the time
    of the test. This is an environment-capacity caveat, not a new contract
    proof target, so it should not be used as the authoritative guest-visible
    growth evidence for the workflow.

- mount_point: path change
  - expected_provider_action: replacement or provider-reported delete/create
  - mutation_class: blocked
  - authority: conservative policy (path changes are blocked in Phase 0)
  - evidence: path changes risk data-masking and provider delete/create semantics; Phase 0 policy maps path changes to `blocked` unless scope is explicitly widened

- docker_mount: change backend/profile
  - expected_provider_action: replacement-sensitive or blocked
  - mutation_class: blocked
  - authority: conservative policy (backend/profile changes are blocked in Phase 0)
  - evidence: attempt to change `docker_storage` mapping

- second_extra_mount: request
  - expected_provider_action: undefined in current module
  - mutation_class: blocked
  - authority: authoritative (module shape enforces at most one optional extra mount)
  - evidence: negative test asserting validation rejects request; NOTE: a
    request for a second extra mount is also out-of-scope for Phase 0 policy
    testing under the current module shape and is therefore treated as
    `blocked` by policy.

- mount_point: remove
  - expected_provider_action: provider-reported delete of mount_point resource and possible downstream resource changes
  - mutation_class: blocked
  - authority: conservative policy (removals are blocked in Phase 0)
  - evidence: no Phase 0 provider-backed safe-removal proof; removals are conservatively blocked and must include explicit backup/restore handling in Phase 1

Notes
-----
- Backend differences (local-lvm vs directory vs zfs) are proximate causes of
  differing provider behavior. Tests must capture backend mapping via
  `storage/pve-test.yaml` and ensure the matrix records actual provider outputs.
- The currently approved ZFS-backed grow-only workflow for non-rootfs mounts is
  operational rather than provider-managed: update the desired size in
  `stack.yaml`, run the Proxmox-native resize, verify the guest, then confirm a
  no-op `terragrunt plan`. Direct provider-managed `mount_point.size` changes
  remain replacement-sensitive.
- This approved operational workflow is now proved on `pve-test` for both:
  - the Docker mount at `/var/lib/docker`
  - an already-existing extra mount at `/srv/test-extra`
- Real stacks that still resolve extra-mount storage through `durable-default`
  (`local-lvm`) must remain on `resize_control_plane: provider` until they are
  rebuilt onto `durable-zfs` and revalidated against the approved operational
  workflow.
- If plan JSON is ambiguous, classifier must default to `blocked`.
