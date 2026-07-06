# Environment Isolation — Plan

Status: **not started.** Scoped out deliberately as its own task, separate
from the 2026-07-06 incident session. See [decisions.md](./decisions.md)
for why the migration is lower-risk than it first appears.

## Key finding that shapes this whole plan (2026-07-07)

Checked `technitium-stack`'s actual Terraform state before assuming the
worst. Both environments' containers **are** already cleanly tracked —
just via Terraform workspace name instead of isolated directories:

| Workspace | State location | Tracks | Confirmed via |
|---|---|---|---|
| `default` | `stacks/technitium-stack/terraform.tfstate` | `pve-test-vm`'s container (`vmid=20015`, MAC `BC:24:11:16:6C:8C`) | `network_interface` attribute in state |
| `pve` | `stacks/technitium-stack/terraform.tfstate.d/pve/terraform.tfstate` | production's container (`vmid=20015`, MAC `BC:24:11:CB:74:A2`) | same |

**No resources are missing, conflated, or need `terraform import`.** This
means the migration is a **state relocation** (copy each workspace's
existing, correct state into its own new isolated directory, verify with a
zero-diff `plan`, then retire the old shared location) — not a riskier
"reconstruct state from scratch" operation. Confirm this same shape holds
for any other stack before assuming it generalizes.

## Phase 0 — Confirm scope (done)

- 11 stacks lack the per-environment layout; only `technitium-stack` is a
  genuine dual-environment gap (see `current-state.md`'s classification
  table). This phase is complete — no further inventory work needed before
  starting Phase 1.

## Phase 1 — Scaffold the new per-environment Terragrunt directories

Mirror `dns-stack` exactly (see `current-state.md`'s reference
`terragrunt.hcl`):

1. `terraform/lxc/environments/pve/technitium-stack/terragrunt.hcl`
2. `terraform/lxc/environments/pve-test-vm/technitium-stack/terragrunt.hcl`

Both are near-identical to `dns-stack`'s, substituting `technitium-stack`
for `dns-stack` (the `basename(get_terragrunt_dir())` calls make this
automatic — no stack-specific content needed in the `.hcl` itself).

This phase is purely additive — creating these files does not affect the
old `stacks/technitium-stack/terragrunt.hcl` or any live resource. Safe to
do first, independent of the state migration below.

## Phase 2 — Pilot the state-relocation procedure on `pve-test-vm` first

Goal: prove the relocation procedure produces a zero-diff `plan` before
ever touching production's tracked state.

1. `cd terraform/lxc/environments/pve-test-vm/technitium-stack && terragrunt init`
   (this will want to create a *new*, empty state at the new
   `generated_dir` location — do not let it apply yet).
2. Copy the **existing** `default`-workspace state
   (`stacks/technitium-stack/terraform.tfstate`) into the new location as
   its starting state (`terraform state push` from the old file, or copy
   the raw file if backend types match — confirm which applies once
   actually doing this, don't assume).
3. **Safety gate**: `PVE_ENV=pve-test-vm terragrunt plan` from the new
   directory. This must show **zero** proposed changes — especially no
   `destroy` or `create` for `proxmox_virtual_environment_container.docker_host`.
   If it shows anything other than a clean no-op, stop. Do not apply. The
   whole point of this procedure is that the live container is never
   touched.
4. Confirm the new location's generated `inventory.yml` matches the
   manually-placed stopgap file from the 2026-07-06 session exactly (same
   `ansible_host`, `pve_host`, etc.) — if it doesn't, that's a sign the
   stopgap file itself had an error, not that the migration is wrong;
   reconcile before proceeding.
5. Only after step 3's zero-diff plan is confirmed: remove the manually-
   placed stopgap `inventory.yml` (it's now superseded by the properly
   Terraform-generated one at the same path) and retire (rename, don't
   delete) the old `default`-workspace state file.

## Phase 3 — Repeat for production, with explicit approval

Same procedure as Phase 2, but against the `pve` workspace's state and
using `./with-secrets-prod`. This is a production Terraform state change —
per `CLAUDE.md`'s Production Credential Controls, it needs a preflight
summary and explicit operator approval before the `terragrunt init`/`plan`
sequence runs with production credentials, even though the goal is a
zero-diff no-op. Do not skip the `plan`-shows-nothing safety gate just
because Phase 2 succeeded — production's state file is not guaranteed
identical in shape.

## Phase 4 — Full teardown/redeploy validation gate

Per `CLAUDE.md`'s Validation Tiers table, this is a Terraform-class
change: a full teardown cycle on `pve-test-vm` (per
`docs/teardown-test/repeatable-test.md`) is required before promoting to
`stable`, proving the new per-environment layout survives a real
destroy/recreate cycle, not just a `plan` no-op.

## Phase 5 — Close the process gap (prevents recurrence for future stacks)

The bigger risk isn't just `technitium-stack` — it's that nothing stops
the *next* new SDN-VLAN stack from being scaffolded the same
non-environment-scoped way. Options to evaluate:

- Add an explicit note to `terraform/lxc/PLATFORM_CONTRACT.md` requiring
  the per-environment layout for any stack with a `network:` zone, with a
  pointer to this incident as the reason.
- Consider whether `scripts/provision.sh`'s fallback-to-shared-inventory
  path (`STACKS_DIR`) should eventually be removed entirely for
  `network:`-zoned stacks once migration is complete — turning today's
  guardrail (loud failure) into an actual structural impossibility (no
  fallback path to hit at all). Do this only after confirming no other
  legitimate stack still depends on the fallback.
- If a repo scaffolding script/template exists for new stacks, make sure
  it generates the per-environment `terragrunt.hcl` pair by default.

## Phase 6 — Closeout

Fold conclusions into `terraform/lxc/PLATFORM_CONTRACT.md` and
`terraform/lxc/README.md`, then archive this workspace.

## Open questions

- Does `terraform state push`/raw file copy work cleanly given the
  `bpg/proxmox` provider and OpenTofu version in use, or is a different
  state-migration mechanism needed? Confirm during Phase 2, don't assume.
- Should `dhcp-test-client-01` get a formal `environments/pve-test-vm/`
  entry too, or is it acceptable to leave it as a stopgap-guarded
  exception given it's disposable? Low priority either way.
- Should physical/`pve`-only stacks (the 9 with no `network:` zone) get an
  explicit `stack.yaml` marker (e.g. `environment_scope: pve-only`) so
  their exemption from this whole category of risk is declared, not just
  inferred from the absence of a `network:` section? Would make the
  guardrail's logic more self-documenting.
