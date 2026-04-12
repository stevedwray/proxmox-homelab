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

---

## Phase 03 — Code Quality and Bug Fixes

<!-- Observations from shell script maintainability, NetBox integration refactoring, SSL acknowledgement -->

---

## Phase 03b — Harbor Setup

<!-- Observations from Harbor configuration, Trivy, proxy caches, robot accounts -->

---

## Phase 03c — Artifact Proxy

<!-- Observations from apt-cacher-ng and Terraform provider mirror -->

---

## Phase 04 — Core Shared Services

<!-- Observations from Authentik, Headscale, step-ca, Traefik, Monitoring deployments -->

---

## Phase 05 — Supply Chain Security

<!-- Observations from Trivy CI integration, Syft, Cosign, Chainloop -->

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

