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
- `storage_profile`: `platform-default`

Usage notes
-----------

- Keep this stack out of the broad teardown/redeploy inventory by leaving it
  absent from `docs/teardown-test/inventory.md` unless explicitly opt-in for a
  validation run.
- Phase 0 mutation exercises will modify this stack's `stack.yaml` transiently
  as part of planned tests; the stack directory remains a normal tracked stack
  shape and must not gain special-case module inputs.
