# Revised Architecture Overview

> Status note
>
> This document is background architecture context for the Portainer-removal
> refactor. The operational source of truth is now
> `docs/refactor-remove-portainer/README.md`, `decisions.md`,
> `task-sequence.md`, and `runbook.md`.
>
> If this document conflicts with those control documents, the control
> documents win.

**Status:** Draft — not yet merged into proxmox-homelab
**Supersedes:** `docs/design/architecture.md` ADR-04 and the deployment model implicit in `terraform/lxc/PLATFORM_CONTRACT.md`

---

## What changed and why

Two architectural decisions have been revised from the current codebase:

### 1. Portainer is removed from the platform deployment path

**Previous model:** Ansible deploys all Docker stacks — including platform services such as
Harbor, Authentik, step-ca, Traefik, and monitoring — by calling the Portainer API. Every
platform LXC runs a `portainer-agent` container registered with the Portainer server.

**Revised model:** Platform and infrastructure containers are deployed directly by Ansible
over SSH using `docker compose`. Portainer has no agent on platform LXCs and no API
involvement in their deployment.

**Why:**

- **Bootstrap circularity.** Portainer must be healthy before any `app_stack` role call can
  succeed. Portainer is itself a platform service. This creates a dependency that can only be
  broken by special-casing or by the existing `block/rescue` workaround in `portainer_api`.
  Removing the dependency eliminates the problem entirely.

- **Attack surface.** Platform containers include the PKI (step-ca), the identity provider
  (Authentik), the container registry (Harbor), and the certificate-issuing CA. A Portainer
  server compromise currently gives an attacker agent-level access to the Docker socket on
  all of these containers. Removing the agent from platform LXCs limits Portainer's blast
  radius to application stacks only.

- **Security constraint SEC-02** (Portainer agent communication must use TLS with mutual
  certificate auth) remains valid for application stacks but is no longer relevant for
  platform stacks.

### 2. Terraform and Ansible are separated into explicit sequential phases

**Previous model:** Each Terragrunt stack module runs Ansible inline via `local-exec`
provisioners immediately after the container is created. Terraform is the orchestrator of
both provisioning and configuration.

**Revised model:** Terraform provisions all LXC containers (infrastructure phase). Ansible
configures all LXC containers in a separate, explicit second phase (configuration phase).
The two phases are orchestrated by a top-level script rather than by Terraform internals.

**Why:**

- Configuration can be re-run without touching Terraform state.
- Ansible runs natively parallel across multiple hosts rather than sequentially through
  Terraform null_resources.
- Debugging is cleaner: a Terraform error means a provisioning problem; an Ansible error
  means a configuration problem.
- The boundary between "what exists" and "what is configured" is explicit rather than
  implicit in Terraform's dependency graph.

---

## Two deployment tiers

All containers fall into one of two tiers. The tier determines the deployment mechanism.

### Tier 1 — Platform / Infrastructure

| Service | Zone | Purpose |
|---|---|---|
| Portainer | `mgmt_seg` | Container visibility for Tier 2 only |
| Harbor | `infra_seg` | Container registry, image scanning |
| apt-cacher-ng | `infra_seg` | apt package proxy |
| NetBox | `infra_seg` | IPAM |
| CI runner | `build_seg` | GitHub Actions self-hosted runner |
| Authentik | `mgmt_seg` | Identity provider, SSO |
| step-ca | `mgmt_seg` | Internal PKI |
| Traefik | `edge_seg` | Reverse proxy, TLS termination |
| CoreDNS | `mgmt_seg` | Authoritative internal DNS |
| Monitoring (Grafana + VictoriaMetrics + Loki) | `mgmt_seg` | Observability |

**Deployment:** Terraform provisions LXC → Ansible configures via SSH + `docker compose`.
**Portainer agent:** Not installed. Portainer has no visibility into these containers.
**Template:** Debian 13 Docker template built with `install_portainer_agent: false`.

### Tier 2 — Application Stacks

| Service | Zone | Purpose |
|---|---|---|
| Pi-hole | `app_seg` | Ad-blocking DNS resolver |
| arr stack | `app_seg` | Media management (Radarr, Sonarr, Prowlarr, etc.) |
| Jellyfin | `app_seg` | Media server |
| Game services | `game_seg` | Minecraft and other game servers |

**Deployment:** Terraform provisions LXC → Ansible configures via Portainer API (`app_stack` role).
**Portainer agent:** Installed. Portainer can inspect and provides management UI.
**Template:** Debian 13 Docker template built with `install_portainer_agent: true` (current default).

---

## Updated ADR-04: Container Management Plane

**Status:** Revised
**Previous decision:** Terraform/Ansible is the control plane. Portainer is observability-only (read access). Portainer agents deployed across all zones with step-ca mutual TLS.

**Revised decision:** Terraform/Ansible is the control plane for all containers. Portainer is a management UI for Tier 2 application stacks only. Portainer agents are not installed on Tier 1 platform containers.

| Option | Pros | Cons |
|---|---|---|
| Portainer agents on all LXCs | Unified visibility, consistent deployment path | Docker socket cross-zone exposure on PKI/IAM/registry; bootstrap circularity |
| Portainer agents on Tier 2 only (revised) | Blast radius limited to apps; bootstrap problem eliminated; simpler platform deploy | Two deployment paths to maintain |
| No Portainer at all | Maximum simplicity | Loss of management UI value for application stacks where it's genuinely useful |

**Rationale:** Portainer's management GUI is most valuable for application stacks — hobby services where interactive inspection and quick restarts have real utility. For platform services (step-ca, Authentik, Harbor), the Docker socket exposure is an unacceptable attack surface given those containers' security significance. The `block/rescue` workaround in the existing `portainer_api` role was a symptom of the bootstrap problem this change eliminates.

---

## Unchanged architectural decisions

All other ADRs, security constraints (SEC-01 through SEC-07), non-functional requirements,
threat model entries, and the bootstrap stage model (Stage 0 through Stage 3b) are
unchanged. In particular:

- **ADR-06** (secrets via `with-secrets` / `sops exec-env`) applies to both tiers
- **NFR-05** (all images from Harbor) applies to both tiers
- **NFR-08** (rebuild-safe from code) applies to both tiers
- The Stage 1 → Stage 2 bootstrap sequence is unchanged; Portainer remains a Stage 1/2
  service and is not affected by its removal from the Tier 1 deployment path
