# Copilot Follow-Up Prompt

Continue the storage refactor already in progress in
`/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/storage-refactor/copilot-init-prompt.md`

Then inspect the current in-progress implementation and fix the next concrete
gaps rather than redesigning the whole refactor.

Current priority

The manifest-driven storage refactor is mostly in place. The next job is to
close the remaining contract and validation gaps so the branch is internally
consistent and ready for deeper validation.

Address these items in order:

1. Restore the harness boundary between source-only and live validation.
   - `scripts/teardown-deploy-test.sh` still defines `source-preflight` as
     source-only.
   - The new storage validation currently performs live Proxmox API checks from
     `source-preflight`.
   - Fix this by preserving the documented split:
     - `source-preflight` should remain source-only/offline-safe.
     - live Proxmox storage/backend/template checks should run from
       `live-preflight`, or the validator should support an explicit offline
       mode for source-only use plus a live mode for live-preflight.
   - Update any affected docs if the contract changes.

2. Fix transitional compatibility in `terraform/lxc/validate-storage-contract.py`.
   - The validator resolves `extra_mount_profile` one way, but later recomputes
     required-content metadata using a different fallback path.
   - Make the validator use one resolved profile path consistently, including
     legacy `extra_mount_storage` mappings.
   - Prefer one explicit resolved variable over duplicating fallback logic.

3. Clean up stale storage-teaching docs that still name physical backends as
   the normal authoring model.
   - Start with `terraform/lxc/stacks/netbox-stack/README.md`.
   - Grep for remaining docs that still teach `infrastructure-containers`,
     `storage-template`, `rootfs_storage`, `extra_mount_storage`, or
     `ostemplate` as the preferred interface and update the ones that are now
     incorrect.
   - Historical/refactor-planning docs can stay historical; active user-facing
     docs should reflect the new intent model.

4. Re-run the appropriate non-destructive checks for the updated behavior.
   - Run source-only checks for the source-only path.
   - Run live read-only checks for the live path.
   - Re-run Python syntax validation for the validator.
   - Re-run any targeted Terraform formatting/validation steps that are safe in
     the current environment.

Working rules

- Do not restart the refactor from scratch.
- Keep the manifest-driven storage model.
- Keep stack intent fields (`storage_profile`, `template_name`,
  `extra_mount_profile`) as the preferred contract.
- Make reasonable implementation choices without asking for routine approval.
- Surface only real blockers or decisions with meaningful consequences.
- Do not touch the unrelated local change in `next-session.md`.

Definition of done for this pass

- `source-preflight` is source-only again, or its contract is explicitly and
  correctly redefined everywhere.
- live storage validation is still available in the harness.
- validator profile resolution is internally consistent for legacy extra-mount
  compatibility.
- stale active docs teaching physical storage backends are updated.
- the follow-up checks you ran and their outcomes are summarized clearly.
