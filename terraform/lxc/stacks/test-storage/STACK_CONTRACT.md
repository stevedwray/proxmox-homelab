# test-storage — Dedicated storage-validation LXC

Purpose
-------

This tracked stack is the dedicated storage-validation target for the
`docs/storage-refactor` capability and mutation exercises. It intentionally
starts in the Docker-only shape and will be mutated during Phase 0 to exercise
attach/grow workflows.

Contract
--------

- `hostname`: test-storage
- `network.zone`: `build_seg` (normal SDN/VLAN-backed zone)
- `deployment_tier`: `platform`
- `storage_profile`: `platform-zfs`
- `extra_mount_profile`: `durable-zfs`
- `docker_mount.logical_name`: `docker-data`
- `docker_mount.path`: `/var/lib/docker`
- `docker_mount.size`: `24G`
- `docker_mount.resize_control_plane`: `operational`
- `docker_mount.mutation_policy`: `grow-only`

Usage notes
-----------

- Keep this stack out of the broad teardown/redeploy inventory by leaving it
  absent from `docs/teardown-test/inventory.md` unless explicitly opt-in for a
  validation run.
- This tracked baseline now targets the ZFS-backed
  `infrastructure-containers` pool via `platform-zfs` so Docker mount growth
  can be tested against a ZFS backend without inventing a special-case module
  path.
- The tracked `docker_mount` block is the source of truth for the supported
  operational resize workflow. The legacy `docker_storage_size` field remains
  present only for compatibility with the current module inputs and must stay
  aligned with `docker_mount.size`.
- Phase 0 mutation exercises will modify this stack's `stack.yaml` transiently
  as part of planned tests; the stack directory remains a normal tracked stack
  shape and must not gain special-case module inputs.
