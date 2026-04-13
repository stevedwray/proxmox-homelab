# Plan Revision Brief

## Status

**COMPLETE.** All nine changes were executed and merged to `dev/pve-test` in commit
`03f40d3` on 2026-04-13. The only remaining action is closing three GitHub issues.

---

## Purpose

This document briefed a session on the changes required to the homelab build plan
following a review of the current state of pve-test, the development pass observations,
and a set of architectural and scoping decisions made during that review.

The session performed **planning and document work only** — no deployment, no Terraform,
no Ansible. The deliverable was an updated, self-consistent set of plan documents ready
for the next development pass on pve-test.

---

## Context

The proxmox-homelab repo implements a greenfield rebuild of a home lab using Proxmox VE,
with Terraform (Terragrunt) for LXC provisioning and Ansible for guest configuration.
A test node (`pve-test`) is used to validate patterns before promotion to the production
node (`pve`). pve-test is treated as ephemeral — it is wiped and rebuilt at the start of
each development pass.

The most recent development pass completed Phases 00b through 03c and the first two
services of Phase 04 (Authentik, step-ca). A review session identified a set of changes
needed before the next pass begins.

---

## What was done

### Change 1 — SDN zone design ✓

`terraform/lxc/network/pve-test.yaml` rewritten. The generic `seg_a`/`seg_b`/`seg_c`
zones were replaced with:

| Zone | Proxmox VNet | Subnet | Gateway | Containers |
|---|---|---|---|---|
| `mgmt_seg` | `tvmgmt` | `10.57.1.0/24` | `10.57.1.1` | Authentik (10.57.1.10), step-ca (10.57.1.11), Monitoring (10.57.1.12) |
| `edge_seg` | `tvedge` | `10.57.2.0/24` | `10.57.2.1` | Traefik (10.57.2.10) |
| `build_seg` | `tvnetc` | `10.57.0.0/24` | `10.57.0.1` | ci-runner-01 (10.57.0.63) |

vmbr0 exceptions (explicitly documented with rationale in `pve-test.yaml`):
- **Portainer (VMID 120)** — bootstrap chicken-and-egg dependency
- **Harbor (VMID 121)** — canonical IP 192.168.1.10 shared between pve and pve-test
- **apt-cacher (VMID 142)** — must be reachable from all zones as an apt proxy; SDN
  placement would require cross-zone routing from build_seg and edge_seg

MikroTik routes required (all three added to the yaml comments):
```
/ip route add dst-address=10.57.0.0/24 gateway=192.168.1.40 comment="pve-test SDN build_seg"
/ip route add dst-address=10.57.1.0/24 gateway=192.168.1.40 comment="pve-test SDN mgmt_seg"
/ip route add dst-address=10.57.2.0/24 gateway=192.168.1.40 comment="pve-test SDN edge_seg"
```

**Decisions with more than one reasonable option:**

1. **apt-cacher placement** — placed on vmbr0 rather than mgmt_seg. The brief listed it
   in mgmt_seg, but vmbr0 ensures universal reachability from all SDN zones without
   per-zone routing rules. This was the one deviation from the brief's zone table.
2. **Subnet numbering** — chose `10.57.1.0/24` / `10.57.2.0/24` continuing the
   `10.57.x.0/24` pattern. Alternative bases (e.g. 172.16.x) were possible.
3. **VNet/zone naming** — used `tvmgmt`/`tvedge` rather than `tvsega`/`tvsegb`.
   More descriptive but deviates from the old `tvnet*` short-name pattern.

### Change 2 — Delete stale task files ✓

Deleted:
- `docs/plan/tasks/04-core-services-03-deploy-step-ca.md` (old numbering)
- `docs/plan/tasks/04-core-services-04-deploy-traefik.md` (old numbering)

### Change 3 — Archive completed Phase 04 tasks ✓

Moved to `docs/plan/tasks/done/`:
- `04-core-services-01-deploy-authentik.md` — status updated to DONE
- `04-core-services-02-deploy-headscale.md` — archived as CANCELLED (already was)

### Change 4 — Update task session prompts for full bring-up sequence ✓

- `04-core-services-03-deploy-traefik.md` — added Steps 0/0b/0c/0d (SDN apply, harbor,
  apt-cacher, Authentik) with Authentik health check gate
- `04-core-services-04-deploy-step-ca.md` — added Steps 0/0b/0c/0d/0e (full 04-03
  sequence plus Traefik)
- `04-core-services-05-deploy-monitoring.md` — added Steps 0/0b/0c/0d/0e/0f (full Phase
  04 bring-up including step-ca)
- `05-supply-chain-01..03` — each references the 04-05 session prompt for the Phase 04
  bring-up sequence rather than duplicating it

### Change 5 — Fix monitoring task prerequisites ✓

In `04-core-services-05-deploy-monitoring.md`, the stale "Task 04-04 complete — Traefik
running" was replaced with:
- Task 04-03 complete — Traefik running at `10.57.2.10`
- Task 04-04 complete — step-ca running at `10.57.1.11`

### Change 6 — Remove Chainloop from Phase 05 ✓

- `phase-05-supply-chain.md`: item 4 removed from goal list; entire Part D (Chainloop)
  section removed; Part E renumbered to Part D
- `05-supply-chain-04-chainloop-server.md`: status updated to CANCELLED with full
  rationale; archived to `docs/plan/tasks/done/`

### Change 7 — Add SDN zone setup as prerequisite in Phase 04 ✓

- `phase-04-core-shared-services.md`: added "SDN zones applied to pve-test" to the
  prerequisites list; added a "SDN zone setup" subsection with MikroTik route commands
  and `pvesh` verification command
- `04-core-services-03-deploy-traefik.md`: Step 0 applies SDN config and verifies zones

### Change 8 — Update README.md ✓

- Services table: removed Headscale (VMID 151) and Chainloop (VMID 155) rows; added Zone
  column; updated all Phase 04 IPs to SDN addresses
- ci-runner-01 IP was already correct at `10.57.0.63`
- Phase 06 row: added out-of-scope note
- SDN reference line: updated from old `sdn-segment-routing.md` to `pve-test.yaml`
- Open issues summary: replaced stale list with current issues table

### Change 9 — Network zone placement in task files ✓

Network placement sections added to:
- `04-core-services-03-deploy-traefik.md` — edge_seg, 10.57.2.10, cross-zone to Authentik
- `04-core-services-04-deploy-step-ca.md` — mgmt_seg, 10.57.1.11
- `04-core-services-05-deploy-monitoring.md` — mgmt_seg, 10.57.1.12
- `05-supply-chain-01-trivy-ci-scan.md` — references ci-runner-01 in build_seg, no new config
- `05-supply-chain-02-syft-sbom.md` — same
- `05-supply-chain-03-cosign-signing.md` — same

### Ancillary changes ✓

- `terraform/lxc/stacks/authentik-stack/stack.yaml`: IP updated to 10.57.1.10/24,
  gateway 10.57.1.1, added `network: zone: mgmt_seg`
- `terraform/lxc/stacks/step-ca-stack/stack.yaml`: IP updated to 10.57.1.11/24,
  gateway 10.57.1.1, added `network: zone: mgmt_seg`
- `phase-04-core-shared-services.md`: all service IP references updated throughout

---

## Outstanding action

Close three GitHub issues. Commands to run:

```bash
gh issue close 89 --comment "Phase 02 services verified healthy. No further action required."
gh issue close 104 --comment "Headscale cancelled — no remote access requirement (lab is managed only from inside the home network). See task 04-core-services-02 archived in done/."
gh issue close 111 --comment "Chainloop cancelled — no Docker Compose self-hosting path exists. Helm/Kubernetes only. Deferred indefinitely. See task 05-supply-chain-04 archived in done/ for full analysis and viable alternatives."
```

---

## Constraints observed

- No deployment commands were run
- No Observations.md changes were made
- IP addresses and zone subnets were grounded in existing `pve-test.yaml` patterns
- The MikroTik router (192.168.1.1) and pve-test (192.168.1.40) addresses were used
  as anchors throughout
