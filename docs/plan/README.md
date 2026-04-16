# Homelab Build Plan — Development and Deployment Index

This directory is the execution index for the greenfield rebuild of the proxmox-homelab.
It links the active development and deployment phases, the task documents used to carry
them out, and the repository conventions that apply while the implementation catches up
to the revised design.

## Phase sequence

Phases must be completed in order unless a phase explicitly says it can run in parallel.
Each phase document owns its own prerequisites, acceptance criteria, and task breakdown.

| Phase | Document | Status | Gate |
|---|---|---|---|
| 00a | [Proxmox Host Bootstrap Alignment](phase-00a-proxmox-host-bootstrap.md) | Before Phase 00b | Phase 00 complete |
| 00b | [pve-test Management Bootstrap](phase-00b-pve-test-management.md) | **Complete** | Phase 00 complete |
| 00c | [Bootstrap Sequence (Stage 1 temporary → Stage 2 production)](phase-00c-bootstrap-sequence.md) | After Phase 03d | Stage 0 (Phase 03d) complete |
| 01 | [CI Runner Deployment](phase-01-ci-runner-deployment.md) | After Phase 00b | Phase 00b complete |
| 02 | [Memory Upgrade (32 GB)](phase-02-memory-upgrade.md) | **Complete** | — |
| 03 | [Code Quality & Bug Fixes](phase-03-code-quality.md) | Parallel with 01-02 | Phase 00 complete |
| 03b | [Harbor Setup: Trivy, Projects, Image Cache](phase-03b-harbor-setup.md) | **Before Phase 04** | Phase 00b complete |
| 03c | [Artifact Proxy (apt-cacher-ng + Terraform mirror)](phase-03c-artifact-proxy.md) | **Before Phase 04** | Phase 00b complete |
| 03d | [Secrets Delivery Hardening (sops exec-env)](phase-03d-secrets-hardening.md) | Workstation task — do before first deploy | None — workstation only |
| 04 | [Core Shared Services](phase-04-core-shared-services.md) | After Phase 03b + 03c + 03d | Phase 03b, 03c, and 03d complete |
| 05 | [Supply Chain Security](phase-05-supply-chain.md) | After Phase 04 | Phase 01, 03b, 04 complete |
| 06 | [Application Stack Migration](phase-06-app-stacks.md) | After Phase 05 | Phase 04, 05 complete — **Out of scope for this plan.** |
| 07 | [Runtime Security and Secrets Management](phase-07-runtime-security.md) | After Phase 06 | Phase 06 complete — **Placeholder; not yet planned.** |

## Architecture reference

See [docs/design/GreenField.md](../design/GreenField.md) for the full architecture rationale and technology selection.

See [docs/design/NetworkPlanning.md](../design/NetworkPlanning.md) for the network zone model and implementation options.

See [docs/design/bootstrap-stages.md](../design/bootstrap-stages.md) for the three-stage bootstrap model: why it exists, the Linux From Scratch parallel, security controls by stage, and the mapping from stages to execution phases.

For the SDN VLAN zone design, IP allocations, and MikroTik configuration, see [terraform/lxc/network/pve-test.yaml](../../terraform/lxc/network/pve-test.yaml).

## Environment summary

pve-test is a **laptop running bare-metal Proxmox VE** at `192.168.1.40` (`pve-test.gibbsgreatly.xyz`), connected via a trunk port to the MikroTik router. It is treated as ephemeral — all services are wiped and rebuilt from scratch at the start of each development pass. No state from a previous pass is assumed to persist.

The pve-test VM that previously ran inside `pve` has been retired. pve (production) is not used during development passes — all services, including Harbor, apt-cacher, and NetBox, are deployed locally on pve-test.

**Network model:** Proxmox SDN VLAN zones. The MikroTik acts as the L3 gateway for all SDN zones. No NAT or routing is performed on the Proxmox host itself. See [terraform/lxc/network/pve-test.yaml](../../terraform/lxc/network/pve-test.yaml) for the zone design and MikroTik setup commands.

## What This README Is For

- Use this file as the top-level index for active build phases and task documents.
- Treat `docs/design/` as the target architecture and rationale.
- Treat each `docs/plan/phase-*.md` file as the execution plan for a slice of work.
- Treat `docs/plan/tasks/*.md` as the detailed implementation prompts and checklists for individual tasks.

### Task document lifecycle

Task documents in `docs/plan/tasks/` fall into two categories:

**Recurring rebuild tasks** — Phase 04, 05, and 06 task docs describe work that must be
re-executed on each fresh pve-test wipe. These docs stay in `tasks/` even after a
successful pass. Do not archive them to `done/`.

**One-time tasks** — Code quality fixes, CI changes, planning documents, and any task that
modifies the repository itself (not a running service) are one-time. Once merged, archive
these to `done/`. The `done/` directory indicates the repository change was merged and will
not be re-executed as a standalone task on the next pve-test pass — it does NOT mean a
service is currently running.

## Host Bootstrap Dependencies

The active plan now includes Proxmox host/bootstrap work as a planned part of the build,
not just as background repo tooling.

See [phase-00a-proxmox-host-bootstrap.md](./phase-00a-proxmox-host-bootstrap.md) for the
current classification of:

- host bootstrap playbooks that are part of the active pve-test path
- host/bootstrap playbooks that need redesign for the current plan
- storage/bootstrap playbooks that should be treated as historical or alternate-path work

## Repository conventions

- Branch from `dev/pve-test` for each phase or individual fix
- Short-lived branches follow the naming: `feat/<name>`, `fix/<name>`, `chore/<name>`
- Validate in the short-lived branch before merging — if issues are found, **stop and present options**, do not push through
- Merge to `dev/pve-test`, never directly to `main`
- PR `dev/pve-test` → `main` only when the phase is stable and tested on pve-test
- After merging to `main`, pull `main` back into `dev/pve-test`: `git checkout dev/pve-test && git merge main && git push origin dev/pve-test`
- Close GitHub issues with `Closes #N` in the commit message
- Run `gh issue close N --comment "Fixed in commit <sha>"` after committing — do both before reporting back

### Security scanning (run before merging any branch)

| Change type | Command |
|---|---|
| Terraform files modified | `/home/steve/.local/bin/snyk iac test terraform/` |
| Code files modified (Python, shell, YAML) | `source .env && sonar-scanner` |

If a scan returns new issues, **stop and present options** — do not merge until resolved or explicitly accepted.

## Active Target-State Addresses

All active planning assumes services are deployed on **pve-test** only. pve (production) is
not part of development passes.

### Management segment — mgmt_seg (VLAN 20, 10.57.1.0/24, gw 10.57.1.1) — first deployed

| Service | Zone | IP | VMID | Phase |
|---|---|---|---|---|
| Portainer | `mgmt_seg` | `10.57.1.20` | 120 | 00b |
| Authentik | `mgmt_seg` | `10.57.1.10` | 150 | 04 |
| step-ca | `mgmt_seg` | `10.57.1.11` | 152 | 04 |
| Monitoring (Grafana + VictoriaMetrics + Loki) | `mgmt_seg` | `10.57.1.12` | 154 | 04 |

### Infrastructure segment — infra_seg (VLAN 40, 10.57.3.0/24, gw 10.57.3.1)

Deployed second, immediately after Portainer. All other zones depend on Harbor and apt-cacher.

| Service | IP | VMID | Phase |
|---|---|---|---|
| Harbor (registry) | `10.57.3.10` | 121 | 03b |
| apt-cacher-ng | `10.57.3.11` | 142 | 03c |
| NetBox (IPAM) | `10.57.3.12` | 143 | 03b or early 04 |

**Harbor bootstrap:** On the first pass, Harbor pulls its own images from Docker Hub directly. Once Harbor is running, all subsequent containers in all zones pull from `10.57.3.10`.

### Management segment — mgmt_seg (VLAN 20, 10.57.1.0/24, gw 10.57.1.1) — Phase 04 additions

### Edge segment — edge_seg (VLAN 30, 10.57.2.0/24, gw 10.57.2.1)

| Service | Zone | IP | VMID | Phase |
|---|---|---|---|
| Reverse proxy (Traefik) | `edge_seg` | `10.57.2.10` | 153 | 04 |

### Build segment — build_seg (VLAN 10, 10.57.0.0/24, gw 10.57.0.1)

| Service | Zone | IP | VMID | Phase |
|---|---|---|---|
| ci-runner-01 | `build_seg` | `10.57.0.63` | 141 | 01 |

### Storage pool names

| Pool | Node | Used by |
|---|---|---|
| `infrastructure-containers` | pve-test | All stacks |

## Phase 04 Bring-Up Sequence (Per-Pass Rebuild)

pve-test is wiped before each development pass. On a fresh node, bring up services in this exact order before starting any Phase 04 task:

1. **VLAN setup on MikroTik** (once per pve-test rebuild) — see `pve-test.yaml`
2. **Enable VLAN awareness on vmbr0** in Proxmox UI, then `ifreload -a`
3. **Apply SDN VLAN zones** to pve-test with `ansible/00-initial-setup/proxmox-sdn-setup.yml` until Terraform support is complete
4. **Portainer** (VMID 120, mgmt_seg, `10.57.1.20`)
5. **Harbor** (VMID 121, infra_seg) — first pass pulls from Docker Hub; verify at `http://10.57.3.10/api/v2.0/ping`
6. **apt-cacher** (VMID 142, infra_seg)
7. **NetBox** (VMID 143, infra_seg) — record all IP allocations from this point forward
8. **Authentik** (VMID 150, mgmt_seg)
9. **Traefik** (VMID 153, edge_seg) — use LE staging resolver for dev passes
10. **step-ca** (VMID 152, mgmt_seg)
11. **Monitoring** (VMID 154, mgmt_seg)

## Active Issues Summary

| Issue | Description | Phase | Action |
|---|---|---|---|
| #106 | Traefik deployment | 04-03 | Active |
| #107 | Monitoring deployment | 04-05 | Active |
| #108 | Trivy CI scan | 05-01 | Active |
| #109 | Syft SBOM | 05-02 | Active |
| #110 | Cosign signing | 05-03 | Active |
| #120 | ShellCheck cleanup: setup-dev-env.sh | — | Ready to work |
| #121 | ShellCheck cleanup: check-proxmox-status.sh | — | Ready to work |

## Known Implementation Gaps

| Gap | Location | Description |
|---|---|---|
| VNet firewall cross-zone rule bug | `terraform/lxc/main.tf:86-95` | `vnet_policy_candidates` requires both `from` and `to` to match the current container's VNet — impossible for cross-zone policies. No ACCEPT rules are generated. Proxmox firewall disabled for dev passes as a workaround. |
| SDN VLAN zone support in Terraform | `configure-network-sdn-vnet.yml` | Playbook handles Simple zone creation only. Must be updated for `zone_type: vlan` before VLAN zones can be applied via `terragrunt apply`. Use `ansible/00-initial-setup/proxmox-sdn-setup.yml` until that gap is closed. |

## Notes

- This README is intentionally an index and execution guide, not the full architecture document.
- If a phase document conflicts with `docs/design/` after the 2026 plan revision, update the phase document to match the revised design or mark it historical.
- Phase 06 remains intentionally out of scope until the platform and supply-chain phases are stable.
