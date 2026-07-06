# Environment Isolation — Per-Environment Terragrunt Migration

## Purpose

Close the structural gap that let a `pve-test-vm`-intended deploy silently
land on production `pve` on 2026-07-06 (see
[docs/dhcp-refactor/decisions.md](../dhcp-refactor/decisions.md) Decision
5's incident note): give every stack that genuinely runs a separate
instance per environment its own isolated Terraform state and generated
inventory, the same way 25 of the repo's 36 stacks already work. Right now
a same-session software guardrail (`scripts/provision.sh`'s
`assert_inventory_matches_env`) converts a silent misdirect into a loud
failure — this workspace is for the actual fix, not the guardrail.

## Status

**Opened 2026-07-07. Not started.** This is deliberately scoped out as its
own planned task rather than done in the same session as the incident that
motivated it — see the operator's own call in that session.

**Scope finding (2026-07-07):** of the 11 stacks not on the per-environment
layout, only **`technitium-stack`** is a genuine dual-environment gap.
`dhcp-test-client-01` has an SDN zone too, but it is Stage A's disposable
DHCP-refactor test fixture — inherently `pve-test-vm`-only by design, never
meant to exist on `pve`, and already correctly blocked from ever reaching
production by the same guardrail. The other 9 (`analysis-stack`,
`cloud-stack`, `elastic-stack`, `gaming-stack`, `headscale-stack`,
`management-stack`, `media-stack`, `security-stack`, `torrent-stack`) have
no `network:` zone in `stack.yaml` at all — they are physical/`pve`-only
LXCs with no test-environment counterpart, so there's nothing to isolate.
**The real migration work here is one stack: `technitium-stack`.** The
larger value of this workspace is fixing the *process* gap (new SDN-VLAN
stacks can currently be scaffolded without this layout, as
`technitium-stack` was) so this doesn't recur for the next new stack.

## Workspace layout

Follows [docs/workflow/documentation-workspaces.md](../workflow/documentation-workspaces.md):

| File | Purpose |
|---|---|
| `README.md` | this file — entry point, status, scope finding |
| `current-state.md` | how the per-environment layout works today (25 stacks), why `technitium-stack` fell through, and the interim mitigations already in place |
| `plan.md` | phased migration plan, including the safe Terraform-state-migration procedure |
| `decisions.md` | ADR-style log of decisions as they're made |
| `artifacts/` | local-only, git-ignored — transient notes, not tracked docs |

## Read these first

1. This file
2. [docs/dhcp-refactor/decisions.md](../dhcp-refactor/decisions.md)
   Decision 5's incident note — the concrete failure this workspace exists
   to prevent from recurring
3. [current-state.md](./current-state.md) — the mechanics of the working
   pattern (`dns-stack`) vs. the broken one (`technitium-stack`)
4. [terraform/lxc/PLATFORM_CONTRACT.md](../../terraform/lxc/PLATFORM_CONTRACT.md) —
   platform conventions this workspace should eventually update
5. [plan.md](./plan.md) — the migration procedure itself

## Workflow and validation

- This is a Terraform-state-changing change once it moves past planning —
  per `CLAUDE.md`'s Validation Tiers table, that means a full teardown
  cycle on `pve-test-vm` before promotion, same bar the DNS and DHCP
  refactors used.
- State migration is the genuinely risky part (moving a *live* resource's
  Terraform state without triggering destroy/recreate) — see plan.md's
  explicit safety gate (a `plan` showing zero destroy/create actions,
  checked before any `apply`).
- Pilot the migration procedure on a low-stakes or disposable stack before
  touching `technitium-stack`'s real, currently-live-in-production
  resource.

## Closeout

When the migration is complete and the scaffolding-convention gap is
closed (new SDN-VLAN stacks can no longer be created without the
per-environment layout), fold durable conclusions into
`terraform/lxc/PLATFORM_CONTRACT.md` and `terraform/lxc/README.md`, then
archive or remove this workspace per the documentation workspace pattern.
