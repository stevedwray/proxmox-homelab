# Green Field Home Lab Architecture

> **Implementation note (2026):** This document is the original architectural design
> reference. The build is in progress on `pve-test`, a **bare-metal laptop** running
> Proxmox (not a nested VM). All services run on pve-test only; pve (production) is not
> used during development passes. The network model uses **Proxmox SDN VLAN zones** with
> the MikroTik as L3 gateway (not Simple zones). **Chainloop** has been descoped from
> Phase 05 — no self-hosted Docker Compose deployment path exists upstream; the Chainloop
> Cloud free tier is the viable alternative if attestation is later required. For the
> current operational plan, see `docs/plan/README.md`.

## 1) Platform layout

I would split the lab into five logical planes:

**Management plane**
Proxmox management, PBS, NetBox, identity, CA, secrets, monitoring, CI runners, registry, and Git. This is the most trusted segment.

**Application plane**
arr stack, Jellyfin, Pi-hole, internal reverse proxies, helper services.

**Security plane**
Security Onion, Wazuh manager/indexers if you keep them, any sandbox or vuln-lab systems.

**Game/services plane**
Minecraft and other game servers. These are operationally different from the media stack and often merit looser tuning, different backup cadence, and sometimes public exposure.

**Ingress/edge plane**
A dedicated reverse proxy or proxy pair, ideally the only path from the internet into the internal application plane.

Proxmox SDN and firewalling are a good native base for this sort of segmentation rather than relying only on per-container Docker networks. ([Proxmox VE][1])

My placement rule would be:

* **VMs:** Security Onion, Proxmox Backup Server, CI/Git if you want hard isolation, maybe Harbor if heavily used.
* **LXCs running Docker:** arr stack, Jellyfin, utility services, maybe game services.
* **Dedicated edge LXC/VM:** reverse proxy and internet-facing auth-protected apps.

That is a design recommendation rather than a vendor requirement, but it lines up with the trust and blast-radius differences between those workloads.

## 1a) Automation layers

The implementation is split across three automation layers, and the design should treat
all three as first-class parts of the platform:

* **Host bootstrap** — Proxmox host preparation, package repositories, Terraform API user/token setup, firewall backend capability, storage baseline, and template creation. In this repository this currently lives under `ansible/00-initial-setup` and `ansible/01-base-system`.
* **Infrastructure provisioning** — network intent, LXC creation, and shared Ansible-driven provisioning. In this repository this lives under `terraform/lxc` and `terraform/lxc/ansible`.
* **Service and application deployment** — phased deployment of shared services, supply-chain controls, and application migrations. This is driven by `docs/plan/`.

For the current pve-test rebuild, host bootstrap is not “background tooling” or an
operator-only concern. It is part of the planned platform implementation and must be kept
aligned with the current pve-test model:

* bare-metal `pve-test`
* Proxmox SDN VLAN zones on a VLAN-aware `vmbr0`
* MikroTik-owned L3 gateways
* `infrastructure-containers` as the active target storage pool for LXC stacks unless a phase explicitly introduces a new storage model

Any future development of the host/bootstrap Ansible should therefore be reflected in the
design and phased plan, not treated as repo-local implementation detail.

## 2) Network design

Build the network first. A secure homelab is mostly a segmentation exercise.

For the current implementation, the intended model is **Proxmox SDN VLAN zones** on a
VLAN-aware `vmbr0`, with the MikroTik acting as the L3 gateway. In other words, VLANs
did not replace SDN in the plan; VLAN-backed zones are the current SDN design.

The active pve-test plan currently uses these SDN segments:

* **build_seg** – CI build workloads
* **mgmt_seg** – identity, PKI, monitoring, and management-plane services
* **edge_seg** – reverse proxy / ingress
* **infra_seg** – Harbor, apt-cacher, NetBox, and other shared build dependencies

Additional zones such as app, game, backup, or security segments may still be introduced
later, but they are not part of the active pve-test implementation path today.

The main rule is that east-west communication should be explicit, not implicit. For example, Jellyfin may need media storage and auth; it should not also be able to talk to Harbor, CI, Git, or Proxmox. The Proxmox firewall and SDN feature set are directly aimed at guest network separation and centralized traffic policy. ([Proxmox VE][1])

For remote administration, the design intent is still to keep management access behind a
trusted VPN or tailnet rather than exposing management ports directly. The exact remote
access control plane is not part of the active implementation plan today.

## 3) Identity, auth, and certificates

For identity, **Authentik** is the obvious open-source fit. It is a self-hosted identity provider, supports reverse-proxy patterns, and its docs explicitly call out reverse proxy deployment requirements and websocket-aware behavior. ([authentik][3])

Use it for:

* SSO to internal web apps
* MFA for operator-facing apps
* role-based access to dashboards and admin tools
* group-based access for family/non-admin users if needed

For internal PKI, I would add **step-ca**. It is an online CA for automated X.509 and SSH certificate management, which is extremely useful in a lab where internal TLS otherwise turns into a mess of self-signed certs and exceptions. ([Smallstep][4])

That combination gives you:

* user identity via Authentik
* service identity via step-ca
* much less password and certificate sprawl

## 4) Source control and CI

Because you work in VS Code with Copilot and Claude Code, the easiest path is still **GitHub repos with self-hosted runners in the lab**. But if you want full sovereignty, **Forgejo** is a very credible self-hosted option now, with Actions-style workflows and separate runners. Forgejo workflows are executed by runners rather than by the Forgejo server itself, which is the right operational model. ([Forgejo][5])

For greenfield, I would choose one of these two:

**Pragmatic path**

* GitHub
* self-hosted runner in mgmt zone
* local-only secrets and internal network access on the runner

**Full self-hosted path**

* Forgejo
* Forgejo Runner
* same pipeline design, all in-lab

Given your tooling habits, I would probably start with the pragmatic path and only move Git hosting in-house later.

Your CI stages should be:

1. **lint/format**
2. **static analysis and secrets scan**
3. **IaC policy checks**
4. **container/image build**
5. **SBOM generation**
6. **vulnerability/misconfiguration scan**
7. **attestation and policy gate**
8. **push/promote to Harbor**
9. **deploy**
10. **post-deploy verification**

## 5) Supply chain: Harbor + signing + optional attestations

This is where your background makes the platform unusually worthwhile.

**Harbor** should be your single internal registry. Harbor supports vulnerability scanning with Trivy, supports pluggable scanners, supports robot accounts for automation, and supports storing Cosign signatures alongside OCI artifacts. ([Harbor][6])

An attestation and evidence layer can sit on top of CI later, but it is not part of the
active self-hosted build plan today. The current plan focuses first on Harbor, Trivy,
Syft, Cosign, and policy checks in CI. If attestation is revisited later, it should be
treated as a follow-on capability rather than a prerequisite for the current platform.

The supply-chain flow I would use is:

* repo push / PR
* CI runs Trivy on repo/filesystem and generated images
* CI generates SBOM with **Syft**
* CI signs built images with **Cosign**
* CI records scan and validation results
* policy evaluates:

  * no critical vulns unless explicitly waived
  * no blocked misconfigs
  * required tests/lints passed
  * required metadata present
* only then is the image promoted in Harbor
* deployment consumes only approved Harbor tags/digests

Syft is built for SBOM generation from container images and filesystems, while Trivy supports vulnerabilities, misconfigurations, secrets, licenses, and filesystem/image scanning. OPA can evaluate Terraform plans before apply. ([GitHub][8])

One practical caveat: Harbor’s Cosign support exists and is useful, but there have also been recent compatibility/reporting issues around some newer Cosign/OCI formats, so I would test your chosen Harbor/Cosign versions together before standardizing on them. ([Harbor][9])

## 6) Secrets and configuration

For secrets, I would split this into two layers:

**SOPS + age** for Git-stored encrypted config
SOPS supports YAML, JSON, ENV, INI, and binary formats, which makes it a strong fit for Terraform vars, Ansible vars, Compose env files, and app configuration. ([SOPS: Secrets OPerationS][10])

**OpenBao** for runtime-distributed secrets and dynamic credentials
OpenBao exists specifically to manage, store, and distribute secrets, certificates, and keys, and supports secrets engines including database-related ones. ([OpenBao][11])

My recommendation:

* use **SOPS** immediately
* add **OpenBao** only when you actually need centrally brokered secrets, leasing, rotation, or dynamic credentials

That keeps the greenfield design strong without overbuilding too early.

## 7) Deployment model

I would keep deployment simple and deterministic:

* **Terraform/OpenTofu** for Proxmox infrastructure objects, networks, templates, and VM/LXC creation
* **Ansible** for inside-guest configuration, package baselines, Docker installation, Compose stack delivery, and service hardening
* app deployment from **Git + CI-produced artifacts**
* all images pulled from **Harbor only**
* no direct Docker Hub pulls from runtime hosts except perhaps one controlled “build/import” host

This is where your earlier Harbor idea becomes important: the runtime hosts should not be general-purpose internet package/image consumers if you want strong hygiene.

For policy-as-code:

* use **OPA/Conftest** on Terraform plans and selected manifests
* use **ansible-lint**
* use Trivy IaC scans on repo files
* optionally ingest Snyk/Sonar findings into a later attestation/evidence layer

OPA explicitly supports Terraform policy checks before changes are applied, and Conftest can also be used against Ansible playbooks. ([Open Policy Agent][12])

## 8) Ingress and exposed services

Do not expose application containers directly.

Put all public-facing HTTP/S behind one edge layer:

* reverse proxy
* auth integration
* WAF/bouncer if desired
* rate limiting / IP reputation
* central certificate management

If you stay Docker-centric, **Traefik** is a strong fit because it integrates dynamically with orchestrators and container environments. **Caddy** is also excellent if you prefer simpler config and automatic HTTPS. ([Traefik Labs Documentation][13])

For added protection, two relevant open-source components are:

* **CrowdSec**, which is a behavior-based detection/blocking engine with bouncers and optional AppSec/WAF integration. ([CrowdSec Documentation][14])
* **open-appsec**, which now has explicit NGINX Proxy Manager integration and is positioned as an open-source WAF add-on for reverse proxies. ([OpenAppSec Documentation][15])

For your lab, I would expose only:

* maybe Jellyfin
* maybe selected game services
* perhaps one or two dashboards behind SSO
* nothing in the management plane

Everything else should be internal-only, reachable via VPN/tailnet.

## 9) Runtime security and detection

Because you are in appsec and vuln management, I would treat runtime detection as a separate layer from vuln scanning.

Two useful open-source additions:

**Falco**
Falco provides runtime detection for Linux hosts and containers by monitoring kernel events and applying rules for suspicious behavior and compliance-relevant activity. ([Falco][16])

**CrowdSec**
Best for exposed web-facing systems and SSH-like log-driven blocking, rather than deep container runtime telemetry. ([CrowdSec Documentation][14])

I would use:

* **Falco** on Docker hosts or a subset of more sensitive hosts
* **CrowdSec** on the edge and perhaps SSH entry points
* **Security Onion** for packet/log analytics where you want richer network visibility
* **Wazuh** only if you still value it for host telemetry/use cases that Security Onion is not covering for you

## 10) Observability and asset inventory

For monitoring, I would keep it boring and cheap:

* **VictoriaMetrics** for metrics storage if you want a lighter Prometheus-style backend
* **Grafana** for dashboards
* **Loki** for log aggregation
* optional exporters from Proxmox, Docker hosts, apps, UPS, NAS, etc.

Loki is designed as a cost-effective log aggregation system that indexes labels rather than full log contents. VictoriaMetrics is positioned as a fast and scalable Prometheus-compatible metrics backend. ([Grafana Labs][17])

For source of truth, I strongly recommend **NetBox**. NetBox exists precisely to model IPAM/DCIM and act as a source of truth for automation. In a lab like yours, it becomes the place to document:

* VLANs and subnets
* LXC/VM ownership and purpose
* service ports and dependencies
* clusters, nodes, storage, racks
* public exposure and business criticality tags ([NetBox Labs][18])

That pays off quickly once the lab stops fitting in your head.

## 11) Backup and disaster recovery

Use **Proxmox Backup Server** for VM/LXC backups and host-integrated retention. PBS provides deduplication, integrity verification, and encrypted client-to-server traffic. ([Proxmox Backup Server][19])

Then add a second layer for application data:

* **Kopia** for encrypted, deduplicated file-level backups of important bind mounts, config repos, and game worlds
* or just use app-native backups plus PBS if you want fewer moving parts

Kopia is explicitly an encrypted, deduplicated snapshot-based backup tool for local and remote storage. ([Kopia][20])

My DR rule would be:

* PBS for restore-the-machine
* app/data backups for restore-the-service
* one off-host or offline copy for ransomware/operator-error resilience

## 12) Maintenance and hygiene

A greenfield secure lab also needs continuous maintenance, not just good initial design.

I would include:

**Renovate**
for automated dependency and image update PRs on a schedule. Renovate is specifically built to open update PRs for package files and dependencies across many ecosystems. ([GitHub][21])

**Scheduled CI jobs**
for:

* image rebuilds
* scan refreshes
* base-image drift checks
* expiring certificate alerts
* backup verification
* restore drills

**Versioned golden templates**
for your Docker-capable Debian LXCs and special-purpose VMs.

**Immutable-ish deployment pattern**
Prefer rebuilding/redeploying from Git over hand-tuning containers in place.

## 13) Concrete greenfield stack I would actually build

### Must-have foundation

* Proxmox VE
* Proxmox Backup Server
* NetBox
* Authentik
* step-ca
* GitHub + self-hosted runner, or Forgejo + Forgejo Runner
* Harbor
* Trivy
* SOPS
* Grafana + metrics + logs

### Strongly recommended next

* Cosign
* Syft
* Renovate
* CrowdSec
* Falco

### Optional / add when justified

* OpenBao
* open-appsec
* Wazuh, if it still gives you signal you want in parallel with Security Onion
* additional policy packs with OPA/Conftest

## 14) The operating model I’d target

The final operating model would be:

**Code**

* Terraform/Ansible/Compose in Git

**Change**

* PR triggers lint, scan, policy, SBOM, test

**Evidence**

* scan, validation, and SBOM outputs are retained in CI and artifact storage

**Artifact**

* signed image and evidence pushed to Harbor only if policy passes

**Deploy**

* Terraform/Ansible deploy from approved artifacts/config

**Run**

* segmented networks, SSO, internal PKI, centralized ingress

**Observe**

* metrics/logs/runtime alerts into dashboards/SIEM

**Recover**

* PBS + app/data backups + documented restores

That is the point where your homelab starts to resemble a compact internal platform rather than a collection of servers.

## 15) My opinionated “best fit for you”

Because you are an appsec and infra vuln-management person, I would optimize for **auditability and repeatability**, not maximum homelab novelty.

So I would start in this exact order:

1. **Network segmentation + Proxmox layout**
2. **Git + CI runner**
3. **Harbor**
4. **Trivy + Syft + Cosign**
5. **Authentik + step-ca**
6. **Monitoring/logging**
7. **NetBox**
8. **PBS + restore practice**
9. **Only then migrate the app stacks**

That order gives you the platform first and the hobby apps second, which is the right sequence if the actual objective is a secure and maintainable lab.

If you want, I’ll turn this into a **phased build plan** for Proxmox with specific VM/LXC roles, zones, and “build this first / later” priorities.

[1]: https://pve.proxmox.com/pve-docs/chapter-pve-firewall.html?utm_source=chatgpt.com "Proxmox VE Firewall"
[3]: https://docs.goauthentik.io/install-config/reverse-proxy/?utm_source=chatgpt.com "Reverse proxy"
[4]: https://smallstep.com/docs/step-ca/?utm_source=chatgpt.com "step-ca Certificate Authority Overview"
[5]: https://forgejo.org/docs/latest/user/actions/?utm_source=chatgpt.com "Forgejo Actions | Reference"
[6]: https://goharbor.io/docs/2.13.0/administration/robot-accounts/?utm_source=chatgpt.com "Harbor docs | Create System Robot Accounts"
[8]: https://github.com/anchore/syft?utm_source=chatgpt.com "anchore/syft: CLI tool and library for generating a Software ..."
[9]: https://goharbor.io/docs/edge/working-with-projects/working-with-images/sign-images/?utm_source=chatgpt.com "Sign Artifacts with Cosign or Notation"
[10]: https://getsops.io/docs/?utm_source=chatgpt.com "SOPS: Secrets OPerationS"
[11]: https://openbao.org/?utm_source=chatgpt.com "OpenBao"
[12]: https://openpolicyagent.org/docs/terraform?utm_source=chatgpt.com "Terraform"
[13]: https://doc.traefik.io/traefik/?utm_source=chatgpt.com "Traefik Proxy Documentation"
[14]: https://docs.crowdsec.net/docs/intro/?utm_source=chatgpt.com "Security Engine Overview"
[15]: https://docs.openappsec.io/integrations/nginx-proxy-manager?utm_source=chatgpt.com "NGINX Proxy Manager"
[16]: https://falco.org/?utm_source=chatgpt.com "Falco"
[17]: https://grafana.com/oss/loki/?utm_source=chatgpt.com "Grafana Loki OSS | Log aggregation system"
[18]: https://netboxlabs.com/docs/netbox/?utm_source=chatgpt.com "index | NetBox Documentation"
[19]: https://pbs.proxmox.com/docs/technical-overview.html?utm_source=chatgpt.com "Technical Overview — Proxmox Backup 4.1.5-1 ..."
[20]: https://kopia.io/docs/?utm_source=chatgpt.com "What is Kopia?"
[21]: https://github.com/renovatebot/renovate?utm_source=chatgpt.com "renovatebot/renovate: Home of the Renovate CLI ..."


## Historical appendix

The remaining phased sketch below is retained as original design background. Where it
differs from the 2026 implementation note at the top of this document or from
`docs/plan/README.md`, the active plan and current pve-test design should be treated as
authoritative.


## Phase 0 — Define the target and keep dev separate

Create two environments from day one:

* **pve-dev**: a nested Proxmox cluster or single-node instance inside your existing Proxmox
* **pve-prod**: your eventual real home lab estate

The purpose of `pve-dev` is to validate templates, Terraform, Ansible roles, Harbor workflows, backup jobs, firewalling, and restore steps without risking your real media, security, or game services. Since Proxmox supports nested virtualization, this is a practical place to start. ([Proxmox VE][1])

I would keep success criteria for this phase very simple:

* you can destroy and rebuild the dev environment repeatedly
* nothing in dev is allowed to be “hand configured and precious”
* every change goes through Git

## Phase 1 — Stand up the virtual Proxmox dev environment

Inside your current Proxmox, build a **dedicated dev/testing VM layer**:

* 1 nested Proxmox VM at minimum
* ideally 2–3 nested Proxmox VMs if you want to test clustering, migrations, or distributed roles
* a separate VM or LXC for **Proxmox Backup Server**
* isolated virtual networks/VLANs for management, apps, edge, and security

The point here is not performance; it is **repeatability**. Proxmox is built around integrated compute, storage, networking, and backup/restore workflows, so this is the right place to prove those patterns before the real rollout. PBS is especially worth including from the beginning because its datastore model is based on deduplicated chunks with verification and client-side encryption support. ([Proxmox VE][2])

Exit criteria:

* nested Proxmox is reachable and manageable
* PBS is connected and can back up at least one guest
* you have named networks for `mgmt`, `apps`, `edge`, `games`, and `security`

## Phase 2 — Create the base automation repo and CI skeleton

Before deploying apps, create the Git structure and CI path.

I would split the repos like this:

* `proxmox-infra` — Terraform/OpenTofu for Proxmox-side resources
* `guest-config` — Ansible for inside-guest setup
* `images-and-stacks` — Dockerfiles, Compose files, helper scripts
* optionally `platform-policies` — OPA/Conftest/Chainloop contracts and policies

Then add CI with either:

* **GitHub Actions + self-hosted runner**, or
* **Forgejo + Forgejo Runner** if you want the forge in-lab

This phase is only about the **pipeline skeleton**, not full deployment yet:

* lint
* validate
* secret scan
* artifact build hooks
* manual approval stage placeholder

Chainloop fits in later, but its model is based on **contracts** that define what evidence a workflow must send and **control gates** that can block pipeline progression when policy fails, so it helps to shape the pipeline around evidence from the start. ([Chainloop Documentation][3])

Exit criteria:

* a commit triggers CI
* Terraform and Ansible basic validation runs
* secrets are not committed in plaintext

## Phase 3 — Build the golden guest baseline

Now automate the baseline guests you will reuse everywhere:

* Debian Docker LXC template
* Debian utility VM template
* optional dedicated edge proxy template
* optional CI runner VM template

At this stage, don’t deploy Harbor or Chainloop yet. Just make sure Terraform can create guests and Ansible can:

* set package baselines
* install Docker where needed
* apply hardening
* configure logging/monitoring agents
* set trusted internal CA roots later

The real deliverable here is a **golden-image-plus-role** pattern:

* Terraform creates
* Ansible configures
* no manual snowflakes

Exit criteria:

* you can create a fresh Docker host in dev from code
* destroy and recreate gives the same result
* the host is segmented into the right network zone

## Phase 4 — Add core shared services

Once the guest pattern is stable, deploy the shared platform services into `pve-dev`:

* **Harbor**
* internal reverse proxy
* identity provider
* internal CA
* NetBox
* monitoring/logging
* PBS jobs and retention
* self-hosted CI runner

Harbor is worth bringing in here because it supports vulnerability scanning with Trivy, robot accounts for automation, and Cosign-related signing workflows. Harbor also supports SBOM generation with Trivy in newer versions, which makes it a strong anchor for your image lifecycle. ([Harbor][4])

This is the phase where you decide your operating rule:

* **runtime hosts pull from Harbor only**
* not from Docker Hub directly, except maybe one controlled import/build path

Exit criteria:

* Harbor is running
* CI can authenticate to Harbor with a robot account
* one test image can be pushed, scanned, and pulled back internally

## Phase 5 — Add the software supply chain controls

Now layer in the security controls around builds and deployments.

Recommended stack:

* **Trivy** for image/filesystem/IaC scanning
* **Syft** for SBOMs
* **Cosign** for signing
* **Chainloop** for attestations, contracts, and control gates

The workflow should become:

1. code change
2. CI lint/validate
3. build image or package config artifact
4. generate SBOM
5. run scans
6. send evidence to Chainloop
7. Chainloop evaluates contract/policy
8. only on pass, promote artifact into approved Harbor location/tag
9. deploy from approved Harbor artifact only

That is exactly the kind of flow Chainloop is designed for: attestations containing evidence like vulnerability scans, SBOMs, and other workflow outputs, with contracts defining required materials and control gates enforcing policy. ([Chainloop Documentation][5])

I would start with just three required evidence types:

* SBOM present
* vuln scan present
* Terraform/Ansible validation passed

Then add Snyk/Sonar/OPA-style findings later.

Exit criteria:

* a deliberately vulnerable test image fails policy
* a clean test image passes and is promoted
* the deployment job consumes only the promoted image

## Phase 6 — Deploy one non-critical workload end to end

Do not start with Jellyfin or Security Onion.

Start with one **low-risk internal app** and prove the full lifecycle. Good candidates:

* a test nginx app
* a small internal dashboard
* a trivial utility service

The point is to prove:

* network placement
* ingress
* auth
* Harbor-only artifact sourcing
* Chainloop evidence gating
* backup
* log visibility
* rebuild from scratch

Only after that should you onboard something like Pi-hole or the arr stack.

Exit criteria:

* full rebuild from Git works
* restore from backup works
* app is reachable only as intended
* logs and metrics are visible

## Phase 7 — Onboard the real service classes in the right order

I would bring services in by **operational criticality**, not by popularity.

### 7A — Core infra services

Start with:

* Pi-hole / DNS services
* identity
* reverse proxy
* NetBox
* monitoring

These become shared dependencies for everything else.

### 7B — Internal apps

Then:

* arr stack
* supporting download/media utilities
* Jellyfin

These are good candidates for Docker inside LXC once your baseline is stable.

### 7C — Game services

Then:

* Minecraft
* other game servers

These deserve their own network zone and backup plan because they are often internet-facing or semi-public, and game-world data has different restore expectations than stateless apps.

### 7D — Security tooling

Then:

* Security Onion
* Wazuh
* Elasticsearch-related workloads

I would treat these as a separate track because they are heavier, noisier, and more likely to need dedicated VMs, storage planning, and network mirroring or tap/SPAN considerations than the app plane. That separation is an architectural judgment, but it fits the role differences in those products and keeps the platform rollout cleaner.

Exit criteria for each class:

* documented dependencies
* documented backup scope
* documented restore test
* documented network policy
* documented exposure level

## Phase 8 — Add policy and network hardening

Once the services are running, tighten the environment:

* default deny between zones
* only edge proxy exposed publicly
* management plane reachable only via VPN/tailnet
* CI runner allowed to reach only what it must
* runtime Docker hosts blocked from arbitrary outbound registry access
* per-service firewall rules documented in NetBox or Git
* signed images only for selected classes if you want to enforce that progressively

Proxmox’s firewalling and integrated networking model make it a good control point for this kind of segmentation. ([Proxmox VE][2])

This is also where I would add:

* periodic PBS verification jobs
* certificate expiration alerts
* dependency update PRs
* scheduled re-scan/rebuild jobs

PBS explicitly includes verification/integrity concepts in its architecture, so backup verification should be part of the normal maintenance plan, not an afterthought. ([Proxmox Backup Server][6])

Exit criteria:

* management plane is not publicly reachable
* at least one restore drill has been run
* at least one network isolation test has been run
* at least one failed-policy deployment has been demonstrated

## Phase 9 — Promote from dev to prod

Only now do you start building the real Proxmox estate with the same code.

The rule should be:

* `pve-dev` proves patterns
* `pve-prod` gets only code that has already passed through the dev environment and CI gates

Promotion should be:

* same Terraform modules
* same Ansible roles
* different inventory/vars
* same Harbor/Chainloop process
* different policy strictness if needed

In other words, treat the nested Proxmox lab as your **pre-production control plane for learning**.

## Suggested timeline and scope

I would chunk it like this:

**Wave 1**

* nested Proxmox dev
* PBS
* Git + CI skeleton
* Terraform + Ansible baseline

**Wave 2**

* Harbor
* reverse proxy
* identity
* monitoring/logging
* NetBox

**Wave 3**

* Trivy + Syft + Cosign
* Chainloop contracts and first control gate
* one demo workload end to end

**Wave 4**

* Pi-hole
* internal app stack
* arr/Jellyfin

**Wave 5**

* game services
* security tooling
* hardening and restore drills

## My opinionated minimum viable greenfield path

If you want the leanest version that still matches your goals, I would start with exactly this:

1. nested Proxmox VM(s)
2. PBS
3. one Git repo with Terraform + Ansible
4. one self-hosted CI runner
5. one Debian Docker template
6. Harbor
7. Trivy scan in CI
8. Chainloop with one contract
9. one demo app
10. only then move on to real workloads

That sequence gives you a secure platform path without trying to solve every problem on day one.

I can turn this into a **concrete build matrix** next, with suggested VM/LXC roles, rough sizing, and which pieces should live in nested dev versus eventual prod.

[1]: https://pve.proxmox.com/wiki/Nested_Virtualization?utm_source=chatgpt.com "Nested Virtualization"
[2]: https://pve.proxmox.com/pve-docs/pve-admin-guide.html?utm_source=chatgpt.com "Proxmox VE Administration Guide"
[3]: https://docs.chainloop.dev/concepts/contracts?utm_source=chatgpt.com "Contracts - Chainloop Documentation"
[4]: https://goharbor.io/docs/2.6.0/administration/vulnerability-scanning/?utm_source=chatgpt.com "Harbor docs | Vulnerability Scanning"
[5]: https://docs.chainloop.dev/quickstart?utm_source=chatgpt.com "Quickstart - Chainloop Documentation"
[6]: https://pbs.proxmox.com/docs/proxmox-backup.pdf?utm_source=chatgpt.com "Proxmox Backup Documentation"
