# Homelab Build Plan — Index

This directory is the execution index for the greenfield rebuild of the proxmox-homelab.
It links the development phases, the task documents used to carry them out, and the
repository conventions that govern all changes.

**Phases describe what the IaC must support, not what is currently running.**
The running containers on pve-test are ephemeral development artefacts. See
[development-status.md](development-status.md) for an honest assessment of which
components are rebuild-safe from code today.

## Phase sequence

Phases must be completed in order unless a phase explicitly says it can run in parallel.
Each phase document owns its own prerequisites, acceptance criteria, and task breakdown.

| Phase | Document | Gate |
| --- | --- | --- |
| 00a | [Proxmox Host Bootstrap Alignment](phase-00a-proxmox-host-bootstrap.md) | — |
| 00b | [pve-test Management Bootstrap](phase-00b-pve-test-management.md) | Phase 00a complete |
| 00c | [Bootstrap Sequence (Stage 1 → Stage 2)](phase-00c-bootstrap-sequence.md) | Stage 0 (Phase 03d) complete |
| 01 | [CI Runner Deployment](phase-01-ci-runner-deployment.md) | Phase 00b complete |
| 02 | [Memory Upgrade (32 GB)](phase-02-memory-upgrade.md) | — |
| 03 | [Code Quality & Bug Fixes](phase-03-code-quality.md) | Phase 00 complete |
| 03b | [Harbor Setup: Trivy, Projects, Image Cache](phase-03b-harbor-setup.md) | Phase 00b complete |
| 03c | [Artifact Proxy (apt-cacher-ng + Terraform mirror)](phase-03c-artifact-proxy.md) | Phase 00b complete |
| 03d | [Secrets Delivery Hardening (sops exec-env)](phase-03d-secrets-hardening.md) | None — workstation only |
| 04 | [Core Shared Services](phase-04-core-shared-services.md) | Phase 00c, 03c, 03d complete |
| 04b | [Internal DNS Authority (CoreDNS)](phase-04b-internal-dns.md) | Phase 04 complete |
| 04c | [Stack-Owned Ingress/Auth/DNS Refactor](phase-04c-stack-owned-ingress-auth-dns.md) | Phase 04 complete |
| 05 | [Supply Chain Security](phase-05-supply-chain.md) | Phase 01, 03b, 04 complete |
| 06 | [Application Stack Migration](phase-06-app-stacks.md) | Phase 04, 05 complete |
| 07 | [Runtime Security and Secrets Management](phase-07-runtime-security.md) | Phase 06 complete — placeholder, not yet planned |

## Architecture reference

- [Architecture](../design/architecture.md) — requirements, ADRs, threat model
- [Network design](../design/network.md) — SDN zones, IP allocation, DNS, TLS
- [Bootstrap sequence](../design/bootstrap.md) — circular dependency model and stage map
- [Development status](development-status.md) — rebuild confidence per component
- [Lessons learned](../design/lessons-learned.md) — non-obvious facts from development passes

For the full SDN zone definitions and MikroTik setup commands, see
[terraform/lxc/network/pve-test-vm.yaml](../../terraform/lxc/network/pve-test-vm.yaml).

## Environment summary

The active test target is **pve-test-vm** (`192.168.1.41`,
`pve-test-vm.gibbsgreatly.xyz`), a VM-hosted Proxmox instance on the homelab
bare-metal host. It replaced the retired bare-metal `pve-test` laptop.
Use `PVE_ENV=pve-test-vm` when running harness or deploy commands.

pve (production) is not touched during development passes. All services, including Harbor,
apt-cacher, and NetBox, are deployed locally on pve-test-vm.

**Network model:** Proxmox SDN VLAN zones. The MikroTik is the L3 gateway for all zones.
No NAT or routing is performed on the Proxmox host.

## Container inventory

The authoritative stack inventory (VMIDs, IPs, deploy/destroy order) is in
[docs/teardown-test/inventory.md](../teardown-test/inventory.md).

Current stack zones and IP segments (IPs resolved from `.env.pve-test-vm`):

| Service | Zone | IP range | VMID |
| --- | --- | --- | --- |
| portainer-stack | `mgmt_seg` | 192.168.20.x | 20020 |
| authentik-stack | `mgmt_seg` | 192.168.20.x | 20010 |
| step-ca-stack | `mgmt_seg` | 192.168.20.x | 20011 |
| monitoring-stack | `mgmt_seg` | 192.168.20.x | 20012 |
| dns-stack | `mgmt_seg` | 192.168.20.x | 20013 |
| proxy-stack | `edge_seg` | 192.168.30.x | 30010 |
| harbor-stack | `infra_seg` | 192.168.40.x | 40010 |
| apt-cacher-stack | `infra_seg` | 192.168.40.x | 40011 |
| netbox-stack | `infra_seg` | 192.168.40.x | 40012 |
| ci-runner-01 | `build_seg` | 192.168.10.x | 10063 |

Storage pool: `infrastructure-containers` on pve-test-vm (ZFS).

**Harbor bootstrap:** On the first pass, Harbor pulls its own images from Docker Hub
directly. Once Harbor is running, all subsequent containers in all zones pull from
`10.57.3.10`. This is the designed Stage 1 → Stage 2 transition — it is not a
misconfiguration. See [bootstrap.md](../design/bootstrap.md).

Portainer remains in the lab as the management UI for Tier 2 application
stacks. Tier 1 platform stacks on `pve-test-vm` are provisioned by Terraform and
configured explicitly via `scripts/provision.sh`; they do not use Portainer
agents.

## Two modes of work

**Mode 1 — Development:** Building and refining the playbook — writing Ansible roles,
exploring service configuration, generating documentation. Order does not matter. Services
can be stood up temporarily on any machine and then discarded. The phase sequence does not
constrain Mode 1 work.

**Mode 2 — Deployment:** Executing the playbook on real infrastructure. Order is
load-bearing. The phase sequence, bootstrap stage model, and all task prerequisites
describe Mode 2. A pve-test wipe-and-rebuild is a Mode 2 activity.

When a phase document lists prerequisites you have not met, ask first whether you are doing
Mode 2 work. If you are exploring or writing code, proceed in whatever order is useful.
See [bootstrap.md](../design/bootstrap.md) for the full treatment of this distinction.

### Task document lifecycle

Task documents in `docs/plan/tasks/` fall into two categories:

**Recurring rebuild tasks** — Phase 04, 05, and 06 task docs describe work that must be
re-executed on each fresh pve-test pass. These docs stay in `tasks/` permanently.

**One-time tasks** — Code quality fixes, CI changes, planning documents, and any task that
modifies the repository itself rather than a running service. Once merged, archive to
`done/`. The `done/` directory means the repository change is merged — it does not mean a
service is currently running.

## Repository conventions

The authoritative workflow and branch model live in:

- [docs/workflow/branch-model.md](../workflow/branch-model.md)
- [docs/workflow/environments.md](../workflow/environments.md)

Use those docs instead of repeating branch/process rules here.

For planning-workspace hygiene, also use:

- [docs/workflow/documentation-workspaces.md](../workflow/documentation-workspaces.md)

Transient handoffs, prompts, transcripts, evidence, and scratch notes should
live in a local `artifacts/` directory inside the relevant docs workspace, not
as tracked documentation.

### Security scanning (run before merging any branch)

| Change type | Command |
| --- | --- |
| Terraform files modified | `/home/steve/.local/bin/snyk iac test terraform/` |
| Code files modified (Python, shell, YAML) | `./with-secrets /home/steve/.local/bin/sonar-scanner` |

If a scan returns new issues, stop and present options — do not merge until resolved or explicitly accepted.

## Known implementation gaps

See also [network.md — Known gaps](../design/network.md#known-gaps) for network-specific gaps.

| Gap | Location | Description |
| --- | --- | --- |
| VNet firewall cross-zone rule bug | `terraform/lxc/main.tf:86-95` | `vnet_policy_candidates` requires both `from` and `to` to match the current container's VNet — cross-zone ACCEPT rules are never generated. Proxmox firewall disabled for dev passes as a workaround. |
| SDN VLAN zone support in Terraform | `configure-network-sdn-vnet.yml` | Handles Simple zones only. Use `ansible/00-initial-setup/proxmox-sdn-setup.yml` for VLAN zones until fixed. |

## Active issues

Tables like this go stale the moment an issue closes. Verify before relying
on it: `gh issue list --state open --search "Phase 06"`.

As of 2026-07-03, Phase 04 (#106, #125, #107) and Phase 05 (#108, #109, #110)
issues below are all **closed** — those phases are implemented. Only Phase 06
work remains open:

| Issue | Description | Phase |
| --- | --- | --- |
| #113 | Discover and document application workloads | 06-01 |
| #114 | Create app_seg and game_seg SDN zones | 06-02 |
| #115 | Migrate Pi-hole to app_seg | 06-03 |
| #116 | Migrate arr stack to app_seg | 06-04 |
| #117 | Migrate Jellyfin to app_seg | 06-05 |
| #118 | Migrate game services to game_seg | 06-06 |
| #119 | Add Trivy rootfs scheduled scan workflow | 06-07 |
