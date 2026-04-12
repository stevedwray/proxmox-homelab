# Project Observations

Running notes and observations collected during the greenfield rebuild. Not actionable —
these are reflections for future reference when revisiting decisions, patterns, or problems.

---

## General

<!-- Add observations that apply across phases here -->

1. **NetBox should be set up earlier and kept current with a Terraform provider integration.**
   NetBox is currently hosted on `pve` and is referenced during Phase 04 for IPAM checks,
   but it is not deployed as a tracked stack on `pve-test` until later in the phase order.
   This creates a gap where early phases must query production NetBox or skip IPAM
   validation entirely. NetBox should be one of the first stacks brought up on any new
   node — before CI runners, Harbor, or application stacks — so that IP allocations and
   DNS records are recorded from the start.

   Additionally, the `netbox-community/terraform-provider-netbox` Terraform provider
   enables IaC-managed IPAM: IP addresses, prefixes, and device records can be
   created/updated as part of the same Terraform run that creates an LXC. This removes
   the manual step of updating NetBox after each deployment and keeps IPAM in sync with
   actual state automatically.

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

2. The Portainer LXC connects directly to `vmbr0` (the physical LAN bridge) rather than
   being placed in any SDN-managed zone. It sits outside the segmented network topology
   created by the project's SDN code — it is a flat LAN citizen, not an SDN tenant.

   This is a pragmatic trade-off rather than a deliberate architectural decision. Portainer
   *could* live in an SDN zone (e.g. `mgmt_seg`) — the existing egress routing automation
   used for `build_seg` would handle LAN reachability. The two complications that drive the
   flat placement:
   - Portainer agents in other zones need a routed path back to the server. Achievable with
     the existing SDN automation, but requires additional routing rules.
   - Bootstrap ordering: the SDN zone must exist before Portainer can be deployed, but
     Portainer is what bootstraps everything else. This chicken-and-egg dependency needs
     careful resolution.

   The consequence is that the management plane (Portainer, NetBox, Harbor) is reachable
   from anything on `192.168.1.0/24` with no SDN policy enforcement in front of it —
   SDN isolation applies to application workloads but not to the management plane itself.
   Stricter access control for Portainer would need to come from Traefik + Authentik
   forward-auth (Phase 04), not from network segmentation.

3. NetBox is hosted on `pve`, not `pve-test`. Any IPAM or allocation checks for Phase 04
   must query the production NetBox instance at `192.168.1.30` even when the deploy target
   is `pve-test`. Assuming NetBox is available locally on `pve-test` will cause false
   failures during validation and can make an otherwise healthy setup look blocked.

---

## Phase 01 — CI Runner Deployment

1. **SonarCloud is not integrated into GitHub Actions.** `sonar-scanner` is documented as
   a manual pre-merge step (CLAUDE.md) but is not invoked in any workflow. The project is
   already configured (`sonar-project.properties` present, SonarCloud project exists) — the
   only missing piece is a `sonar-scanner` job in `security-scan.yml` and a `SONAR_TOKEN`
   Actions secret. Without CI integration, SonarCloud analysis only runs when explicitly
   remembered, and PRs have no automatic quality gate.

   Recommended addition to `security-scan.yml`:
   - Use `SonarSource/sonarcloud-github-action`
   - Pass `fetch-depth: 0` on checkout (required for blame/new-issue detection)
   - Replace the hardcoded `sonar.branch.name=main` in `sonar-project.properties` with
     `-Dsonar.branch.name=${{ github.ref_name }}` as a runtime arg

2. **Shell scripts have no CI lint coverage.** `scripts/`, `populate-bitwarden.sh`,
   `sync-secrets.sh`, and several scripts inside `terraform/lxc/` are not checked by any
   workflow. ShellCheck runs on `ubuntu-latest` with no secrets or self-hosted runner
   required — low cost, no infrastructure dependency.

   Recommended addition to `validate.yml`:
   ```
   find . -name '*.sh' -not -path './.git/*' | xargs shellcheck
   ```

3. **Ansible lint only covers `terraform/lxc/ansible/playbooks/`.** The playbooks under
   `ansible/` (initial setup, storage configuration, Proxmox host setup) are not linted in
   CI. These are higher-risk than the stack playbooks — mistakes there affect physical hosts,
   not containers. A second lint step targeting `ansible/` with `ansible/ansible.cfg` as the
   config file would close this gap.

---

## Phase 02 — Memory Upgrade

<!-- Observations from the pve-test VM resize -->

---

## Phase 03b — Harbor Setup

1. Harbor runs in its own dedicated LXC container, consistent with the one-service-per-LXC
   pattern established by Portainer.

2. The Harbor LXC connects directly to `vmbr0` (the flat LAN bridge) — no `network:` block
   in `stack.yaml`, so it inherits the default bridge. This is the same placement as
   Portainer and carries the same trade-off: it is reachable from anything on
   `192.168.1.0/24` with no SDN policy enforcement in front of it.

   The consequence is wider here than for Portainer. Every other LXC that pulls images
   from Harbor (`192.168.1.10`) must have a routed path to the LAN. LXCs on `vmbr0`
   (infra/apps zones) have this by default; LXCs in SDN zones (`build_seg`, `apps_seg`,
   etc.) need either SNAT enabled or explicit cross-zone routing. This is a known gap in
   the current network intent model — the policies in `pve-test.yaml` cover intra-VNet
   FORWARD rules, but not LAN-to-SDN egress routing for registry pulls.

   A future improvement would be to place Harbor in a dedicated `registry_seg` SDN zone
   with explicit inbound policies from all consumer zones, or to enable SNAT on each SDN
   subnet so containers can reach the LAN-addressed Harbor without per-zone routing rules.

3. **IP migration model for LAN-bridge stacks.** The greenfield design assigns the same
   canonical `192.168.1.10` to Harbor on both nodes. Because both nodes share `vmbr0`,
   only one can hold that IP at a time. Deploying Harbor to pve-test therefore requires
   stopping the pve instance first (`pct stop 121` on pve). The override variable
   `TF_VAR_stack_ip_address` exists in `terraform/lxc/variables.tf` and can be used via
   `coalesce()` in `main.tf` if parallel operation at a temporary IP is ever needed — but
   the primary migration path is a clean cut-over. This pattern applies to any future
   LAN-bridge stack that already runs on pve at a canonical IP.

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

1. **Authentik must be placed in the correct SDN network zone.** Authentik acts as the
   forward-auth provider for Traefik and as the SSO identity provider for internal apps.
   Its LXC must be reachable from both Traefik (in whatever zone the reverse proxy sits)
   and from the apps that delegate auth to it. Placing Authentik on `vmbr0` (flat LAN)
   avoids zone-routing complexity during initial setup, but conflicts with the goal of
   keeping the auth layer behind the SDN enforcement boundary. The intended placement is
   the `mgmt_seg` zone with explicit allow rules from the `public-edge` zone (Traefik)
   and any app zones that use forward-auth. Verify zone reachability before starting the
   Authentik deployment and confirm that Traefik can reach both the Authentik server and
   outpost endpoints before wiring up any protected routes.

2. **Headscale was dropped from Phase 04.** Remote access to the homelab is never needed
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
