# Homelab Build Plan — Phase Index

This directory contains per-phase planning documents for the greenfield rebuild of the proxmox-homelab. Each document is self-contained and intended to be used in a single AI-assisted work session.

## Phase sequence

Phases must be completed in order. Each phase lists its prerequisites explicitly.

| Phase | Document | Status | Gate |
|---|---|---|---|
| 00b | [pve-test Management Bootstrap](phase-00b-pve-test-management.md) | **Before Phase 03b** | Phase 00 complete |
| 01 | [CI Runner Deployment](phase-01-ci-runner-deployment.md) | After Phase 00 | Phase 00 complete |
| 02 | [Memory Upgrade (32 GB)](phase-02-memory-upgrade.md) | **Complete** | — |
| 03 | [Code Quality & Bug Fixes](phase-03-code-quality.md) | Parallel with 01-02 | Phase 00 complete |
| 03b | [Harbor Setup: Trivy, Projects, Image Cache](phase-03b-harbor-setup.md) | **Before Phase 04** | Phase 00b complete |
| 03c | [Artifact Proxy (apt-cacher-ng + Terraform mirror)](phase-03c-artifact-proxy.md) | **Before Phase 04** | Phase 00b complete |
| 04 | [Core Shared Services](phase-04-core-shared-services.md) | After Phase 03b + 03c | Phase 03b and 03c complete |
| 05 | [Supply Chain Security](phase-05-supply-chain.md) | After Phase 04 | Phase 01, 03b, 04 complete |
| 06 | [Application Stack Migration](phase-06-app-stacks.md) | After Phase 05 | Phase 04, 05 complete — **Out of scope for this plan.** |

## Architecture reference

See [docs/design/GreenField.md](../design/GreenField.md) for the full architecture rationale and technology selection.

See [docs/design/NetworkPlanning.md](../design/NetworkPlanning.md) for the network zone model and implementation options.

For the SDN VLAN zone design, IP allocations, and MikroTik configuration, see [terraform/lxc/network/pve-test.yaml](../../terraform/lxc/network/pve-test.yaml).

## pve-test environment

pve-test is a **laptop running bare-metal Proxmox VE** at `192.168.1.40` (`pve-test.gibbsgreatly.xyz`), connected via a trunk port to the MikroTik router. It is treated as ephemeral — all services are wiped and rebuilt from scratch at the start of each development pass. No state from a previous pass is assumed to persist.

The pve-test VM that previously ran inside `pve` has been retired. pve (production) is not used during development passes — all services, including Harbor, apt-cacher, and NetBox, are deployed locally on pve-test.

**Network model:** Proxmox SDN VLAN zones. The MikroTik acts as the L3 gateway for all SDN zones. No NAT or routing is performed on the Proxmox host itself. See [terraform/lxc/network/pve-test.yaml](../../terraform/lxc/network/pve-test.yaml) for the zone design and MikroTik setup commands.

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

## Key infrastructure addresses

All services are deployed on **pve-test** only. pve (production) is not referenced during development passes.

### Bootstrap services (vmbr0 — LAN bridge)

These run on the flat LAN bridge before SDN zones exist. Portainer is the only permanent vmbr0 exception; all other services move to SDN zones once the zones are up.

| Service | IP | VMID | Phase |
|---|---|---|---|
| Portainer | `192.168.1.20` | 120 | 00b |

### Infrastructure segment — infra_seg (VLAN 40, 10.57.3.0/24, gw 10.57.3.1)

Deployed second, immediately after Portainer. All other zones depend on Harbor and apt-cacher.

| Service | IP | VMID | Phase |
|---|---|---|---|
| Harbor (registry) | `10.57.3.10` | 121 | 03b |
| apt-cacher-ng | `10.57.3.11` | 142 | 03c |
| NetBox (IPAM) | `10.57.3.12` | 143 | 03b or early 04 |

**Harbor bootstrap:** On the first pass, Harbor pulls its own images from Docker Hub directly. Once Harbor is running, all subsequent containers in all zones pull from `10.57.3.10`.

### Management segment — mgmt_seg (VLAN 20, 10.57.1.0/24, gw 10.57.1.1)

| Service | Zone | IP | VMID | Phase |
|---|---|---|---|---|
| Authentik | `mgmt_seg` | `10.57.1.10` | 150 | 04 |
| step-ca | `mgmt_seg` | `10.57.1.11` | 152 | 04 |
| Monitoring (Grafana + VictoriaMetrics + Loki) | `mgmt_seg` | `10.57.1.12` | 154 | 04 |

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

## Memory budget — pve-test (16 GB)

pve-test runs on a 16 GB laptop. Only one application stack runs at a time during development passes. The table below shows the target allocation for the Phase 04 platform. Do not exceed these values; OOM on the Proxmox host disrupts all running containers.

| Service | VMID | Memory |
|---|---|---|
| Portainer | 120 | 512 MB |
| Harbor | 121 | 2048 MB |
| apt-cacher | 142 | 256 MB |
| NetBox | 143 | 1024 MB |
| ci-runner-01 | 141 | 1024 MB |
| Authentik | 150 | 2048 MB |
| step-ca | 152 | 256 MB |
| Traefik | 153 | 512 MB |
| Monitoring | 154 | 1536 MB |
| **Platform total** | | **~9.2 GB** |
| Host OS overhead | | ~2.5 GB |
| **Available for one app stack** | | **~4.3 GB** |

When deploying an application stack for development, check that platform containers are within their allocations first: `pct list` on pve-test. Stop any non-essential containers if the headroom is insufficient.

## Phase 04 bring-up sequence (per-pass rebuild)

pve-test is wiped before each development pass. On a fresh node, bring up services in this exact order before starting any Phase 04 task:

1. **VLAN setup on MikroTik** (once per pve-test rebuild) — see `pve-test.yaml`
2. **Enable VLAN awareness on vmbr0** in Proxmox UI, then `ifreload -a`
3. **Apply SDN VLAN zones** to pve-test (manual pvesh until Terraform support is complete)
4. **Portainer** (VMID 120, vmbr0)
5. **Harbor** (VMID 121, infra_seg) — first pass pulls from Docker Hub; verify at `http://10.57.3.10/api/v2.0/ping`
6. **apt-cacher** (VMID 142, infra_seg)
7. **NetBox** (VMID 143, infra_seg) — record all IP allocations from this point forward
8. **Authentik** (VMID 150, mgmt_seg)
9. **Traefik** (VMID 153, edge_seg) — use LE staging resolver for dev passes
10. **step-ca** (VMID 152, mgmt_seg)
11. **Monitoring** (VMID 154, mgmt_seg)

## Open issues summary

| Issue | Description | Phase | Action |
|---|---|---|---|
| #106 | Traefik deployment | 04-03 | Active |
| #107 | Monitoring deployment | 04-05 | Active |
| #108 | Trivy CI scan | 05-01 | Active |
| #109 | Syft SBOM | 05-02 | Active |
| #110 | Cosign signing | 05-03 | Active |
| #120 | ShellCheck cleanup: setup-dev-env.sh | — | Ready to work |
| #121 | ShellCheck cleanup: check-proxmox-status.sh | — | Ready to work |

## Known code gaps (not yet fixed)

| Gap | Location | Description |
|---|---|---|
| VNet firewall cross-zone rule bug | `terraform/lxc/main.tf:86-95` | `vnet_policy_candidates` requires both `from` and `to` to match the current container's VNet — impossible for cross-zone policies. No ACCEPT rules are generated. Proxmox firewall disabled for dev passes as a workaround. |
| SDN VLAN zone support in Terraform | `configure-network-sdn-vnet.yml` | Playbook handles Simple zone creation only. Must be updated for `zone_type: vlan` before VLAN zones can be applied via `terragrunt apply`. Apply manually via pvesh until fixed. |
