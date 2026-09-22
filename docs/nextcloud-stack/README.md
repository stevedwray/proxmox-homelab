# nextcloud-stack

Status (2026-09-23): **Phase 1 (the nextcloud-stack itself) still not
started — still not a priority, still just planned.** But Phase 3
(Pangolin exposure/monitoring/security) has real, executed groundwork
now, entirely on the OCI side — see "Current execution state" below
before assuming anything here is still purely theoretical.

Goal: a self-hosted Nextcloud instance as a durable local storage point,
initially for documentation/reports produced by other lab projects (the
`deep-research` agent, CyberSecEval), later opened to the internet via
Pangolin with monitoring and a deliberately narrow blast radius — see
Phase 3 in [plan.md](plan.md).

## Current execution state (2026-09-23)

**Nothing in `proxmox-homelab` itself has been executed yet** — no
`apps_seg` zone, no `nextcloud-stack`, no `connector_seg`, no
`pangolin-proxy`. Phase 1/2/3 here are all still just plan.md content.

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
- **Wazuh agent installed on the OCI host**, enrolled with its **own
  unique credential** (manager-side pre-registration, agent ID `007`
  `oci-pangolin` on `wazuh-stack`/`pve` — never the shared
  `WAZUH_AGENT_AUTHD_PASSWORD` every other agent uses, so a compromise
  of this internet-facing host can't touch the rest of the fleet's
  enrollment trust). Service is `active` and running local modules
  (SCA, syscollector), but shows `Never connected` on the manager —
  **expected**, not broken: it's blocked on the same missing
  infrastructure as the rest of Phase 3 below.
- **What's actually blocking further progress on both sides**: the
  `connector_seg` zone, the `newt-connector` host, and the
  `pangolin-proxy` Traefik instance described in `plan.md` Phase 3 have
  not been created in `proxmox-homelab` yet. Nothing routes OCI to the
  home network privately. Wazuh going `Active` and the OCI-side
  monitoring/logging phases both wait on this landing first.

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md`.

See [plan.md](plan.md) for the full step-by-step plan.

## Decisions (resolved 2026-09-22, operator-confirmed)

- **App:** Nextcloud over ownCloud — richer WebDAV/OCS API and CLI (`occ`)
  for programmatic writes from other stacks, larger app ecosystem;
  ownCloud has been shedding features into its paid Infinite Scale
  rewrite.
- **Zone:** new `apps_seg` SDN zone (VLAN 90, `192.168.90.0/24`), not
  reusing `infra_seg` or `media_seg` — keeps a future
  internet-exposed-via-Pangolin app isolated from core infra and media
  traffic, matching the existing per-purpose zone pattern
  (`media_seg`, `game_seg`, `pentest_seg`, `ai_seg`).
- **Database:** PostgreSQL — matches Authentik/NetBox/Wazuh, already
  operated on this platform; Nextcloud's own docs prefer it over MariaDB
  for new installs.
- **Storage:** actual Nextcloud data directory on a dedicated
  `extra_mount_profile: durable-zfs` volume (same pattern as
  `harbor-stack`/`wazuh-stack`/`opensearch-stack`), not crammed into the
  container's own rootfs/docker-storage.
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
  before building it:** adding Wazuh telemetry from OCI *increases*
  `connector_seg`'s blast radius (a second lateral target beyond
  `pangolin-proxy`), and a host-based agent can be blinded by whoever
  compromises the host it's watching — mitigated by (a) a Wazuh
  enrollment credential unique to the OCI host, never the fleet-shared
  one, and (b) OCI-native VCN Flow Logs/Audit logs as a control-plane
  signal the guest OS can't suppress. `pangolin-proxy` (Option B) limits
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
- **Wazuh agent for the OCI host: unique enrollment credential, not the
  shared fleet password (decided and executed 2026-09-23).** Manager-
  side pre-registration on `wazuh-stack`/`pve` (agent ID `007`,
  `oci-pangolin`), key delivered to the OCI host entirely out of band —
  never through an automated pipeline (Claude Code's own safety
  classifier correctly refused to script the key extraction). See
  `hardening-and-wazuh-plan.md` Phase 3 for the full sequence, including
  a real gap hit live (the `wazuh` group didn't exist until the agent
  package was installed) and how it was fixed without ever exposing the
  key to an intermediate file.
- **`connector_seg` network placement (recap, not yet built):** VLAN
  100, `192.168.100.0/24`, gateway `192.168.100.1`, single host
  `newt-connector` at `192.168.100.10`. Exactly two permitted
  destinations: `pangolin-proxy` (192.168.30.11, `edge_seg`) on 443, and
  — once the private Pangolin resource for it exists —
  `wazuh-stack` (192.168.40.15, `infra_seg`) on 1514 only, never 1515.
  Everything else explicit-deny; internet egress stays open for the
  actual Gerbil/Newt tunnel. See `nextcloud-P3-01` for the literal
  `pve.yaml` content.

## Research this plan is based on

- Zone/firewall shape modeled on `media_seg`'s real block in
  `terraform/lxc/network/pve.yaml` (lines 124–141, 256–260, 513–569),
  including three real gaps `media_seg` only discovered live after
  deploy (rsyslog forwarding to Graylog, node_exporter TLS from step-ca,
  and OIDC token exchange actually routing via `edge_seg` through
  Traefik rather than direct to `mgmt_seg:9443`) — `apps_seg`'s policy
  block below bakes all three in from the start instead of rediscovering
  them.
- New-stack scaffolding via `terraform/lxc/scaffold-stack.sh`, driven by
  a `stack-request.yaml` (`terraform/lxc/stacks/stack-request.example.yaml`,
  the `minecraft-stack` exemplar) — reused here rather than hand-writing
  `stack.yaml`/`terragrunt.hcl`/the Ansible playbook from scratch.
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
  through Traefik). `nextcloud-02b` fixes this by resolving
  `LAB_FQDN_HARBOR` instead, the same way `media-stack-lab`'s playbook
  does.
- **apt-cacher, monitoring, and security-scan integration researched
  directly against the real, running platform, not assumed from the
  media-stack-lab precedent alone:**
  - `apt_cacher_host` is a `stack.yaml` field consumed by the `lxc_base`
    role (`terraform/lxc/ansible/roles/lxc_base/tasks/main.yml`) to point
    `apt` at `apt-cacher-ng:3142` — every existing stack sets it;
    `nextcloud-02`'s `stack-request.yaml` now includes it.
  - Harbor (443) and apt-cacher (3142) reachability from a new zone is
    already covered by an existing blanket rule (`from: all_zones, to:
    infra_seg, ports: [80, 443, 3142]`) — no bespoke firewall rule needed
    for either.
  - VictoriaMetrics scrape targets are a fully manual, hardcoded static
    list living inside `deploy-monitoring-stack.yml` itself (lines
    183–264 as of this plan's writing) — there is no NetBox-driven
    auto-discovery for metrics despite NetBox tracking the host.
    `nextcloud-02c` adds the new target and redeploys `monitoring-stack`.
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

- **Nextcloud image tag.** Deliberately not pinned in this doc — check
  the current stable tag at `hub.docker.com/_/nextcloud` (or
  `hub.docker.com/r/nextcloud/server`) at execution time and pin it
  literally into the step that authors `stack-request.yaml`, rather than
  baking in a version that may already be stale by the time this plan is
  run.
- **`user_oidc` provisioning mechanism.** Nextcloud has no compose-level
  env-var equivalent to Immich's `IMMICH_CONFIG_FILE`; OIDC provider
  registration is normally done via `occ user_oidc:provider` after the
  app itself is installed via `occ app:install user_oidc`. `nextcloud-04`
  below writes this as literal `docker exec ... occ ...` post-tasks in
  the generated Ansible playbook, but it has **not been validated live**
  — confirm the exact `occ user_oidc:provider` flag set against whatever
  Nextcloud major version gets pinned before treating that step as
  gate-clean.
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
- **Connector VLAN placement.** `pangolin-observability-and-graylog-plan.md`
  itself lists "connector VLAN ID/subnet versus locked-down `mgmt_seg`
  LXC" as an open decision. This plan takes the dedicated-VLAN option
  (`connector_seg`, VLAN 100) as the target since both OCI-repo docs
  prefer it, but that choice hasn't been re-confirmed with the operator
  independent of this plan's own read of those docs.
- **OCI-side monitoring/logging.** Fully designed in
  `pangolin-observability-and-graylog-plan.md` but, by that document's
  own admission, not yet implemented — its Phase 0 (verify the live
  Graylog input/TLS/port contract) hasn't run. This plan treats that as
  a prerequisite for Phase 3's Pangolin publish, not something to skip.
