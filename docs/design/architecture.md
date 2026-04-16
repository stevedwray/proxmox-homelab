---
stepsCompleted: [1, 2, 3, 4]
inputDocuments:
  - docs/design/GreenField.md
  - docs/design/NetworkPlanning.md
  - docs/design/Observations.md
  - docs/design/PlanRevisionBrief.md
  - docs/plan/README.md
  - docs/plan/phase-00a-proxmox-host-bootstrap.md
  - docs/plan/phase-00b-pve-test-management.md
  - docs/plan/phase-01-ci-runner-deployment.md
  - docs/plan/phase-02-memory-upgrade.md
  - docs/plan/phase-03-code-quality.md
  - docs/plan/phase-03b-harbor-setup.md
  - docs/plan/phase-03c-artifact-proxy.md
  - docs/plan/phase-04-core-shared-services.md
  - docs/plan/phase-05-supply-chain.md
  - docs/plan/phase-06-app-stacks.md
  - docs/plan/phase-07-runtime-security.md
  - docs/reference/proxmox-server-baseline.md
  - docs/reference/proxmox-terraform-user.md
  - docs/reference/sdn-segment-routing.md
  - docs/reference/secrets-management.md
workflowType: architecture
project_name: homelab
user_name: Stephen Wray
date: '2026-04-15'
documentStyle: thorough
scope: full-system
elicitationSessions:
  - method: Red Team vs Blue Team
    date: '2026-04-15'
    findings: 7 attack vectors identified; 7 hardening constraints applied
  - method: Architecture Decision Records
    date: '2026-04-15'
    findings: 6 ADRs documented (CI platform, reverse proxy, metrics, container mgmt, remote access, secrets runtime)
  - method: STRIDE Threat Model
    date: '2026-04-15'
    findings: 32 threats identified across 9 asset classes; 4 P0, 9 P1, 7 P2, 8 P3; 4 deferred to Phase 07
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

---

## Project Context Analysis

### Project Nature

Brownfield homelab infrastructure rebuild — a deliberate greenfield redesign of an existing personal lab, built progressively on `pve-test` (bare-metal Proxmox laptop) before being promoted to the production node `pve`. Architecture is **infrastructure-as-code first**: all provisioning in Terraform (Terragrunt), all configuration in Ansible, all operations gated through CI.

### Functional Requirements

| Ref | Requirement |
|---|---|
| FR-01 | Host and manage LXC containers and VMs on Proxmox VE using Terraform (Terragrunt) for provisioning |
| FR-02 | Network segmentation across dedicated SDN VLAN zones (build, mgmt, edge, infra, and future app/game/security) |
| FR-03 | Internal identity and SSO via Authentik |
| FR-04 | Internal certificate authority via step-ca |
| FR-05 | Reverse proxy with dual certificate resolver (Let's Encrypt for browser, step-ca for internal) via Traefik |
| FR-06 | Internal container registry with vulnerability scanning, proxy cache, and robot account support via Harbor |
| FR-07 | Artifact proxying for apt packages (apt-cacher-ng) and Terraform providers (local mirror) |
| FR-08 | IPAM and network documentation via NetBox |
| FR-09 | CI/CD pipeline via GitHub Actions with self-hosted runner on `build_seg` |
| FR-10 | Observability stack: VictoriaMetrics + Grafana + Loki |
| FR-11 | Supply chain: Trivy (scan), Syft (SBOM), Cosign (sign), Harbor (policy gate) |
| FR-12 | Application stack migration: arr stack, Jellyfin, Pi-hole, game services |
| FR-13 | Secrets management with Bitwarden and environment variable injection |
| FR-14 | Code quality: ShellCheck, Ansible Lint, Snyk IaC, SonarCloud in CI |

### Non-Functional Requirements

| Ref | NFR | Source |
|---|---|---|
| NFR-01 | **Rebuild-safe** — pve-test is ephemeral; all state is in code, not in running containers | Phase plan conventions |
| NFR-02 | **One service per LXC** — no co-location of unrelated services | Observations §00b |
| NFR-03 | **Default-deny east-west** — all inter-zone traffic is explicit | GreenField §2, NetworkPlanning |
| NFR-04 | **Management access via VPN/tailnet** — no management ports exposed to internet *(target state; deferred to Phase 07 per ADR-05; bridge: MikroTik ACL restricts mgmt interface access to operator IPs per SEC-05)* | GreenField §2 |
| NFR-05 | **Images must source from Harbor** — no direct Docker Hub pulls at runtime | Phase 06 |
| NFR-06 | **Phased gating** — no phase starts until prerequisites from the prior phase are met | Plan README |
| NFR-07 | **IaC policy compliance** — Snyk IaC clean before merging Terraform changes | CLAUDE.md |
| NFR-08 | **Reproducibility** — pve-test wipe-and-rebuild must produce an identical result from code | Phase conventions |

### Security Hardening Constraints (Red Team Analysis — 2026-04-15)

The following constraints were identified through adversarial analysis and must be treated as architectural requirements, not optional hardening:

| Ref | Constraint | Attack vector mitigated |
|---|---|---|
| SEC-01 | CI runner (`build_seg`) egress must be restricted at MikroTik — allow only Harbor (`10.57.3.10`), apt-cacher (`10.57.3.11`), GitHub API/Actions, and package registries. Block all other outbound. | Compromised dependency → runner pivot to infra_seg via unrestricted egress |
| SEC-02 | Portainer agent communication must use TLS with mutual certificate auth (step-ca issued certs). Anonymous/plain socket exposure is not permitted. | Portainer server compromise → Docker socket access across all zones |
| SEC-03 | `.env` secrets are ephemeral — materialised from Bitwarden vault at deployment time via `bw unlock` session token and never persisted on disk beyond the active session. No static `.env` file stored on the operator workstation. *(Bridge period: `sync-secrets.sh` in repo populates `.env` at session start; the file must be deleted after each deployment session. This is the accepted operational procedure until Vault is available in Phase 07.)* | Workstation compromise → `.env` exfiltration → full Proxmox API access |
| SEC-04 | Traefik must enforce rate limiting on all Authentik-facing routes. Authentik brute-force protection (account lockout, CAPTCHA) must be enabled. Consider Cloudflare proxy (orange cloud) in front of edge for WAF/DDoS mitigation. | Brute-force Authentik login → valid session → internal admin dashboard access |
| SEC-05 | MikroTik management interface must not be accessible from the flat LAN. Access restricted to operator IPs via ACL, or via VPN only. MikroTik hardening (disable unused services, SSH key auth only) is a prerequisite before any SDN zone is relied upon for isolation. | MikroTik compromise → inter-VLAN ACL removal → full zone isolation collapse |
| SEC-06 | Harbor anonymous pull must be disabled. All image pulls — including internal service-to-service — require robot account authentication. | Compromised LXC → anonymous Harbor pull → image enumeration and SAST evasion analysis |
| SEC-07 | Cloudflare DNS API token must be scoped to minimum: `Zone:DNS:Edit` for `gibbsgreatly.xyz` only. Token must be rotated after each development pass and stored only in Bitwarden (never in `.env` template or committed files). | Token leak → arbitrary DNS record creation → Let's Encrypt cert for any subdomain → service impersonation |

### Open Items

1. **NetBox Terraform provider** not yet implemented — IP allocations are still manual (candidate for Phase 07)
2. ~~**NPM (Nginx Proxy Manager)** should be deployed earlier~~ — **Closed.** Evaluated and rejected by ADR-02. Traefik is the sole reverse proxy. Services are accessed by IP during early phases.
3. **Shell script CI coverage** (ShellCheck) — Phase 03 observation still open
4. **Remote access control plane** (VPN/tailnet) — deferred to Phase 07 per ADR-05; immediate mitigation is MikroTik ACL per SEC-05
5. **Phase 01 runner recovery** — repository-level security checks already run on GitHub-hosted runners, but self-hosted `terraform-validate`, `ansible-lint`, and planned Phase 05 image/SBOM/signing jobs depend on `ci-runner-01` being restored and re-enabled

---

## Architectural Decisions

### ADR-01: CI/CD Platform

**Status:** Decided
**Context:** GreenField §4 identifies both GitHub Actions and Forgejo as viable options without deciding. Current implementation uses GitHub Actions with a self-hosted runner on `build_seg`.

**Options considered:**

| Option | Pros | Cons |
|---|---|---|
| GitHub Actions + self-hosted runner | Works today; SHA-pinned actions; native VS Code/Copilot integration | GitHub is external trust root; outage stops all CI; no air-gap path |
| Forgejo (self-hosted) | Full sovereignty; mirrors self-hosted philosophy; enables offline builds | Another service to deploy and operate before the platform is stable |

**Decision:** GitHub Actions + self-hosted runner for all current phases. Forgejo evaluated as a Phase 07 candidate once the platform has proven stability through at least one full pve-test rebuild cycle.

**Rationale:** The intended runner location is `build_seg`, not `mgmt_seg`, so build execution stays outside the management plane. GitHub-hosted jobs already cover repo-level checks such as Trivy filesystem scanning, Snyk IaC, TruffleHog, SonarCloud, Terraform format, Harbor image policy, and SOPS decryption. Self-hosted jobs are reserved for runner-dependent validation and later image pipeline work. Adding Forgejo before core shared services are stable still inverts operational priorities. SEC-01 (runner egress restriction) mitigates the primary supply chain risk of the external CI platform.

---

### ADR-02: Reverse Proxy

**Status:** Decided
**Context:** Phase 04 specifies Traefik. Observations §General-2 suggests NPM should be deployed early for faster service validation. These conflict.

**Options considered:**

| Option | Pros | Cons |
|---|---|---|
| Traefik | IaC-native (file/label config); Authentik forward-auth first-class; dual-resolver (Let's Encrypt + step-ca); rate limiting available | Requires more upfront config than NPM |
| Nginx Proxy Manager | GUI-driven, fast onboarding during early phases | Config not auditable/versionable; no forward-auth without plugins; creates two parallel proxies |
| Both (NPM early, Traefik later) | Fast early validation | Split trust, routing confusion, operational overhead to migrate |

**Decision:** Traefik is the sole reverse proxy. NPM is not deployed at any phase.

**Rationale:** Services without a Traefik route are accessed directly by IP during early phases. This is acceptable for operator-only services and avoids the cost of running and migrating away from NPM. Aligns with NFR-08 (reproducibility) — all proxy config is in code from day one.

---

### ADR-03: Metrics Stack

**Status:** Decided
**Context:** Phase 04 specifies VictoriaMetrics + Grafana + Loki without documented rationale.

**Options considered:**

| Option | Pros | Cons |
|---|---|---|
| VictoriaMetrics | Lower memory footprint; drop-in Prometheus-compatible API; better long-term storage performance; single binary | Smaller community than Prometheus |
| Prometheus | Industry standard; extensive documentation and dashboard ecosystem | Higher memory use; Alertmanager is a separate component; long retention needs Thanos/Cortex |

**Decision:** VictoriaMetrics + Grafana + Loki (confirmed).

**Rationale:** pve-test is a single bare-metal node with 32 GB RAM shared across all services. VictoriaMetrics' lower memory footprint is a material advantage. Prometheus-compatible API means all Grafana dashboards, Ansible exporters, and Terraform monitoring integrations work unchanged.

---

### ADR-04: Container Management Plane

**Status:** Decided
**Context:** Portainer is deployed in Phase 00b and has agents across multiple zones. Its role relative to Terraform/Ansible as the control plane is not formally defined.

**Options considered:**

| Option | Pros | Cons |
|---|---|---|
| Portainer as primary control plane | GUI convenience; fast interactive debugging | Drift from IaC state; Docker socket exposed cross-zone (SEC-02); violates NFR-08 |
| Terraform/Ansible as primary | Single source of truth; rebuild-safe; auditable; no cross-zone socket exposure | No live GUI visibility |
| Portainer as observability only (read access) | GUI visibility retained; control-plane risk eliminated; SEC-02 blast radius limited | Portainer agents still require TLS (SEC-02) |

**Decision:** Terraform/Ansible is the control plane. Portainer is deployed in observability-only mode (read access). No container is ever created or modified via the Portainer UI.

**Rationale:** Aligns with NFR-08 (reproducibility) — if a container can be created via GUI, the rebuild is no longer fully reproducible. SEC-02 still applies: Portainer agents deployed with step-ca mutual TLS. Portainer read-only mode limits blast radius if the Portainer server is compromised.

---

### ADR-05: Remote Operator Access

**Status:** Deferred (Phase 07)
**Context:** GreenField §2 specifies management access behind a VPN or tailnet. SEC-05 flags MikroTik management on the flat LAN as a risk. Neither a VPN service nor a formal access policy is part of the active pve-test plan.

**Options considered:**

| Option | Pros | Cons |
|---|---|---|
| Tailscale | Zero-config; device-level ACLs; works immediately | External control plane dependency |
| WireGuard (self-hosted) | Full sovereignty; no external control plane | Requires public endpoint or DDNS; operational complexity |
| LAN-only (current) | No overhead while building locally | MikroTik management exposed on flat LAN; no remote access path |

**Decision:** LAN-only is acceptable during active pve-test development (operator is always on LAN). Tailscale is the Phase 07 target for production remote access. MikroTik ACL restriction (SEC-05) applies immediately regardless of VPN decision.

**Rationale:** Adding a VPN service before Phase 04 core services are stable adds unnecessary failure domains. The immediate mitigation (SEC-05 MikroTik ACL) eliminates the most critical exposure without adding infrastructure.

---

### ADR-06: Secrets Runtime Delivery

**Status:** Decided (current phases); Vault deferred to Phase 07
**Context:** Current approach is Bitwarden CLI → `.env` → `source .env`. There is no runtime secret delivery mechanism for running containers — secrets are passed as Docker environment variables at deploy time.

**Options considered:**

| Option | Pros | Cons |
|---|---|---|
| `.env` injection (current) | Simple; Bitwarden is already the vault; no additional infrastructure | Secrets visible in `docker inspect`; no rotation without redeployment; no audit log of access |
| HashiCorp Vault | Dynamic secrets; audit log; lease-based rotation; first-class Terraform/Ansible integration | Another service to deploy and operate; Phase 07 complexity |
| Docker secrets / K8s secrets | Native platform integration | Not using Swarm or Kubernetes |

**Decision:** `.env` injection with SEC-03 ephemeral constraint enforced for all current phases. HashiCorp Vault evaluated as a Phase 07 candidate for runtime secret rotation.

**Rationale:** Adding Vault before the platform is stable inverts priorities. SEC-03 (`.env` materialised ephemerally from Bitwarden at deploy time, never persisted) is the minimum required bar. `docker inspect` secret exposure is accepted as a known limitation for the current phase — addressed via network segmentation (secrets only visible to operator on `mgmt_seg`) and rebuild-cycle rotation.

---

## Threat Model

**Method:** STRIDE, per asset class.
**Date:** 2026-04-15
**Status:** Initial pass. Threats fully addressed by existing SEC-01 through SEC-07 constraints are omitted. All IDs below are net-new gaps.

### Threat ID Reference

| ID | Asset | STRIDE | Threat | Risk |
|---|---|---|---|---|
| TM-01 | Operator workstation | Info Disclosure | The age private key at `~/.config/sops/age/keys.txt` decrypts all infrastructure credentials in `terraform/secrets.enc.yaml`. Workstation compromise = full secret corpus exfiltration. | **Critical** |
| TM-02 | Operator workstation | Info Disclosure | `sync-secrets.sh` populates `.env` at session start. If the `.env` file is not deleted post-session (SEC-03 procedure), static credentials persist on disk indefinitely. The deletion step is manual and therefore unreliable. | **High** |
| TM-03 | Operator workstation | Spoofing | Bitwarden `bw unlock` session token scope and lifetime are not documented. A long-lived unlock token left in env is equivalent to a plaintext credential cache. | **High** |
| TM-04 | Operator workstation | Elevation | No workstation hardening policy documented. If the operator account has passwordless sudo, a malicious process running as the operator has immediate access to age key and unlock token material. | **Medium** |
| TM-05 | GitHub Actions / CI | Elevation | Self-hosted runner in `build_seg` executes code from the repository. A malicious PR using `pull_request_target` that triggers CI on the self-hosted runner can run arbitrary code with runner network access. The workflow trigger policy for self-hosted runners has not been confirmed safe. | **Critical** |
| TM-06 | GitHub Actions / CI | Tampering | If any third-party Actions are not SHA-pinned, upstream tag mutation is a silent supply chain attack vector. This repository currently mitigates that risk by SHA-pinning the active workflow actions, but the control must be maintained as workflows change. | **High** |
| TM-07 | GitHub Actions / CI | Info Disclosure | `SOPS_AGE_KEY`, `HARBOR_ROBOT_PASSWORD`, `SONAR_TOKEN`, and `SNYK_TOKEN` are stored as GitHub Actions secrets. GitHub is the external trust root (ADR-01). A GitHub account compromise bypasses all internal controls. | **High** |
| TM-08 | GitHub Actions / CI | Repudiation | If the runner LXC is compromised, GitHub Actions logs can be tampered with at the runner level before upload. No independent audit log exists for runner-executed operations. | **Medium** |
| TM-09 | MikroTik router | Tampering | MikroTik configuration is not managed by IaC. A config change that removes VLAN ACLs eliminates all zone isolation. No automated config backup or drift detection is in place. | **Critical** |
| TM-10 | MikroTik router | Info Disclosure | MikroTik config backup location is not documented. Backups may contain pre-shared keys and VLAN ACL rules whose structure is useful intelligence for an attacker. | **Medium** |
| TM-11 | MikroTik router | Tampering | MikroTik firmware patch cadence is not documented. RouterOS has had remotely exploitable CVEs (e.g., Chimay Red/Blue). An unpatched border device invalidates all downstream zone controls. | **High** |
| TM-12 | step-ca | Tampering | step-ca root CA private key protection mechanism is not documented. If the root key is stored unencrypted on the mgmt_seg LXC, compromise of that LXC yields the ability to forge certificates trusted by all internal services. | **Critical** |
| TM-13 | step-ca | Repudiation | No OCSP responder or CRL distribution point is documented. If a service certificate is compromised, there is no revocation mechanism — all services continue to trust it until manual rotation. | **High** |
| TM-14 | step-ca | Spoofing | The root/intermediate CA architecture is not documented. If step-ca is deployed as a single root (no offline root + online intermediate), the key signing operational certs is also the root of trust — larger blast radius from an online compromise. | **Medium** |
| TM-15 | Authentik | Elevation | Traefik forward-auth middleware must be applied to every internal route requiring auth. A misconfigured router omitting `authentik@file` middleware exposes that service unauthenticated. No documented policy or automated check enforces this. | **High** |
| TM-16 | Authentik | Spoofing | OIDC/OAuth2 client secrets for applications registered in Authentik are not referenced in the secrets management documentation. If stored outside SOPS/Bitwarden, they are an undocumented credential surface. | **Medium** |
| TM-17 | Authentik | Denial of Service | No HA or failover for Authentik is documented. An Authentik outage makes all SSO-protected services simultaneously inaccessible. | **Medium** |
| TM-18 | Harbor | Tampering | Cosign image signature verification is configured in Harbor (Phase 05) but is not yet enforced at the container runtime level. A container can be started with an image that has no valid Cosign signature if the runtime-level policy is absent. | **High** |
| TM-19 | Harbor | Info Disclosure | If a Harbor project is misconfigured as public, external actors can enumerate internal service topology (image names, tags, layer history) without credentials. SEC-06 addresses anonymous pull but not project-level visibility. | **Medium** |
| TM-20 | Harbor | Tampering | Trivy CI scan fails only on CRITICAL/HIGH severity. MEDIUM-severity vulnerabilities are permitted to promote to Harbor without compensating control. Some exploit chains begin at MEDIUM severity. | **Low–Medium** |
| TM-21 | Terraform API token | Elevation | Terraform API token role scoping is not documented. If the token holds `PVEAdmin` or `Administrator` rather than a minimal role, a CI compromise delivers full Proxmox API control — VM deletion, network reconfiguration, etc. | **High** |
| TM-22 | Secrets architecture | Info Disclosure | No documented rotation schedule or trigger for the age key. A long-lived age key that is never rotated extends the TM-01 exposure window indefinitely. | **Medium** |
| TM-23 | Secrets architecture | Elevation | `SOPS_AGE_KEY` stored in GitHub Actions secrets grants any workflow with access to that secret the ability to decrypt all infrastructure credentials. There is no separation between "can decrypt SOPS" and "can access infrastructure." | **High** |
| TM-24 | SDN / Proxmox | Elevation | All zones share a single Proxmox host. A container escape (LXC privilege escalation via kernel vulnerability) reaches the hypervisor and all other zones. No hardware boundary exists between zones. | **High** |
| TM-25 | SDN / Proxmox | Tampering | VLAN tagging is enforced at the Linux bridge. A misconfigured LXC with trunk mode or incorrect VLAN tag may receive traffic from unintended zones. No documented audit of per-LXC VLAN assignments. | **Medium** |
| TM-26 | SDN / DNS | Info Disclosure | Internal service names resolving via public Cloudflare DNS expose internal topology (service names, IP ranges) to external actors. DNS split-horizon is not documented. | **Medium** |
| TM-27 | Observability / Loki | Repudiation | Loki is in mgmt_seg. If mgmt_seg is compromised, an attacker can delete or corrupt logs before detection. No immutable log destination (external syslog, S3 with object lock) is documented. | **High** |
| TM-28 | Grafana | Info Disclosure | Grafana authentication mechanism (Authentik SSO vs. local accounts) is not confirmed in the architecture. Local accounts bypass the SSO revocation path. | **Medium** |

### Deferred Threats (Phase 07 gap)

Controls deferred to Phase 07 that leave current gaps:

| ID | Deferred Control | Current Exposure |
|---|---|---|
| TM-29 | OpenBao runtime secrets | Static long-lived credentials in SOPS; no dynamic issuance, leasing, or rotation |
| TM-30 | Falco runtime detection | No runtime detection of container anomalies; exploitation of TM-24 would be undetected |
| TM-31 | CrowdSec behavioural blocking | Static Traefik rate limiting only (SEC-04); no adaptive edge blocking |
| TM-32 | Tailscale/VPN remote access | Management access LAN-only; SEC-05 MikroTik ACL is the sole bridge control |

### Priority Summary

| Priority | IDs | Action |
|---|---|---|
| **P0 — Address before next phase** | TM-01, TM-05, TM-09, TM-12 | Critical blast radius — full infrastructure or zone isolation compromise |
| **P1 — Address before production** | TM-06, TM-07, TM-11, TM-13, TM-15, TM-18, TM-21, TM-23, TM-27 | High-severity gaps against core security controls |
| **P2 — Plan within active phases** | TM-02, TM-03, TM-14, TM-16, TM-24, TM-25, TM-26 | Meaningful risk requiring design decisions |
| **P3 — Track** | TM-04, TM-08, TM-10, TM-17, TM-19, TM-20, TM-22, TM-28 | Lower severity or mitigated by in-flight work |
