# nextcloud-stack

Status: **planning, not started.** Not a priority — scoped ahead of time so
it's ready to execute whenever it becomes one.

Goal: a self-hosted Nextcloud instance as a durable local storage point,
initially for documentation/reports produced by other lab projects (the
`deep-research` agent, CyberSecEval), later opened to the internet via
Pangolin (separate, lower-priority effort, not addressed by this plan).

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
- **Pangolin exposure.** Not addressed here at all — explicitly
  deprioritized by the operator; revisit as its own plan once this
  stack is live internally.
