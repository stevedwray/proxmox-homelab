# DNS Refactor — CoreDNS to Technitium Migration

## Purpose

Plan and track migrating the internal authoritative DNS service (currently
`dns-stack`, running CoreDNS) to Technitium DNS Server.

## Status

**Phase 0 complete, Phase 1 scaffold in progress (2026-07-03).** All Phase 0
decisions are recorded in [decisions.md](./decisions.md): Technitium over
CoreDNS (unified DNS+DHCP path, web UI, DoH/DoT/DNSSEC), Docker Compose
deployment shape, and a new-VMID parity window (not an in-place swap).
`terraform/lxc/stacks/technitium-stack/` now exists with a
`STACK_CONTRACT.md`, `stack.yaml` (VMID `20015`), `terragrunt.hcl`,
`smoke-test.sh`, and a `deploy-technitium-stack` Ansible playbook
(syntax-checked, not yet run against a live host). `LAB_IP_TECHNITIUM` /
`TF_VAR_lab_ip_technitium` are wired through `variables.tf`, `main.tf`, and
the `.env*.template` files — **the real gitignored `.env` /
`.env.pve-test-vm` files still need the operator to copy the new
`LAB_IP_TECHNITIUM` line in before a `terragrunt plan/apply` will pick it
up.** Initial bring-up now uses a separate Technitium-only bootstrap zone
(`TECHNITIUM_BOOTSTRAP_ZONE`, default `tech.${LAB_DOMAIN}`; on
`pve-test-vm`, `tech.test.gibbsgreatly.xyz`) for direct queries only.
Nothing has been deployed or applied yet; this stack does not touch
`dns-stack` or the MikroTik FWD rule.

**Stated program end goal:** Technitium eventually replaces MikroTik as DHCP
server too, not just DNS authority. That's out of scope for this workspace
(DHCP today only runs on the physical LAN `bridgeLocal`, a separate domain
from the SDN container VLANs this workspace covers) but current decisions
must not preclude it — see plan.md's "Future: DHCP takeover from MikroTik"
section before finalizing Technitium's network identity or stack sizing.

## Workspace layout

This follows the repo-wide pattern in
[docs/workflow/documentation-workspaces.md](../workflow/documentation-workspaces.md):

| File | Purpose |
|---|---|
| `README.md` | this file — entry point, status, reading order |
| `current-state.md` | accurate baseline of the *current* CoreDNS `dns-stack` — what a replacement must account for |
| `plan.md` | phased migration plan |
| `decisions.md` | ADR-style log of Technitium-specific design decisions, as they're made |
| `artifacts/` | local-only, git-ignored (`docs/**/artifacts/`) — put transient session handoffs, scratch notes, and evidence here, not in tracked docs |

## Read these first

Before planning, a session should read, in order:

1. This file
2. [current-state.md](./current-state.md) — what the current CoreDNS deployment actually does
3. [docs/design/network.md](../design/network.md) — DNS section: two-tier MikroTik + authoritative-server model, namespaces, per-zone resolver config
4. [docs/design/architecture.md](../design/architecture.md) — FRs/ADRs/threat model (note: there is currently no explicit FR or ADR for the DNS service choice — see decisions.md)
5. [terraform/lxc/README.md](../../terraform/lxc/README.md) and [terraform/lxc/PLATFORM_CONTRACT.md](../../terraform/lxc/PLATFORM_CONTRACT.md) — how `stack.yaml`-driven Terraform/Ansible provisioning works, needed once this moves from planning to a `technitium-stack` scaffold
6. [docs/teardown-test/inventory.md](../teardown-test/inventory.md) — authoritative current stack deploy/destroy order and dependents (DNS is foundational — see current-state.md)

## Workflow and validation

- Branch: cut `work/dns-refactor-<topic>` (or `feat/`/`fix/` as appropriate) from current HEAD per
  [docs/workflow/branch-model.md](../workflow/branch-model.md).
- This is a Terraform / network-class change. Per `CLAUDE.md`'s Validation Tiers
  table, that means a **full teardown cycle on `pve-test-vm`** is the minimum
  validation before promoting to `stable`, not a lighter tier.
- DNS is deployed 3rd in the platform deploy order and destroyed 9th of 11 (see
  current-state.md) — nearly everything else depends on it. Cutover sequencing
  needs explicit design in `plan.md` before any destructive validation run.
- `pve` (production) is out of scope until the `pve-test-vm` teardown gate passes
  and the operator explicitly approves a production migration task.

## Closeout

When this workspace's plan is either implemented and promoted, or explicitly
abandoned, fold the durable conclusions into `docs/design/network.md` and
`docs/plan/phase-04b-internal-dns.md` (retitled/rewritten for Technitium), then
remove or archive this workspace per the documentation workspace pattern.
