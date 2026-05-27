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
  - authority: conservative policy (no provider-backed proof in this pass)
  - evidence: No provider-backed `terragrunt plan` for `rootfs_size` increase
    was produced in this branch's Phase 0 pass; downgraded to conservative
    policy until an authoritative provider-backed plan is captured.

- docker_mount: increase size
  - expected_provider_action: provider may report replacement for the current `pve-test` backend (replace of the container resource)
  - mutation_class: replacement-sensitive
  - authority: authoritative (observed on current `pve-test` profile)
  - evidence: `docker_storage_size` increase on `test-storage` produced a provider replace in the observed plan output

- extra_mount: introduce (none -> first extra_mount)
  - expected_provider_action: create+attach (provider may report create of mount_point)
  - mutation_class: blocked
  - authority: conservative policy (Phase 0 blocks first-additive mounts until explicit in-place proof exists)
  - evidence: attempted introduction on `test-storage` classified and treated as blocked in Phase 0

- extra_mount: increase size
  - expected_provider_action: provider-dependent; may be in-place or require replacement depending on backend/profile
  - mutation_class: blocked
  - authority: conservative policy (no Phase 0 in-place proof for extra-mount growth on current backends)
  - evidence: no provider-backed non-replacing plan observed for extra-mount size increases on the current `pve-test` profile

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
- If plan JSON is ambiguous, classifier must default to `blocked`.
