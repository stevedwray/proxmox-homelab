# Project Observations

Running notes and observations collected during the greenfield rebuild. Not actionable —
these are reflections for future reference when revisiting decisions, patterns, or problems.

---

## General

<!-- Add observations that apply across phases here -->

1. **NetBox deployment has been moved into Phase 03b (infra_seg, alongside Harbor).**
   A dedicated task (`03b-netbox-01-deploy-netbox.md`) and stack (`netbox-stack-test` /
   VMID 143 / `10.57.3.12`) now exist. NetBox is deployed immediately after Harbor and
   apt-cacher so all Phase 04 allocations can be recorded at deployment time.

   **Still outstanding:** The `netbox-community/terraform-provider-netbox` Terraform
   provider integration is not yet implemented. IP allocations, prefixes, and device
   records must still be entered manually in NetBox after each deployment. Automating this
   via the Terraform provider would remove the manual step and keep IPAM in sync with
   actual state automatically — a candidate improvement for Phase 07 or a standalone task.

2. **NPM (Nginx Proxy Manager) should be deployed early and updated per service as the
   project progresses.** NPM is the current front door for most internal services and
   is treated as an end-of-phase concern, but it should be deployed in the first wave
   alongside Portainer and NetBox on any new node. Proxy host entries for each service
   should be added as that service is deployed rather than in a batch at the end of a
   phase. This ensures each service is reachable by hostname immediately after deployment
   and that later services (Harbor, Authentik, Traefik) can be validated through the same
   access path that production will use.

3. **When allocating an IP address, verify availability with a ping in addition to checking
   IPAM.** NetBox records what was allocated but cannot detect addresses that are live on
   the network but never registered. Before assigning any IP, run `ping -c 3 <ip>` from a
   host on the same subnet; if the ping succeeds, the address is in use regardless of what
   IPAM shows. Allocate a different address and flag the conflict in NetBox for
   investigation. This applies to both manual and Terraform-driven allocations.

---

## Phase 00b — pve-test Management Bootstrap

1. Portainer runs in its own dedicated LXC container. Originally expected that basic
   management services might be co-located in a single "management" container, but the
   pattern here is one service per LXC throughout the project.

2. ~~The Portainer LXC was originally expected to sit on `vmbr0`~~ — **Resolved.**
   `portainer-stack/stack.yaml` uses `network: zone: mgmt_seg` at `10.57.1.20/24`.
   The chicken-and-egg concern (SDN zone must exist before Portainer, but Portainer
   bootstraps everything) does not apply: Phase 00a-02 applies the SDN VLAN zones to
   pve-test before Phase 00b deploys Portainer. LAN workstations reach Portainer via the
   MikroTik static route for `10.57.1.0/24 → 192.168.1.40` (pve-test). Portainer agents
   in `infra_seg`, `edge_seg`, and `build_seg` reach the server at `10.57.1.20` via
   standard MikroTik inter-VLAN routing — no extra static routes required beyond those
   already defined in `pve-test.yaml`. `mgmt_seg` now also uses the MikroTik as its
   DNS entry point at `10.57.1.1`; the router serves split DNS for
   `gibbsgreatly.xyz` on that interface and forwards public lookups via DoH.

3. NetBox now has a dedicated pve-test stack (`netbox-stack-test` / VMID 143) placed in
   `infra_seg` at `10.57.3.12`. It is deployed in Phase 03b alongside Harbor and apt-cacher.
   The production NetBox at `192.168.1.30` is no longer the reference for pve-test
   allocation checks. See task `docs/plan/tasks/03b-netbox-01-deploy-netbox.md`.

---

## Phase 01 — CI Runner Deployment

1. ~~**SonarCloud is not integrated into GitHub Actions.**~~ **Resolved.** A `sonarcloud`
   job has been added to `.github/workflows/security-scan.yml` using
   `SonarSource/sonarcloud-github-action@v3.1.0` (SHA-pinned). Checkout uses
   `fetch-depth: 0` for blame/new-issue detection. The branch name is passed dynamically
   via `-Dsonar.branch.name=${{ github.ref_name }}`; the hardcoded `sonar.branch.name=main`
   line has been removed from `sonar-project.properties`.

2. **Shell scripts have no CI lint coverage.** `scripts/`, `populate-bitwarden.sh`,
   `sync-secrets.sh`, and several scripts inside `terraform/lxc/` are not checked by any
   workflow. ShellCheck runs on `ubuntu-latest` with no secrets or self-hosted runner
   required — low cost, no infrastructure dependency.

   Recommended addition to `validate.yml`:
   ```
   find . -name '*.sh' -not -path './.git/*' | xargs shellcheck
   ```

3. ~~**Ansible lint only covers `terraform/lxc/ansible/playbooks/`.**~~ **Resolved.**
   A second lint step targeting `ansible/00-initial-setup/` and `ansible/01-base-system/`
   has been added to the `ansible-lint` job in `validate.yml`. The step runs from the
   `ansible/` directory so `ansible/ansible.cfg` is discovered automatically.

---

## Phase 02 — Memory Upgrade

<!-- Observations from the pve-test VM resize -->

---

## Phase 03b — Harbor Setup

1. Harbor runs in its own dedicated LXC container, consistent with the one-service-per-LXC
   pattern established by Portainer.

2. ~~The Harbor LXC connects directly to `vmbr0`~~ — **Resolved.** Harbor (`harbor-stack/
   stack.yaml`) now uses `network: zone: infra_seg`, placing it at `10.57.3.10/24` in
   VLAN 40. All SDN zones reach Harbor through MikroTik routing to `10.57.3.0/24` via
   the `all_zones → infra_seg` policy defined in `pve-test.yaml`. There is no
   LAN-to-SDN egress gap for registry pulls. apt-cacher is placed identically at
   `10.57.3.11/24` in `infra_seg`.

3. ~~**IP migration model for LAN-bridge stacks.**~~ **Historical — no longer applies.**
   Harbor uses distinct addresses on each node: `10.57.3.10` on pve-test (infra_seg) and
   `192.168.1.10` on pve (vmbr0). There is no IP conflict and no need for a cut-over
   sequence. The concern described here was specific to an earlier design where Harbor
   shared `192.168.1.10` across nodes on a flat LAN bridge; that design has been
   superseded by the SDN VLAN zone model.

---

## Phase 03 — Code Quality and Bug Fixes

<!-- Observations from shell script maintainability, NetBox integration refactoring, SSL acknowledgement -->

---

## Phase 03b (continued)

4. **Default Terraform workspace targets pve — sourcing `.env.pve-test` is mandatory before
   any Terraform operation on harbor-stack.** The default workspace state file
   (`terraform/lxc/stacks/harbor-stack/terraform.tfstate`) records `target_node: pve`.
   A `pve-test` workspace state exists in `terraform.tfstate.d/pve-test/`. Without
   sourcing `.env.pve-test` first, `TF_WORKSPACE` is unset, Terraform uses the default
   workspace, and any `plan` or `apply` targets pve's VMID 121. Because the
   `lxc-docker-host` module defaults both `onboot` and `start` to `true`, the Proxmox
   provider will start a stopped pve Harbor container to converge on desired state.

   This was the root cause of pve's Harbor being started during task 03b-03: that task's
   session prompt only sourced `.env` (not `.env.pve-test`), leaving the workspace in its
   default (pve-targeting) state. The fix is to add a mandatory `source .env.pve-test`
   step and a workspace safety check to every harbor-stack task session prompt, matching
   the pattern used in tasks 03b-01 and 03b-02.

5. **NPM on pve is currently the safest Harbor validation path for shared-host work.**
   While pve-test is the active rebuild target, `harbor.gibbsgreatly.xyz` can already be
   used through the existing NPM instance on pve as a temporary front door to Harbor at
   `192.168.1.10`. This is useful for validating robot logins and other registry-facing
   checks without touching the pve-test Harbor daemon/client trust configuration.

   The next development/testing round should bring up NPM early on pve-test as one of the
   first container stacks, so future Harbor and application validation can happen against
   the test environment directly instead of depending on the production NPM bridge.

6. **Harbor scan summaries lag behind image pulls and may need an explicit scan trigger.**
   After a `docker pull` through the proxy cache, `scan_overview` can stay `null` for a
   while even though the artifact is already cached. In practice, the cleanest validation
   path was to trigger the artifact scan endpoint explicitly and then poll the artifact
   list until the Trivy summary appeared. The repository path in the API call also needs
   double-encoding for nested image names such as `goauthentik%2Fserver`.

7. **Harbor’s GC schedule API on pve-test expects a 6-field cron string.**
   The task docs originally showed the 5-field cron `0 3 * * 0`, but the live API rejected
   it and accepted `0 0 3 * * 0` instead. In other words, this Harbor build wants seconds
   as the first field. That detail should be carried forward anywhere GC scheduling is
   documented or automated.
8. **Portainer agent and server versions must be kept in sync across all stacks.**
   The portainer-agent in harbor-stack was deployed at v2.40.0 while the Portainer server
   on pve-test was at v2.27.3, and pve's Portainer server was at v2.33.6. This caused two
   compounding problems:

   - **Protocol incompatibility**: agent v2.40.0 starts TLS from the first byte
     (`use_tls=true`). Portainer server v2.27.3 sends a plain-HTTP handshake first, so
     every connection attempt from pve-test's server fails with
     `client sent an HTTP request to an HTTPS server`. The endpoint shows as Status 2
     (down) in the UI despite the agent being fully running.
   - **Cross-instance pairing lock**: pve's Portainer (v2.33.6) can complete the TLS
     handshake with agent v2.40.0 and claims the agent. The agent then locks itself to
     that server and rejects any subsequent connection from pve-test's server as
     "already paired with another Portainer instance." Removing the endpoint from the
     pve Portainer UI does not send an unpair signal to the agent; the lock persists
     in the agent's in-memory state until the container is restarted.

   **Fix**: upgrade pve-test's Portainer server to `portainer-ce:latest` (matching or
   exceeding the agent version) *before* restarting the agent container. Restarting the
   agent clears the in-memory pairing state; the first server that successfully completes
   a TLS handshake re-claims it. If pve's older Portainer still has a registration for
   harbor-stack, it can re-claim the agent before pve-test does. Remove the harbor-stack
   endpoint from pve's Portainer first as a precaution.

   **Going forward**: pin agent and server to the same major/minor version tag in all
   `docker-compose.yml` files rather than using `latest` or mismatched explicit tags.
   The portainer stack on pve-test (`/opt/portainer/docker-compose.yml` in VMID 120) and
   the agent deployed with each stack should reference the same version string.
---

## Phase 03c — Artifact Proxy

<!-- Observations from apt-cacher-ng and Terraform provider mirror -->

---

## Phase 04 — Core Shared Services

<!-- Observations from Authentik, Headscale, step-ca, Traefik, Monitoring deployments -->

1. **SDN zone type changed from Simple to VLAN; MikroTik is now the L3 gateway.**
   The original design used Proxmox SDN Simple zones, where the Proxmox host itself
   held the gateway IPs and performed SNAT. This was replaced with VLAN zones, where
   the MikroTik owns all gateway IPs (10.57.0.1–10.57.3.1) and routes all inter-zone
   and internet-bound traffic. Proxmox is now a pure L2 switch.

   Consequences:
   - No static routes are needed on the MikroTik for inter-zone traffic — all VLAN
     subnets are directly connected.
   - `snat: false` on all SDN zones is mandatory. SNAT at Proxmox would double-NAT
     traffic (MikroTik also SNATs at WAN) and break LAN → container ingress.
   - MikroTik firewall is now the enforcement point for all cross-zone policy. The
     Proxmox VNet firewall controls inbound per-container rules only.
   - pve-test is a bare-metal laptop connected via a trunk port to the MikroTik. It
     is NOT a VM inside pve. All 16 GB RAM is available to pve-test containers.
    - The Terraform SDN provisioner (`configure-network-sdn-vnet.yml`) handles Simple
       zones only. VLAN zones are now applied by `ansible/00-initial-setup/proxmox-sdn-setup.yml`
       until the Terraform-side playbook is updated. This remains a known code gap.

2. **Harbor, apt-cacher-ng, and NetBox moved to a dedicated `infra_seg` zone.**
   Previously, Harbor and apt-cacher ran on `vmbr0` (flat LAN) at `192.168.1.10` and
   `192.168.1.35`. They are now placed in `infra_seg` (VLAN 40, `10.57.3.0/24`):
   - Harbor: `10.57.3.10`
   - apt-cacher-ng: `10.57.3.11`
   - NetBox: `10.57.3.12`

   All zones have a cross-zone allow rule to infra_seg (tcp/80,443,3142), so every
   container can reach Harbor and apt-cacher without vmbr0 bridging. The
   `all_zones → infra_seg` policy is documented in `pve-test.yaml`.

3. **Harbor bootstrap: first pass pulls from Docker Hub directly.**
   On a fresh pve-test pass, Harbor's own container images must be pulled from Docker
   Hub because Harbor is not yet running. Once Harbor is up, all subsequent containers
   in all zones pull from `10.57.3.10`. This chicken-and-egg dependency is expected and
   documented in the Phase 04 bring-up sequence in `docs/plan/README.md`. It is NOT a
   misconfiguration — Harbor pulls from Docker Hub on first pass, then becomes the
   registry for everything else.

4. **Let's Encrypt staging CA for all dev passes.**
   All Traefik deployments on pve-test use the LE staging CA
   (`https://acme-staging-v02.api.letsencrypt.org/directory`) to avoid burning the
   production rate limit during iterative development. The staging cert issuer shows
   `(STAGING) Let's Encrypt` in browsers — this is expected and correct for dev passes.
   Switch to the production CA only when promoting to `pve` (production).

5. **step-ca ACME challenge is httpChallenge, not tlsChallenge.**
   step-ca connects back to Traefik on port 80 to verify domain ownership. This requires
   an explicit MikroTik policy: `mgmt_seg → edge_seg tcp/80`. Using tlsChallenge would
   require step-ca to reach Traefik on port 443 with a valid cert — circular dependency
   during initial PKI bootstrapping. httpChallenge is simpler and avoids this.

6. **Authentik must be placed in the correct SDN network zone.** Authentik acts as the
   forward-auth provider for Traefik and as the SSO identity provider for internal apps.
   Its LXC must be reachable from both Traefik (in whatever zone the reverse proxy sits)
   and from the apps that delegate auth to it. Placing Authentik on `vmbr0` (flat LAN)
   avoids zone-routing complexity during initial setup, but conflicts with the goal of
   keeping the auth layer behind the SDN enforcement boundary. The intended placement is
   the `mgmt_seg` zone with explicit allow rules from the `public-edge` zone (Traefik)
   and any app zones that use forward-auth. Verify zone reachability before starting the
   Authentik deployment and confirm that Traefik can reach both the Authentik server and
   outpost endpoints before wiring up any protected routes.

7. **Headscale was dropped from Phase 04.** Remote access to the homelab is never needed
   — the lab is only managed from inside the home network. The only outgoing VPN in use
   is gluetun, which provides traffic privacy for specific containers and is not an admin
   access path. A self-hosted Tailscale control plane adds complexity with no benefit in
   this setup. If remote admin access is ever required in the future, options in ascending
   complexity are: router WireGuard peer, managed Tailscale free tier, then Headscale.

---

## Phase 05 — Supply Chain Security

1. **Shared Trivy service — worth revisiting before implementing task 05-01.** The current
   design runs three independent Trivy instances: an embedded adapter inside Harbor, a
   transient process in the GitHub-hosted `sast-scan` CI job, and a planned transient
   process in the self-hosted `trivy-image-scan` job. The preference is to reduce the
   number of independent service instances where practical.

   Trivy supports `trivy server` mode, which exposes an HTTP endpoint consumable by
   both Harbor (as a registered external scanner) and `aquasecurity/trivy-action` (via
   its `trivy-server` input). A shared service would mean a single DB download/cache and
   consistent scan results across all consumers.

   Arguments against as currently understood:
   - **Network reachability from GitHub-hosted runners**: the `sast-scan` filesystem scan
     runs on `ubuntu-latest` and cannot reach `192.168.1.x`. This is the structural
     blocker for fully consolidating CI scans — but its significance depends on where the
     Trivy service ends up in the SDN design. If ci-runner-01 handles all Trivy scans
     (self-hosted), the GitHub-hosted constraint disappears.
   - **Shared service as single point of failure**: if the Trivy service is down, both
     Harbor scans and CI are blocked. Acceptable risk at homelab scale if the service is
     on a reliable, always-on LXC.

   **Decision deferred to Phase 05.** Before implementing task 05-01, evaluate whether
   the `trivy-image-scan` job should run on the self-hosted runner (enabling server-mode
   consolidation) or GitHub-hosted. Document the chosen topology as a follow-on task if
   a shared service is adopted. Harbor's embedded Trivy can be replaced by registering an
   external scanner via `POST /api/v2.0/scanners` after setting
   `harbor_installer_with_trivy: false`.

2. **Chainloop has no Docker Compose self-hosting path — Helm on Kubernetes is the only
   supported option.** The phase-05 plan documented a Docker Compose deployment for the
   Chainloop server, but this does not exist upstream. The Chainloop repository's entire
   self-hosting surface is the `oci://ghcr.io/chainloop-dev/charts/chainloop` Helm chart.

   Two real images exist (`controlplane` and `artifact-cas`) but they require PostgreSQL,
   a Vault instance (or cloud secrets backend), an OIDC provider, and an ECDSA keypair —
   all wired together by Helm init jobs and hooks. There is no official compose bundle
   and no evaluated extraction of those manifests into compose form. Reverse-engineering
   a compose stack from `helm template` output is possible but produces an unsupported,
   unpatchable result that carries significant operational risk.

   The image reference used in the repo (`ghcr/chainloop-dev/chainloop:v1.58.0`) was a
   placeholder that does not exist in any registry — it is not a valid GHCR path.

   **Viable paths for Phase 05 task 05-04:**
   - **Chainloop Cloud free tier (recommended)**: register at `chainloop.dev`, obtain a
     `CHAINLOOP_TOKEN`, point the CLI at the SaaS control plane. No LXC or Kubernetes
     required. Meets all Phase 05 acceptance criteria (CLI on ci-runner-01, contract
     defined, gated CI job, token stored as Actions secret).
   - **K3s in LXC 155 + Helm dev mode**: install K3s inside the existing LXC, then
     `helm install chainloop oci://ghcr.io/chainloop-dev/charts/chainloop --set development=true`.
     Dev mode bundles PostgreSQL, Vault (in-memory), and Dex OIDC. LXC 155 at 2 cores /
     2 GB RAM is undersized; needs at minimum 4 GB to be viable.
   - **Defer**: keep LXC 155 paused; complete the rest of Phase 05 (Trivy, Syft, Cosign)
     and revisit Chainloop when a Kubernetes layer exists elsewhere in the lab.

---

## Phase 06 — Application Stack Migration

<!-- Observations from migrating arr stack, Jellyfin, Pi-hole, game services -->

---

## Tooling and Workflow

<!-- Observations about the AI-assisted workflow, Codex, Copilot, branching patterns, scan gates -->

1. `jq` should be treated as an early bootstrap dependency for `pve-test`. Several setup and validation steps use it for NetBox and Harbor API checks, so the pve-test Ansible bootstrap should install it alongside the other base tooling rather than relying on it being present later in the workflow.

---

## Patterns and Conventions

<!-- Observations about what stack patterns worked well, what was awkward, what to carry forward -->

1. **Preferred IP allocation sequence: IPAM check → ping verify → allocate.**
   See General observation 3 above. This sequence applies universally — Terraform modules,
   Ansible tasks, and manual deployments should all follow it before committing an address.

---

## Things to Revisit

<!-- Decisions made under time pressure that deserve a second look later -->
