# nextcloud-stack

Status (2026-09-24): **Phase 1 is deployed and operational on `pve`.**
Nextcloud is private to the lab edge at
`https://nextcloud.lab.gibbsgreatly.xyz`; Pangolin publication remains a
separate, later Phase 3 decision. See "Current execution state" for the
verified deployment and the remaining follow-up work.

Goal: a self-hosted Nextcloud instance as a durable local storage point,
initially for documentation/reports produced by other lab projects (the
`deep-research` agent, CyberSecEval), later opened to the internet via
Pangolin with monitoring and a deliberately narrow blast radius — see
Phase 3 in [plan.md](plan.md).

## Current execution state (2026-09-24)

**`connector_seg` is now live on `pve`** — `nextcloud-P3-01` executed:
zone/vnet/subnet applied via `pvesh` under the production approval flow
(VLAN 110, `192.168.110.0/24`, `tvnewt`), verified with `pvesh get` and
`ip link show vmbr0.110`. Two real VLAN collisions were caught and
fixed along the way (both from checking the actual physical switch
config against what the plan assumed was free): `connector_seg` moved
off VLAN 100 (already `cse_seg` on `pve-tiny`) to 110, and `apps_seg`
(nextcloud's own zone, not yet built) moved off VLAN 90 (already
`test_dhcp_seg` on `pve-test-vm`, nested inside `pve`) to 120 — see
Decisions below for both.

**MikroTik enforcement is also live (2026-09-23).** Applied by the
operator directly on the router, verified read-only afterward via
`terraform/lxc/stacks/netbox-stack/integrations/mikrotik_client.py`:
VLAN 110 interface + bridge-vlan tagging (`ether1`,`ether5`, matching
every other zone), gateway `192.168.110.1`, 3 input rules (ping/DNS to
the router, placed before the input catch-all — the exact ordering bug
hit live in `media-stack-lab`'s Stage B), and forward rules scoped to
`192.168.110.0/24`: accept to `pangolin-proxy` (192.168.30.11:443),
the shared Graylog TCP syslog ingress (192.168.20.14:514), accept general
internet egress (covers both the Newt control connection and the Gerbil
WireGuard tunnel — protocol-unrestricted, modeled on `cse_seg`'s egress
rule), then default-deny. `connector_seg`
is now enforced end-to-end (Proxmox SDN + MikroTik), not just declared
in `pve.yaml`.

**`newt-connector` is also live (2026-09-23)** — `nextcloud-P3-02`
executed: base LXC (192.168.110.10, Docker only, no Newt credentials in
this repo's automation) deployed via `provision.sh`, smoke test stable
after fixing two real bugs (256MB OOM-killed `apt install`; bare `ssh`
in `smoke-test.sh` worked standalone but failed silently under
`provision.sh`'s subprocess environment — fixed with explicit
`-F`/`-i`/`-n`). **Newt itself is now connected
to the OCI Pangolin edge** — `lab` site recreated (original credentials
unrecoverable, Community Edition gates regeneration behind Enterprise),
tunnel confirmed up. Two more real bugs found and fixed on the OCI side
getting there — see `/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`
Historical Step 3.5 for the full account (a missing CA bundle in the `fosrl/newt`
image, and the real blocker: a stale Let's Encrypt *staging* cert that
`roles/pangolin/tasks/main.yml`'s ACME storage policy was silently
protecting from ever being corrected — now self-healing, not a one-off
manual fix).

**Wazuh is retired for the OCI edge (decision 2026-09-23).** The failed
path added a privileged endpoint agent, private resource, firewall
exception, and a relay sharing Gerbil's namespace, but could not provide
tamper-resistant evidence and briefly affected public-edge availability
during recovery. The `connector_seg -> wazuh-stack:1514` desired-state
rule has been removed. The OCI agent, relay, manager registration,
Pangolin resource/client, and MikroTik rule `*A3` are gone; the router
was re-queried read-only and has no matching TCP/1514 rule. The `lab`
Newt site and its credentials remain for future published services. OCI
monitoring
now prioritizes control-plane logs/alarms, public-port scans, external
HTTPS/TLS probes, and tested off-host recovery. The investigation is
retained as historical context in
`/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`.

**`apps_seg` and `nextcloud-stack` are live on `pve` (2026-09-24):** VLAN 120,
`192.168.120.0/24`, gateway `192.168.120.1`, and `tvapps` are applied on
Proxmox and the MikroTik. Its policy permits only the planned application
dependencies, shared TCP syslog, internet package/image egress, the Wazuh
agent manager ports, and an explicit deny for everything else.

`nextcloud-stack` is LXC `120010` at `192.168.120.10`: a 16G rootfs and 30G
Docker mount on `apps-containers`, with a 200G durable mount on
`storage-containers` at `/var/lib/nextcloud-persistent`. It runs Nextcloud
35.0.0, PostgreSQL 16 Alpine, Redis, and cAdvisor. `status.php` is healthy;
the Wazuh agent is enrolled; Docker uses the local rsyslog/syslog relay for
Graylog forwarding. The main Traefik and Technitium authority publish
`nextcloud.lab.gibbsgreatly.xyz` to `192.168.30.10` and proxy it to the LXC.
The separate `pangolin-proxy` remains scaffolded, not deployed.

**OIDC was verified live.** The `user_oidc` app is installed and enabled;
Authentik manages the strict callback
`https://nextcloud.lab.gibbsgreatly.xyz/apps/user_oidc/code` and the required
authorization-code grant. Nextcloud has `allow_local_remote_servers=true` so
its server-side OIDC client can resolve the internal Authentik endpoint. This
is a deliberate SSRF-hardening trade-off: restrict and review features that
can make arbitrary outbound requests, and rely on the apps-segment firewall
for network containment.

**But the OCI side of Phase 3 has real, live progress**, tracked in its
own repo's plan, `/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`
(that repo has no `.git` — not a commit history, just a live file):

- **OCI instance hardened**: NSG confirmed clean (80/443/UDP tunnel
  ports only); subnet security list stripped of 8 leftover rules from
  the box's prior life as a Minecraft server (Minecraft ports, an
  `"obsidian"` sync rule, a `"crawl4ai"` rule); SSH restricted to the
  operator's egress IP at both the OCI security-list layer and a new
  host-level `ufw` layer (`roles/os_hardening/` in the `oci` repo).
  Bastion was considered and explicitly rejected — IP restriction was
  judged sufficient, updated by hand if the operator's IP changes.
- **OCI Wazuh path retired:** a uniquely pre-registered `oci-pangolin`
  credential was safer than fleet-wide enrollment, but the resulting
  private route, agent, and Gerbil-netns relay had more security and
  availability cost than value for this one-purpose edge host. The
  agent, relay, manager registration, private resource/client, and
  router rule have been removed. The `lab` Newt site remains intact for
  future Pangolin-published services.
- **OCI monitoring priority:** VCN Flow Logs, OCI Audit/Cloud Guard,
  vulnerability/public-port scanning, external HTTPS/TLS checks, and
  off-host backups—not a home-lab Wazuh connection.

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md`.

See [plan.md](plan.md) for the full step-by-step plan.

## Decisions (resolved 2026-09-22, operator-confirmed)

- **App:** Nextcloud over ownCloud — richer WebDAV/OCS API and CLI (`occ`)
  for programmatic writes from other stacks, larger app ecosystem;
  ownCloud has been shedding features into its paid Infinite Scale
  rewrite.
- **Zone:** `apps_seg` SDN zone (VLAN 120, `192.168.120.0/24`), not
  reusing `infra_seg` or `media_seg` — keeps a future
  internet-exposed-via-Pangolin app isolated from core infra and media
  traffic, matching the existing per-purpose zone pattern
  (`media_seg`, `game_seg`, `pentest_seg`, `ai_seg`). Originally scoped
  for VLAN 90; changed 2026-09-23 after confirming on the physical
  switches that VLAN 90 is already live as `test_dhcp_seg`
  (`terraform/lxc/network/pve-test-vm.yaml`, labeled `dhcp_test` on the
  switch) — `pve-test-vm` is nested inside `pve` and shares its
  physical trunk, so it would have collided. Same class of gap as the
  `connector_seg`/VLAN 100 fix below; 120 is the next tag free across
  `terraform/lxc/network/*.yaml` as of 2026-09-23.
- **Database:** PostgreSQL — matches Authentik/NetBox/Wazuh, already
  operated on this platform; Nextcloud's own docs prefer it over MariaDB
  for new installs.
- **Storage:** rootfs and Docker storage use `platform-apps-zfs` (the
  ZFS-backed `apps-containers` pool); a 200G `durable-zfs` mount on
  `storage-containers` holds both user files and PostgreSQL data under
  separate directories. No NAS mount is part of the first deployment.
- **Auth:** Authentik OIDC (`user_oidc` app) wired from day one, via the
  same `edge-<stack>-<route>` reconciler pattern (`discover-authentik-edge.py`
  / `reconcile-authentik-edge.py`) already used for Harbor, Grafana,
  Portainer, Technitium, OpenWebUI, OpenSearch Dashboards, Wazuh
  Dashboard, Jellyfin, and Immich.
- **Ingestion (deep-research / CyberSecEval docs):** WebDAV push, keyed
  off the existing `reports/<project>/<run-id>/` storage convention
  (`docs/reporting-platform/CONVENTION.md`) rather than a bespoke path —
  see [plan.md](plan.md) Phase 2 for what that means concretely and what's
  still genuinely open (cross-node reach to CyberSecEval on `pve-tiny`).
- **Pangolin exposure (Phase 3, 2026-09-23):** not deprioritized after
  all — rolled into this plan. Anchored to a separate, already-existing
  repo, `/home/steve/git/oci`, which designs the OCI-hosted Pangolin edge
  and home-side Newt connector in real detail. The OCI instance hasn't
  changed since that design was written (operator-confirmed), so it's
  treated as current, not stale, and this plan adapts it rather than
  re-deriving it. Key constraint carried over: Newt gets a firewall rule
  only to a Traefik, **never** directly to `apps_seg` — a dedicated
  `connector_seg` VLAN and working OCI-side monitoring/logging are
  shared infrastructure, not nextcloud-specific one-offs.
- **LAN/Pangolin Traefik isolation (decided 2026-09-23): Option
  B — a second, dedicated Traefik instance (`pangolin-proxy`,
  192.168.30.11, `edge_seg`), not a second entrypoint on the existing
  shared Traefik.** `connector_seg`'s one firewall rule points only at
  `pangolin-proxy`; the main, LAN-facing Traefik (192.168.30.10) is
  unreachable from `connector_seg` entirely, by construction. Rejected
  the entrypoint-on-shared-instance option because its isolation is
  *policy* (the renderer must always assign entrypoints correctly as
  services get added) rather than *structural* (a second process simply
  has no router for anything not deliberately published to it). This
  generalizes beyond nextcloud-stack: any future Pangolin-published
  service (cse-panel, deep-research, others) rides the same
  `pangolin-proxy` instance and the same `connector_seg → pangolin-proxy`
  rule — no new VLAN or firewall rule per service, only a new opt-in
  entry in that service's own `edge.yaml`.
- **Authentik login for Pangolin-published routes:** `pangolin-proxy`
  needs its own copy of the shared `forwardAuth` middleware
  (`nextcloud-P3-03b`) — confirmed this works for free, no new firewall
  rule, because the middleware calls an internal-only hostname
  (`LAB_FQDN_AUTHENTIK_INTERNAL`) that resolves straight to Authentik,
  not through either Traefik, and `pangolin-proxy` sits in `edge_seg`
  alongside the main Traefik so it inherits the same existing
  `edge_seg → mgmt_seg:9443` rule. The real open item is OIDC-mode
  routes (not `forwardAuth`-mode ones like cse-panel/deep-research):
  `discover-authentik-edge.py` computes each route's expected
  `redirect_uris` from a single `host:` field, so a service published
  under two hostnames (LAN + `.pan.`) needs the reconciler taught to
  register both callback URLs against the same OAuth client — not yet
  built, see `nextcloud-P3-03c`.
- **Pangolin's own dashboard login is NOT Authentik-backed.** Checked
  the actual `oci` repo config (`group_vars/pangolin.yml`,
  `roles/pangolin/tasks/main.yml`) — no OIDC/SAML/IdP wiring exists for
  it. Every "Authentik" reference in that repo's docs is about
  *published applications'* own middleware, never about federating
  Pangolin's own login. Pangolin's dashboard uses its own native
  owner/user/MFA system, entirely separate from Authentik's centralized
  policies (session lifetime, group-based review, MFA enforcement).
  Since compromising the Pangolin dashboard means an attacker can
  define what gets published from the lab and to whom, it's arguably
  the single highest-value target in this whole design — treated as
  needing standalone hardening, not inherited from anything else here.
- **Security assessment (2026-09-23) of the Phase 3 design itself,
  updated after the Wazuh investigation:** Wazuh telemetry from OCI
  increased `connector_seg`'s blast radius (a second lateral target
  beyond `pangolin-proxy`) while a host agent could still be blinded by
  a compromised host. It is therefore retired in favor of OCI-native
  VCN Flow Logs/Audit/Cloud Guard, external checks, and recovery.
  `pangolin-proxy` (Option B) limits
  lateral *scope* from a compromised connector but does not eliminate
  Traefik-CVE exposure — two Traefik instances now need tracking on the
  same patch cadence, and the smaller, quieter one is the more likely to
  be forgotten. Full writeup: `nextcloud-P3-07` and
  `/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`.
- **OCI SSH access: IP-restriction, not Bastion (decided 2026-09-23).**
  OCI's native Bastion service was considered for `nextcloud-P3-01`-
  adjacent reasoning (session-based, no persistent open port) but
  rejected: Bastion sessions are ephemeral (TTL-bound), which would
  require new wrapper tooling around Ansible and
  `scripts/pangolin-backup.sh` (both assume a static, always-reachable
  SSH host) just to keep existing OCI workflows working. The operator's
  egress IP is effectively static for this purpose; updated by hand via
  the OCI CLI if it ever changes. Executed live — see
  `hardening-and-wazuh-plan.md` Phase 1.
- **Wazuh retirement (decided 2026-09-23):** revoke and remove the
  pre-registered `oci-pangolin` agent rather than trying to repair its
  private route. Keep the historical record for auditability, but do
  not create a replacement home-lab route to Wazuh **for OCI-originated
  traffic through the tunnel** — that transport shape is what was
  retired, not home-lab Wazuh coverage in general.
- **nextcloud-stack and newt-connector monitoring (added 2026-09-24):**
  the OCI retirement above is specific to the Pangolin/Gerbil tunnel
  path and does not extend to ordinary same-network hosts. Both
  `nextcloud-stack` (Phase 1, `apps_seg`) and `newt-connector` (Phase 3,
  `connector_seg`) join the existing 6-host home-lab Wazuh agent pilot
  (`authentik-stack`, `proxy-stack`, `harbor-stack`, `technitium-stack`,
  `apt-cacher-stack`, `pve` — see `docs/wazuh-stack/README.md`), each via
  a narrowly-scoped new `<zone> -> wazuh-stack:1514,1515` firewall rule
  (`nextcloud-01c`, `nextcloud-P3-02b`) and the shared `wazuh_agent` role
  (`nextcloud-02d`, `nextcloud-P3-02c`). `newt-connector` is a
  particularly high-value target for this — it's the only host holding
  the live credential-bearing tunnel to OCI. Container-level metrics
  (cadvisor, `nextcloud-02c`/`02f`) and Docker→Graylog log forwarding
  (`nextcloud-02d`) are also now part of nextcloud-stack's first deploy,
  matching the pattern already live on `authentik-stack`/`netbox-stack`/
  `media-stack-lab` rather than treating monitoring/logging as a later
  add-on. See `plan.md` for the literal steps.
- **nextcloud-stack is hand-authored, not scaffolded (decided
  2026-09-24).** `scaffold-stack.sh`'s generic five-file path was dropped
  in favor of directly authoring `stack.yaml`/`terragrunt.hcl`/
  `docker-compose.yml`/the deploy playbook (`nextcloud-02`–`02e`),
  matching the precedent `wazuh-stack`/`opensearch-stack`/
  `greenbone-stack` already set — this plan had grown five separate
  hand-written patch steps on top of a generated playbook (registry-host
  fix, monitoring, Graylog forwarding, Wazuh agent, OIDC bootstrap), at
  which point the generator was only producing a skeleton immediately
  rewritten by hand anyway.
- **`connector_seg` network placement (recap):** VLAN
  110, `192.168.110.0/24`, gateway `192.168.110.1`, single host
  `newt-connector` at `192.168.110.10`. Changed from the originally
  planned VLAN 100 on 2026-09-23 after confirming on the physical
  switches that VLAN 100 is already live as `cse_seg`
  (`terraform/lxc/network/pve-tiny.yaml`) — 110 is the next tag not
  already claimed by any zone across `terraform/lxc/network/*.yaml`
  (10/20/30/40/50/60/70/80/90/100 all in use). Its only application
  destination is `pangolin-proxy` (192.168.30.11, `edge_seg`) on 443;
  TCP syslog to Graylog (192.168.20.14:514) is separately allowed through
  the shared managed-zone sender policy —
  the `connector_seg → wazuh-stack:1514` rule that briefly existed
  alongside it has been removed (Wazuh retired, see "Current execution
  state" above). Everything else explicit-deny; internet egress stays
  open for the actual Gerbil/Newt tunnel. See `nextcloud-P3-01` for the
  literal `pve.yaml` content.

## Research this plan is based on

- Zone/firewall shape modeled on `media_seg`'s real block in
  `terraform/lxc/network/pve.yaml` (lines 124–141, 256–260, 513–569),
  including three real gaps `media_seg` only discovered live after
  deploy (rsyslog forwarding to Graylog, node_exporter TLS from step-ca,
  and OIDC token exchange actually routing via `edge_seg` through
  Traefik rather than direct to `mgmt_seg:9443`) — `apps_seg`'s policy
  block below bakes all three in from the start instead of rediscovering
  them.
- **`scaffold-stack.sh` was tried first, then dropped (2026-09-24)** in
  favor of hand-authoring `stack.yaml`/`terragrunt.hcl`/
  `docker-compose.yml`/the deploy playbook directly, matching
  `wazuh-stack`/`opensearch-stack`/`greenbone-stack`'s existing
  precedent — the generic scaffolder stopped earning its keep once five
  separate hand-written patch steps had piled up on top of its generated
  playbook anyway. See plan.md's `nextcloud-02` for the full reasoning.
- Authentik OIDC wiring modeled on `media-stack-lab`'s real
  `edge.yaml` and its two `OIDC_ROUTE_CLIENT_IDS`/`OIDC_ROUTE_CLIENT_SECRETS`
  entries in `terraform/lxc/discover-authentik-edge.py`.
- Durable-storage shape modeled on `harbor-stack/stack.yaml`'s
  `extra_mount_path`/`extra_mount_size`/`extra_mount_profile: durable-zfs`/
  `extra_mount` block.
- Compose shape (pinned image tags, Harbor pull-through
  `${REGISTRY_HOST}/dockerhub/...` prefix, password-via-env convention)
  modeled on `netbox-stack/docker-compose.yml`'s
  app+Postgres+Redis pattern — **but not its `REGISTRY_HOST` resolution**,
  which resolves to `LAB_IP_HARBOR` (the bare Harbor IP) and is a known,
  twice-confirmed-live bug (`docker login`/pull gets "connection refused"
  on 443 against the raw IP — Harbor's TLS only works via the FQDN
  through Traefik). `nextcloud-02`/`02d` resolve `LAB_FQDN_HARBOR`
  instead from the start, the same way `media-stack-lab`'s playbook
  does.
- **apt-cacher, monitoring, and security-scan integration researched
  directly against the real, running platform, not assumed from the
  media-stack-lab precedent alone:**
  - `apt_cacher_host` is a `stack.yaml` field consumed by the `lxc_base`
    role (`terraform/lxc/ansible/roles/lxc_base/tasks/main.yml`) to point
    `apt` at `apt-cacher-ng:3142` — every existing stack sets it;
    `nextcloud-02`'s `stack.yaml` includes it.
  - Harbor (443) and apt-cacher (3142) reachability from a new zone is
    already covered by an existing blanket rule (`from: all_zones, to:
    infra_seg, ports: [80, 443, 3142]`) — no bespoke firewall rule needed
    for either.
  - VictoriaMetrics scrape targets are a fully manual, hardcoded static
    list living inside `deploy-monitoring-stack.yml` itself (lines
    183–264 as of this plan's writing) — there is no NetBox-driven
    auto-discovery for metrics despite NetBox tracking the host.
    `nextcloud-02f` adds the new target and redeploys `monitoring-stack`.
  - GVM/Greenbone scan coverage of a new SDN zone is explicitly treated
    by `docs/greenbone-stack/network-scan-rollout-plan.md` as a
    deliberate widening action, not a routine add — `nextcloud-01b`
    follows that doc's own process rather than inventing a new one.
- Reports convention read from `docs/reporting-platform/CONVENTION.md`
  and `docs/reporting-platform/README.md` — **this is the same convention
  the current `feat/reporting-cyberseceval-phase2` branch's work belongs
  to.** `deep-research` (on `pve`, `ai-services-stack`, `ai_seg`) already
  writes `reports/deep-research/<run-id>/{report.md,manifest.json}`;
  CyberSecEval writes the equivalent on `cse-controller`/`cse-panel-stack`,
  which live on the separate `pve-tiny` node. `docs/reporting-platform/README.md`
  explicitly defers cross-node unification (its own Phase 3) as "real,
  deliberate follow-up work, not something to build speculatively" —
  this plan follows that same discipline: Phase 2 below only covers the
  same-node (`pve`) `deep-research` push, and does not invent a
  `pve`↔`pve-tiny` ingestion path ahead of that upstream work landing.

## Still genuinely open

- **Credential rotation.** The first bootstrap produced an over-verbose
  database exception log. Rotate `NEXTCLOUD_DB_PASSWORD` with a coordinated
  PostgreSQL, Compose, and SOPS update; do not treat this as a simple `.env`
  edit. The other first-deploy secrets are present in SOPS. `NEXTCLOUD_IMAGE_TAG`
  is non-secret and pinned in the operator's local `.env` to `35.0.0-apache`;
  review and deliberately update it during a future Nextcloud upgrade.
- **Monitoring validation.** The cAdvisor sidecar, Wazuh agent, and local
  Docker-to-rsyslog relay are deployed. Confirm the VictoriaMetrics/Grafana
  scrape and a real Graylog search before declaring metrics and log delivery
  end-to-end validated.
- **Deep-research → Nextcloud push implementation.** `nextcloud-P2-01`
  below identifies *where* this needs to hook in
  (`docs/reporting-platform/plan.md`'s Phase 1 adopter code path for
  `deep-research`) but the actual push code has not been written or
  scoped into a literal step yet — needs a follow-up research pass
  reading that code directly before it can become a real step block.
- **CyberSecEval → Nextcloud push**, cross-node from `pve-tiny`: out of
  scope for this plan entirely until `docs/reporting-platform/plan.md`
  Phase 3 (cross-node ingestion) lands upstream.
- **EdgeManifest Pangolin opt-in mechanism (Phase 3).** The Traefik
  isolation question itself is resolved (Option B, a second dedicated
  Traefik instance — see above), but `render-edge-traefik.py` still needs
  a second output target and a per-route opt-in field so a service's
  `edge.yaml` can publish to `pangolin-proxy` in addition to the main
  Traefik — it currently renders everything into one dynamic-config
  directory with no branching at all (confirmed by reading it). See
  `nextcloud-P3-03c` in plan.md; also carries the OIDC `redirect_uris`
  wrinkle (one route, two public hostnames, one OAuth client needing
  both callback URLs registered).
- **OCI-side monitoring/logging.** Fully designed in
  `pangolin-observability-and-graylog-plan.md` but not yet implemented
  end-to-end. The shared lab Graylog TCP/514 transport and authenticated
  API were verified on 2026-09-24; OCI-native signals, external probes,
  and recovery validation remain prerequisites for Phase 3 publishing.
- **nextcloud-stack telemetry is deployed; Newt telemetry remains open.**
  `nextcloud-stack` has its Wazuh agent, cAdvisor, Docker-to-rsyslog relay,
  and the `apps_seg -> wazuh-stack:1514,1515` policy/MikroTik mirror.
  `newt-connector` remains a separate follow-up because its
  operator-managed Compose path must be confirmed before FIM can be scoped
  safely; do not add broad watches such as `/root`.
- **Greenbone scan reach (`nextcloud-01b`) not yet applied.** Confirmed
  live 2026-09-24: `apps_seg` has no `greenbone-stack`-sourced discovery
  rule in `pve.yaml`, and `192.168.120.10` isn't registered as a GVM scan
  target. This step was deliberately deferred until the host was real and
  reachable (per its own note in plan.md) — that precondition is now met,
  so this is actionable, just not yet done.
- **Monitoring-stack scrape target (`nextcloud-02f`) confirmed not
  applied live 2026-09-24** — `deploy-monitoring-stack.yml` has no
  `nextcloud` reference yet, matching the "Monitoring validation" item
  above; listed here explicitly so it doesn't get missed as a discrete
  redeploy step.
- **9 Critical CVEs found by Wazuh on nextcloud-stack (2026-09-24),
  triaged.** All base-OS packages (openssl x3, perl x3, glibc,
  libssh2, gnutls), none application-layer. Root cause: nextcloud-stack
  was never enrolled in the unattended-upgrades pilot — fixed by
  `nextcloud-02g` (not yet applied). **That step alone does not close
  all 9** — confirmed live that glibc's and perl's fixes ship only via
  Debian's `trixie/main` point-release pocket, not the
  `trixie-security` pocket unattended-upgrades watches by deliberate
  design (`roles/unattended_upgrades/templates/50unattended-upgrades.j2`'s
  own comment: non-security updates are applied deliberately, not
  silently overnight). **This is fleet-wide, not nextcloud-specific**:
  spot-checked live, all 5 other pilot hosts (`authentik-stack`,
  `proxy-stack`, `apt-cacher-stack`, `technitium-stack`, `wazuh-stack`)
  are still on the same unpatched glibc despite unattended-upgrades
  running successfully on all of them daily. Closing the glibc/perl
  CVEs anywhere requires either an explicit manual `apt upgrade` per
  host or a separate, deliberate decision to widen
  `Origins-Pattern` fleet-wide — not decided here.
