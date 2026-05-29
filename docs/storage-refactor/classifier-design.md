# Phase 0 — Classifier Design Draft

Purpose
-------

Consume a targeted `terragrunt plan` / `terraform show -json` artifact for a
single stack and classify storage-relevant field transitions into one of:
- `safe-in-place`
- `reboot-required`
- `replacement-sensitive`
- `blocked`

Inputs
------
- stack manifest path (stack.yaml)
- rendered storage manifest (`terraform/lxc/storage/pve-test.yaml`)
- machine-readable plan JSON (`terraform show -json` or saved plan file)

Processing
----------
1. Extract provider-level resource diffs for `proxmox_virtual_environment_container` and any related `mount_point` entries.
2. For each storage-related field transition (rootfs size, mount_point size, mount_point path, mount_point volume), map provider `actions` and `change` details to a canonical field_transition key.
3. Consult the Phase 0 mutation matrix to map field_transition -> mutation_class.
4. If provider action is ambiguous or missing, map to `blocked`.
5. Persist classifier output as JSON with:
   - stack_name
   - timestamp
   - storage_manifest_snapshot
   - plan_snapshot (path)
   - extracted_diffs
   - classified_transitions

Output
------
- Classifier output should be machine-readable JSON intended for audit, but
  transient proof artifacts must not be committed into tracked docs paths by
  default. Recommended destinations:
  - ephemeral local paths (for example `/tmp/test-storage-classified.json`) for
    interactive passes
  - CI or artifact storage for durable runs (attach links in the hand-back)
  - a tracked fixture only when the classification output is intentionally
    preserved as a repeatable test vector; include a short rationale in the
    same commit explaining why the fixture is durable and how to regenerate it.

  The classifier CLI should accept an `--out` path so callers can choose an
  appropriate transient or persistent destination. A CLI implementation now
  exists at `terraform/lxc/classify-storage-plan.py` and accepts `--plan-json`
  and `--out` as documented in the script header.

Fixture note
-------------

If a tracked fixture appears under `docs/storage-refactor/fixtures/`, that
fixture must not be treated as authoritative Phase 0 proof. Fixtures are
allowed as lightweight, repeatable test vectors for the classifier only.

- Durable provider-backed evidence must come from `terragrunt plan` /
  `terraform show -json` output captured from the `test-storage` stack and
  stored outside of tracked `docs/` paths (for example, ephemeral `/tmp`
  artifacts or CI-attached build artifacts). The classifier may consume
  fixtures for unit testing, but Phase 0 capability claims must reference
  provider-backed plan output recorded during the dedicated `test-storage`
  runs.

Authority note
--------------

- The classifier is a conservative helper intended to extract and map plan
  fields to mutation classes for Phase 0 audit convenience. It is _not_ a
  substitute for real provider-backed plan evidence. For authoritative Phase
  0 results, use the provider-backed `terragrunt plan` / `terraform show -json`
  output from the target stack under `pve-test`. Fixtures or classifier output
  are useful test vectors, but the provider-backed plan artifacts are the
  authoritative source of truth for Phase 0 capability decisions.

Next steps
----------
- The classifier CLI is implemented at `terraform/lxc/classify-storage-plan.py`.
- Wire the classifier into the Phase 0 test harness so each `terragrunt plan`
  for `test-storage` produces an evidence artifact consumed by the hand-back.
