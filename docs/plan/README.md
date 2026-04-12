# Homelab Build Plan — Phase Index

This directory contains per-phase planning documents for the greenfield rebuild of the proxmox-homelab. Each document is self-contained and intended to be used in a single AI-assisted work session.

## Phase sequence

Phases must be completed in order. Each phase lists its prerequisites explicitly.

| Phase | Document | Status | Gate |
|---|---|---|---|
| 00b | [pve-test Management Bootstrap](phase-00b-pve-test-management.md) | **Before Phase 03b** | Phase 00 complete |
| 01 | [CI Runner Deployment](phase-01-ci-runner-deployment.md) | After Phase 00 | Phase 00 complete |
| 02 | [Memory Upgrade (32 GB)](phase-02-memory-upgrade.md) | **Hard gate for Phase 04** | Phase 01 complete |
| 03 | [Code Quality & Bug Fixes](phase-03-code-quality.md) | Parallel with 01-02 | Phase 00 complete |
| 03b | [Harbor Setup: Trivy, Projects, Image Cache](phase-03b-harbor-setup.md) | **Before Phase 04** | Phase 00b complete |
| 03c | [Artifact Proxy (apt-cacher-ng + Terraform mirror)](phase-03c-artifact-proxy.md) | **Before Phase 04** | Phase 00b complete |
| 04 | [Core Shared Services](phase-04-core-shared-services.md) | After Phase 02 + 03b + 03c | Phase 02, 03b, and 03c complete |
| 05 | [Supply Chain Security](phase-05-supply-chain.md) | After Phase 04 | Phase 01, 03b, 04 complete |
| 06 | [Application Stack Migration](phase-06-app-stacks.md) | After Phase 05 | Phase 04, 05 complete — **Out of scope for this plan.** Phase 04/05 establishes the platform basis. App stack migration is a separate planning effort. |

## Architecture reference

See [docs/plans/GreenField.md](../plans/GreenField.md) for the full architecture rationale and technology selection.

For SDN zone design and egress routing (mgmt_seg, edge_seg, build_seg),
see [terraform/lxc/network/pve-test.yaml](../../terraform/lxc/network/pve-test.yaml).

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

All services are validated on **pve-test** first, then promoted to **pve** (production).
Services share the `192.168.1.x/24` LAN on both nodes; IPs are the same on both nodes
except where noted.

### Management infrastructure

| Service | IP | VMID | Node | Phase |
|---|---|---|---|---|
| Portainer (production) | `192.168.1.4` | — | pve | existing |
| Portainer (pve-test) | `192.168.1.20` | 120 | pve-test | 00b |
| NetBox (IPAM) | `192.168.1.30` | 119 | pve | existing |
| Harbor (registry) | `192.168.1.10` | 121 | pve | existing |
| ci-runner-01 | `10.57.0.63` | 141 | pve-test | 01 |
| apt-cacher-ng | `192.168.1.35` | 142 | pve-test → pve | 03c |

### Core shared services (Phase 04)

| Service | Zone | IP | VMID |
|---|---|---|---|
| Authentik | `mgmt_seg` | `10.57.1.10` | 150 |
| step-ca | `mgmt_seg` | `10.57.1.11` | 152 |
| Reverse proxy (Traefik) | `edge_seg` | `10.57.2.10` | 153 |
| Monitoring (Grafana + VictoriaMetrics + Loki) | `mgmt_seg` | `10.57.1.12` | 154 |

### Storage pool names

| Pool | Node | Used by |
|---|---|---|
| `infrastructure-containers` | pve, pve-test | All LAN-attached stacks (`stack.yaml` default) |
| `storage-containers` | pve-test | SDN-zone (net-\*) validation stacks only |

All Phase 03b, 03c, and 04 `stack.yaml` files should use `rootfs_storage: infrastructure-containers`.

## Open issues summary

| Issue | Description | Phase | Action |
|---|---|---|---|
| #89 | Phase 02 service verification | 02 | Close — services verified healthy |
| #104 | Headscale deployment | 04 | Close — cancelled (no remote access requirement) |
| #106 | Traefik deployment | 04-03 | Active |
| #107 | Monitoring deployment | 04-05 | Active (was 04-04 in old numbering) |
| #108 | Trivy CI scan | 05-01 | Active |
| #109 | Syft SBOM | 05-02 | Active |
| #110 | Cosign signing | 05-03 | Active |
| #111 | Chainloop server | 05-04 | Close — cancelled (no Docker Compose self-hosting path) |
| #120 | ShellCheck cleanup: setup-dev-env.sh | — | Ready to work (ShellCheck available locally) |
| #121 | ShellCheck cleanup: check-proxmox-status.sh | — | Ready to work |
