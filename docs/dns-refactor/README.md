# DNS Refactor — CoreDNS to Technitium Migration

## Purpose

Plan and track migrating the internal authoritative DNS service (currently
`dns-stack`, running CoreDNS) to Technitium DNS Server.

## Status

**Phase 0 complete, Phase 1 complete, Phase 2 complete, Phase 3 rehearsal
complete, and Phase 4 teardown/redeploy validation complete on
`pve-test-vm` (2026-07-04). Production (`pve`) parallel bring-up and DNS
delegate cutover are now complete.**
All Phase 0 decisions are recorded in [decisions.md](./decisions.md):
Technitium over CoreDNS (unified DNS+DHCP path, web UI, DoH/DoT/DNSSEC),
Docker Compose deployment shape, and a new-VMID parity window (not an
in-place swap). `terraform/lxc/stacks/technitium-stack/` is deployed on
`pve-test-vm` at `192.168.20.115`, served through
`https://technitium.test.gibbsgreatly.xyz`, and integrated with Authentik
via native OIDC. Initial bring-up uses a separate Technitium-only bootstrap
zone (`TECHNITIUM_BOOTSTRAP_ZONE`, default `tech.${LAB_DOMAIN}`; on
`pve-test-vm`, `tech.test.gibbsgreatly.xyz`) while CoreDNS remains live for
the router path.

Phase 2 added a formal direct-query parity verifier:
`terraform/lxc/stacks/technitium-stack/verify-parity.sh`. It checks the
important `test.gibbsgreatly.xyz` names directly against Technitium,
including browser-routed names, direct/internal names, bootstrap-zone
resolution, and public recursion.

Phase 3 rehearsal is now also complete on `pve-test-vm`: the MikroTik
`test-zone-delegate` rule was repointed from CoreDNS (`192.168.20.113`) to
Technitium (`192.168.20.115`), and resolver-path checks through
`192.168.1.1` succeeded for browser-routed names, direct/internal names,
and public recursion.

Phase 4 is now also complete: the full teardown/redeploy harness passed on
stamp `20260703-220525`, including platform destroy/recreate, stack
provisioning, delegated/authoritative DNS checks, Harbor/Portainer/Authentik
smokes, and a final `reconcile-edge.py` dry-run. Browser validation also
confirmed the main routed services were healthy after the harness pass. The
next gate is production parity/cutover prep, not more test-environment
discovery work.

Production parallel bring-up is now complete as well: `technitium-stack`
is live on `pve` at `192.168.20.15`, provisioned successfully, and serving
direct-query parity answers for `lab.gibbsgreatly.xyz`.

Production cutover was then completed by repointing the MikroTik
`lab-zone-delegate` rule (`*45`) from CoreDNS `192.168.20.13` to
Technitium `192.168.20.15` and flushing the router DNS cache. Post-cutover
resolver-path checks through `192.168.1.1` succeeded for:

- browser-routed names: `traefik`, `authentik`, `harbor`, `netbox`,
  `portainer` -> `192.168.30.10`
- authority records: `dns`, `ns1` -> `192.168.20.15`
- direct/internal names: `authentik-int` -> `192.168.20.10`,
  `step-ca` -> `192.168.20.11`
- public recursion: `github.com` -> non-empty answer

CoreDNS is no longer the active production delegate target; it remains
deployed only as the old parallel authority/rollback point. One follow-up
was identified immediately after cutover: the Technitium browser route
returned a Traefik `404`, which traced back to unpublished production edge
output for `technitium-stack`. Republishing the generated Traefik config to
`proxy-stack` restored `https://technitium.lab.gibbsgreatly.xyz`
successfully. A follow-up read-only `reconcile-edge.py` dry-run still
reports Authentik metadata drift for the Technitium app's launch host
(`test` vs `lab`), but the live DNS cutover and browser route are both
healthy.

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
| `production-cutover-packet.md` | direct parity verification command set, executed production MikroTik cutover record, and rollback steps |
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
  table, a **full teardown cycle on `pve-test-vm`** was the minimum
  validation before promoting to `stable`; that gate is now satisfied by the
  successful `20260703-220525` evidence set.
- DNS is deployed 3rd in the platform deploy order and destroyed 9th of 11 (see
  current-state.md) — nearly everything else depends on it. Cutover sequencing
  needs explicit design in `plan.md` before any destructive validation run.
- `pve` production parallel bring-up and the MikroTik delegate cutover have
  now both been exercised successfully.
- The remaining production work is limited to post-cutover Authentik edge
  metadata cleanup for Technitium, not more DNS-stack scaffolding.

## Closeout

When this workspace's plan is either implemented and promoted, or explicitly
abandoned, fold the durable conclusions into `docs/design/network.md` and
`docs/plan/phase-04b-internal-dns.md` (retitled/rewritten for Technitium), then
remove or archive this workspace per the documentation workspace pattern.
