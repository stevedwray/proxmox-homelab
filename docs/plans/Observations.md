# Project Observations

Running notes and observations collected during the greenfield rebuild. Not actionable —
these are reflections for future reference when revisiting decisions, patterns, or problems.

---

## General

<!-- Add observations that apply across phases here -->

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

---

## Phase 03c — Artifact Proxy

<!-- Observations from apt-cacher-ng and Terraform provider mirror -->

---

## Phase 04 — Core Shared Services

<!-- Observations from Authentik, Headscale, step-ca, Traefik, Monitoring deployments -->

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

---

## Phase 06 — Application Stack Migration

<!-- Observations from migrating arr stack, Jellyfin, Pi-hole, game services -->

---

## Tooling and Workflow

<!-- Observations about the AI-assisted workflow, Codex, Copilot, branching patterns, scan gates -->

---

## Patterns and Conventions

<!-- Observations about what stack patterns worked well, what was awkward, what to carry forward -->

---

## Things to Revisit

<!-- Decisions made under time pressure that deserve a second look later -->
