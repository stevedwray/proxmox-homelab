# Plan Revision Brief

## Purpose

This document briefs a new session on the changes required to the homelab build plan
following a review of the current state of pve-test, the development pass observations,
and a set of architectural and scoping decisions made during that review.

The new session performs **planning and document work only** — no deployment, no Terraform,
no Ansible. The deliverable is an updated, self-consistent set of plan documents ready for
the next development pass on pve-test.

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

## Documents to read before making any changes

Read all of these in full before touching any file.

### Architecture and planning

- `docs/plans/GreenField.md` — full architecture rationale, technology selection, phase
  sequence, target operating model
- `docs/plans/NetworkPlanning.md` — network zone model, SDN options, recommended zone
  design, traffic policy shape
- `docs/plans/Observations.md` — running notes from the development pass; decisions made
  under time pressure, patterns that worked, known gaps

### Phase plan documents

- `docs/plan/README.md` — phase index, services table, repository conventions
- `docs/plan/phase-04-core-shared-services.md` — Phase 04 goal, service specs, IP
  allocation table, compose excerpts, acceptance criteria
- `docs/plan/phase-05-supply-chain.md` — Phase 05 goal and task breakdown

### Current task files (active)

- `docs/plan/tasks/04-core-services-01-deploy-authentik.md`
- `docs/plan/tasks/04-core-services-02-deploy-headscale.md`
- `docs/plan/tasks/04-core-services-03-deploy-traefik.md` ← new numbering
- `docs/plan/tasks/04-core-services-04-deploy-step-ca.md` ← new numbering
- `docs/plan/tasks/04-core-services-05-deploy-monitoring.md`
- `docs/plan/tasks/05-supply-chain-01-trivy-ci-scan.md`
- `docs/plan/tasks/05-supply-chain-02-syft-sbom.md`
- `docs/plan/tasks/05-supply-chain-03-cosign-signing.md`
- `docs/plan/tasks/05-supply-chain-04-chainloop-server.md`
- `docs/plan/tasks/05-supply-chain-05-harbor-image-policy.md`

### Stale task files (also present — read to understand old numbering, then delete)

- `docs/plan/tasks/04-core-services-03-deploy-step-ca.md` ← old numbering, delete
- `docs/plan/tasks/04-core-services-04-deploy-traefik.md` ← old numbering, delete

### Completed task files (for context on what patterns are already codified)

- `docs/plan/tasks/done/` — all archived task files; read to understand what the
  deployment patterns look like and what has been validated

### Network intent

- `terraform/lxc/network/pve-test.yaml` — current SDN zone definitions for pve-test;
  the generic seg_a/b/c zones do not yet reflect the target architecture

### Reference stacks (understand the deployment pattern)

- `terraform/lxc/stacks/harbor-stack/` — canonical reference for stack.yaml and
  terragrunt.hcl format
- `terraform/lxc/stacks/authentik-stack/` — most recently deployed Phase 04 stack
- `terraform/lxc/ansible/playbooks/` — all current Ansible playbooks

---

## Required changes

Work through these in order. Each section is independent unless noted.

---

### Change 1 — SDN zone design (do this first, everything else depends on it)

This is the most important change. Every container deployed in Phase 04 and Phase 05
must have a planned, reasoned location on the SDN. vmbr0 (flat LAN) placement is not
a default — it must be a conscious decision with a recorded rationale.

**What to produce:**

Update `terraform/lxc/network/pve-test.yaml` to replace the generic `seg_a`, `seg_b`,
`seg_c` zones with named zones that reflect the target architecture.

The target zone model (from NetworkPlanning.md, Design B) is:

| Zone | Purpose | Containers |
|---|---|---|
| `mgmt_seg` | Management plane — infra services that operators and automation reach | Harbor, Authentik, step-ca, Monitoring, apt-cacher |
| `edge_seg` | Public ingress — the only path from the LAN into internal services | Traefik |
| `build_seg` | CI build workloads | ci-runner-01 (already here on seg_c) |

**Bootstrap exceptions (must be explicitly justified in the yaml):**

Some services cannot easily be placed in SDN zones due to bootstrap ordering or
IP migration constraints. For each, the placement must be documented with a rationale
comment in `pve-test.yaml`:

- **Portainer (VMID 120)**: on `vmbr0` — bootstraps everything else; SDN zones
  must exist before Portainer can be moved, creating a chicken-and-egg dependency.
  Acceptable on vmbr0 with access controlled via Authentik forward-auth (Phase 04-03).
- **Harbor (VMID 121)**: on `vmbr0` — canonical IP `192.168.1.10` shared between
  pve and pve-test; placing in an SDN zone would break the proxy cache URLs baked
  into all compose files. Registry traffic from SDN zones reaches Harbor via SNAT
  on each zone's gateway.

For each SDN zone you define, include:
- `zone_type` (use `simple` as established by existing zones)
- `subnet` and `gateway`
- `snat: true` where containers in that zone need outbound internet or LAN access
- A static route note (MikroTik `/ip route` command) where required, matching the
  pattern already documented in `pve-test.yaml` for `seg_c`

For each container in Phase 04/05, explicitly document which zone it belongs to and
why — either in `pve-test.yaml` comments or in an updated `pve-test.yaml` `zones`
section that maps zone names to their intended purpose and container membership.

---

### Change 2 — Delete stale task files

Delete these two files — they are the old numbering, superseded by the new 04-03 and
04-04 files:

- `docs/plan/tasks/04-core-services-03-deploy-step-ca.md`
- `docs/plan/tasks/04-core-services-04-deploy-traefik.md`

---

### Change 3 — Archive completed Phase 04 tasks

Move to `docs/plan/tasks/done/` and update status to DONE:

- `docs/plan/tasks/04-core-services-01-deploy-authentik.md` — deployed and healthy
- `docs/plan/tasks/04-core-services-02-deploy-headscale.md` — cancelled; already
  marked CANCELLED, archive as-is

---

### Change 4 — Update task session prompts for full bring-up sequence

pve-test is wiped between development passes. Every remaining task's session prompt
must include the steps to bring up its dependencies before beginning work on the task
itself. The deployment steps for dependencies should reference the existing playbooks
and stack files (not re-specify them in full).

**04-core-services-03-deploy-traefik.md session prompt:**
Add a "Prerequisites bring-up" step before Step 1 that:
- Sources `.env` and `.env.pve-test`
- Runs `terragrunt apply` for `harbor-stack`, `apt-cacher-stack`, `authentik-stack`
- Runs the Ansible playbooks for each in order
- Verifies Authentik health (`curl http://192.168.1.46:9000/-/health/ready/` → 204)
before proceeding

**04-core-services-04-deploy-step-ca.md session prompt:**
Add a "Prerequisites bring-up" step that brings up harbor, apt-cacher, Authentik,
and Traefik (04-03 full sequence) before beginning step-ca work.

**04-core-services-05-deploy-monitoring.md session prompt:**
Add a "Prerequisites bring-up" step that brings up the full Phase 04 stack
(harbor, apt-cacher, Authentik, Traefik, step-ca) before beginning monitoring work.

**Phase 05 task session prompts (05-01 through 05-03):**
Each must include a "Prerequisites bring-up" step that brings up the full Phase 04
stack before beginning Phase 05 work. Reference the phase-04 task session prompts
for the bring-up sequence rather than duplicating it.

---

### Change 5 — Fix monitoring task prerequisites (stale task number reference)

In `04-core-services-05-deploy-monitoring.md`, the prerequisites currently reference
`Task 04-04 complete — Traefik running`. In the new numbering, 04-04 is step-ca and
Traefik is 04-03. Update to:

- Task 04-03 complete — Traefik running at `192.168.1.43`
- Task 04-04 complete — step-ca running at `192.168.1.42` (Grafana uses the internal
  CA for its own cert via the step-ca resolver in Traefik)

---

### Change 6 — Remove Chainloop from Phase 05

Chainloop has no Docker Compose self-hosting path and will not be used.

- In `phase-05-supply-chain.md`: remove item 4 from the goal list; remove the
  Chainloop section from the body
- Cancel `05-supply-chain-04-chainloop-server.md` — update status to CANCELLED,
  record the reason (no compose self-hosting path; Chainloop Cloud requires SaaS
  dependency; deferred indefinitely)
- Do not delete the file — archive it to `done/` as a cancelled task so the decision
  is recorded

---

### Change 7 — Add SDN zone setup as a prerequisite step in Phase 04

The Phase 04 phase document (`phase-04-core-shared-services.md`) and the first
active task (`04-core-services-03-deploy-traefik.md`) must include a prerequisite
step for applying the SDN zone configuration to pve-test before any containers are
deployed.

Add to the phase-04 prerequisites section:
- SDN zones defined in `terraform/lxc/network/pve-test.yaml` applied to pve-test
- Static routes added to MikroTik router for any SDN subnets with gateways
- Verification: `pvesh get /nodes/pve-test/sdn/zones` lists expected zones

Add as Step 0 in the 04-03 session prompt: apply `pve-test.yaml` SDN configuration
and verify zones before touching any stack.

---

### Change 8 — Update README.md

`docs/plan/README.md` contains several stale entries:

- **Services table**: remove Headscale (VMID 151) and Chainloop (VMID 155) rows
- **Services table**: update ci-runner-01 IP to `10.57.0.63` if not already correct
- **Phase 06 row**: add a note — "Out of scope for this plan. Phase 04/05 establishes
  the platform basis. App stack migration is a separate planning effort."
- **Open issues summary**: replace the stale list (referencing old closed issues #23,
  #25, #26 etc.) with the current open issues relevant to Phase 04/05

Current open issues relevant to this plan:

| Issue | Description | Phase | Action |
|---|---|---|---|
| #89 | Phase 02 service verification | 02 | Close — services verified healthy |
| #104 | Headscale deployment | 04 | Close — cancelled |
| #106 | Traefik deployment | 04-03 | Active |
| #107 | Monitoring deployment | 04-05 | Active (note: was 04-04 in old numbering) |
| #108 | Trivy CI scan | 05-01 | Active |
| #109 | Syft SBOM | 05-02 | Active |
| #110 | Cosign signing | 05-03 | Active |
| #111 | Chainloop server | 05-04 | Close — cancelled |
| #120 | ShellCheck cleanup: setup-dev-env.sh | — | Ready to work (ShellCheck available locally) |
| #121 | ShellCheck cleanup: check-proxmox-status.sh | — | Ready to work |

Close issues #89, #104, and #111 via `gh issue close` with a comment explaining why.

---

### Change 9 — Network zone placement in each task file

For every remaining task file that deploys a container, add a **Network placement**
section between Prerequisites and Objective that specifies:

- Which SDN zone the container belongs to
- The IP address and how it was chosen (IPAM check, ping verify)
- Any cross-zone routing required (e.g. Traefik in edge_seg reaching Authentik in mgmt_seg)
- The firewall policy intent (what traffic is allowed in/out of this container)

This section should be present in:
- `04-core-services-03-deploy-traefik.md`
- `04-core-services-04-deploy-step-ca.md`
- `04-core-services-05-deploy-monitoring.md`
- `05-supply-chain-01-trivy-ci-scan.md`
- `05-supply-chain-02-syft-sbom.md`
- `05-supply-chain-03-cosign-signing.md`

Phase 05 tasks do not deploy new containers (they add CI jobs and tooling to the
existing ci-runner-01), so their network placement section is brief: reference
ci-runner-01's existing zone placement and note that no new network configuration
is required.

---

## Constraints for the new session

- Do not deploy anything. This is a document revision session.
- Do not invent IP addresses or zone subnets without grounding them in the existing
  `pve-test.yaml` patterns and the NetworkPlanning.md recommendations.
- Do not remove content from Observations.md — it is a reference document that
  informs the plan, not a document to be updated in this session.
- When making choices about SDN zone subnets, follow the pattern established by
  `seg_c` in `pve-test.yaml` (simple zone, /24 subnet, SNAT enabled, MikroTik
  static route documented).
- The MikroTik router is at `192.168.1.1`. pve-test is at `192.168.1.40`. Any
  SDN zone with a gateway needs a static route on the MikroTik pointing the
  subnet back to `192.168.1.40`.
