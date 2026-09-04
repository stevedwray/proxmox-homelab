# media-stack-lab (planning workspace)

Status: **all 8 plan steps done.** Stages A/B/C (Terraform, MikroTik,
`provision.sh`), the edge/OIDC hookup, the Jellyfin SSO plugin
(automated, not manual UI after all), legacy's config/users/watch
history, and Immich's NAS-photos external library are all done -- see
Deployment status below. `steve`'s SSO login is confirmed to have
landed on the migrated account (operator-verified 2026-09-04). Only
the same watch-history eyeball check for Glyn (`media-lab-07`) remains,
needing the operator. **Not yet merged to `stable` or `main`** -- still
on `task/media-stack-v2-plan-refresh`, no PR opened yet. One
combined stack --
Jellyfin + Immich together in a single new LXC --
standing up **alongside** legacy `media-stack`, not replacing it
destructively. Existing Jellyfin users/watch-history get brought across
so the new stack is a real alternative, but legacy stays running;
retiring it is a separate, future, operator-initiated decision this
plan does not assume or schedule.

Supersedes `docs/immich-stack/` -- see that workspace's README for why.

## Platform integration: Graylog, Grafana, NetBox, Portainer (2026-09-04)

Operator noticed media-stack-lab was missing from Portainer, Grafana,
and NetBox, and asked to check Graylog specifically. Findings and
fixes, in the order found:

- **Portainer: not a gap.** `portainer_agent: false` in `stack.yaml` is
  correct and matches the majority of current real production stacks
  (netbox-stack, harbor-stack, authentik-stack, proxy-stack,
  monitoring-stack, opensearch-stack, wazuh-stack). `true` is now
  mostly the older single-container stacks.
- **Graylog: real bug, chased through 3 layers before actually fixed.**
  1. `deploy-media-stack-lab.yml` never wrote `/etc/docker/daemon.json`
     with the syslog log-driver every other stack's playbook has --
     Docker used its default `json-file` driver, nothing left the
     container. Fixed, and while fixing it, cadvisor's image pull
     through the bare Harbor IP failed with `connection refused` on
     443 -- confirmed live Harbor's own container IP only serves HTTP,
     never HTTPS, so `insecure-registries` against it can get an HTTP
     manifest response but then fails the token-auth redirect. Fixed
     by using `LAB_FQDN_HARBOR` (via Traefik) instead, per the existing
     documented pattern in `docs/harbor-stack/image-sourcing-enforcement.md`
     and matching `deploy-minecraft-wildworks.yml`/`deploy-greenbone-stack.yml`.
  2. Restarting the Docker daemon doesn't retroactively change already
     -running containers' log driver (it's fixed at container-create
     time) -- had to `docker compose up -d --force-recreate` to get
     jellyfin/immich/redis/database onto the new driver too; cadvisor
     picked it up for free since it was newly created.
  3. **Even then, nothing arrived.** `media_seg` had no firewall rule
     to Graylog at all (`192.168.20.14:514`) -- every other zone with
     syslog forwarding (`game_seg`, `pentest_seg`) has one, media_seg
     never got one when the zone was created. Added live via the
     RouterOS API (place-before the deny rule, same pattern as the
     earlier Authentik-callback fix), then restarted rsyslog to force
     an immediate reconnect instead of waiting out its retry backoff.
     Verified end-to-end via Graylog's search API: host syslog and
     Docker container logs (jellyfin, immich-server, cadvisor) all
     confirmed flowing.
- **Grafana: two gaps, same investigation.** VictoriaMetrics' scrape
  config (`deploy-monitoring-stack.yml`) is a hardcoded static target
  list, no auto-discovery -- media-stack-lab was simply never added.
  Added `node_exporter`/`cadvisor` target blocks matching the
  established per-stack pattern. Redeploying surfaced a second real
  gap: `node_exporter` came up serving plain HTTP instead of HTTPS --
  its role silently skips step-ca TLS cert issuance (`wait_for` +
  `ignore_errors`) when step-ca is unreachable, and `media_seg` had no
  firewall rule to step-ca (`192.168.20.11:443`) either, same class of
  gap as the Graylog one. Added that rule too, re-ran provision, cert
  issued, VictoriaMetrics now shows both `node_exporter` and `cadvisor`
  targets `health: up`.
- **NetBox: discovery already works** (`discover.py` globs
  `stacks/*/stack.yaml`, no hardcoding) but the containerized `apply`
  path (`scripts/run-netbox-populate-container.sh`) had two real,
  pre-existing bugs, unrelated to media-stack-lab specifically: its
  env-passing regex silently dropped every *prefixed* env var
  (`LAB_IP_NETBOX`, `NETBOX_API_TOKEN`, ...), and it never mounted the
  network-intent YAML the container needs (`populate.py` derives that
  path from its own script location, which only resolves inside a
  real git checkout -- never true in this container). Both fixed.
  media-stack-lab is now a real NetBox VM record (id 39, correct
  `primary_ip4`). One unrelated pre-existing NetBox data conflict
  found along the way (`gaming-stack`'s primary-IP reassignment,
  IP id 30) -- not caused by this work, not fixed, flagged for a
  separate pass.
- The 2 additive MikroTik rules from this pass (Graylog, step-ca) are
  now mirrored into `terraform/lxc/network/pve.yaml`'s `policies:`
  section, not just applied live -- see that file for the exact rules
  and rationale. (The Harbor/internet-egress rules from the original
  Stage B pass remain live-only, not yet mirrored back -- a
  pre-existing gap true of every zone's Harbor/egress rules, not
  unique to media_seg, not addressed in this pass.)

## Deployment status (real infrastructure, beyond the 8 plan steps below)

- **Stage A -- `terragrunt apply` for `media-stack-lab`: DONE 2026-09-04.**
  `./with-secrets-prod terragrunt apply --working-dir
  terraform/lxc/stacks/media-stack-lab`. `Apply complete! Resources: 5
  added, 0 changed, 0 destroyed` -- LXC container (VMID `80010`,
  `media-stack-lab`, confirmed `running` live via the Proxmox API), the
  `tvmedia` SDN zone/vnet/subnet (confirmed live in
  `/cluster/sdn/zones`, alongside all 7 other zones), and the Ansible
  inventory. No Docker services deployed yet -- the container exists,
  Docker/compose deployment is Stage C.
- **Stage B -- MikroTik router config: DONE 2026-09-04, verified live.**
  Checked the real current router state read-only via
  `terraform/lxc/stacks/netbox-stack/integrations/mikrotik_client.py`
  (the existing RouterOS REST API discovery client) rather than assume:
  no `vlan80-media` interface exists yet (10 VLANs live, 80 not among
  them), `bridgeLocal` has `vlan-filtering: true` so a matching
  `/interface bridge vlan` entry is required too, not just
  `/interface vlan` -- every existing VLAN has one
  (`tagged=bridgeLocal,ether1,ether5`). Firewall-rule inspection also
  found **2 rules beyond what `pve.yaml`'s `policies:` ever documented,
  needed for this stack to actually provision and pull images**:
  `media_seg -> infra_seg` (Harbor/apt-cacher, ports 80/443/3142) and
  `media_seg` internet egress (80/443, since this stack's images come
  from `ghcr.io`/`docker.io`/`lscr.io` directly, not through Harbor) --
  matching the pattern every other zone (`game_seg`, `pentest_seg`,
  `ai_seg`, `research_seg`) already has on the router, just never
  mirrored back into the YAML (true of those zones too, not a gap
  unique to this one). Full exact RouterOS command set (8 rules +
  interface/bridge-vlan/IP setup) handed to the operator in chat
  2026-09-04, applied by the operator on the router. **One real gap hit
  live**: the router-level config alone wasn't enough -- a physical
  switch between the router and the Proxmox host also needed VLAN 80
  added to its own trunk. Found via the router's ARP table showing
  `192.168.80.10` stuck at `status: failed` (no L2 path) even though
  every router-side object (VLAN interface, bridge-vlan entry, firewall
  rules, gateway IP) was confirmed correct; operator added VLAN 80 on
  the switch, then ARP flipped to `complete: true, status: reachable`
  and ping succeeded (4/4, MAC matches the container's real `hwaddr`
  exactly). Fully verified end-to-end, not just router-config-exists.
- **Stage C -- `provision.sh --stack media-stack-lab`: DONE 2026-09-04,
  verified live.** All 5 compose services up and healthy: `database`,
  `redis`, `immich-machine-learning`, `jellyfin` (port 8096),
  `immich-server` (port 2283, `Nest application successfully started`,
  no crash loop). NFS mounts (`mp1` raw `/mnt/nas-media` for Jellyfin,
  `mp2` bindfs-remapped `immich-photos` for Immich) confirmed real and
  correctly owned. This took several real, live-found bugs to get
  clean -- none caught by any gate in this plan, all found by actually
  reading container/router state during the deploy attempts:
  1. **MikroTik `input` chain ordering**: the 3 media_seg input rules
     from `media-lab-00` were appended *after* an existing global
     `Drop all other unhandled input traffic` catch-all -- completely
     dead on arrival. Confirmed via rule packet counters (0 hits) before
     the fix, and by watching the DNS-UDP rule immediately start
     counting hits after moving them before the catch-all. This blocked
     the container from resolving DNS via its own gateway at all,
     triggering `lxc_base`'s public-DNS fallback, which my forward-chain
     egress rule (80/443 only) then also blocked -- total DNS dead-end.
     Fixed with `/ip firewall filter move ... destination=[find where
     comment="Drop all other unhandled input traffic"]`.
  2. **`immich-server` was never given its own DB credentials.** Crash
     looped on `password authentication failed for user "postgres"` --
     the `database` service's own `POSTGRES_USER=immich`/`PASSWORD`
     don't propagate automatically; confirmed against
     docs.immich.app/install/environment-variables/ that `DB_HOSTNAME`/
     `DB_PORT`/`DB_USERNAME`/`DB_PASSWORD`/`DB_DATABASE_NAME` must be
     set explicitly on `immich-server` itself. Missing from the plan's
     original `compose_requirements` too, not just this session's
     authoring.
  3. **`immich-config.json` unreadable by `immich-server`'s own UID.**
     Templated `owner: root, group: root, mode: 0600`, but the service
     runs as `user: "1000:1000"` (set for NFS write ownership) -- zero
     permission bits for that UID. Fixed to `owner: "1000", group: "1000"`,
     kept `mode: 0600` (still not world-readable -- this file will hold
     a real Authentik client secret once `media-lab-04` reconciles).
  4. **`mp1`/`mp2` NFS mounts didn't land on the first `pct set` attempt**
     (operator-run, cause not fully diagnosed -- confirmed missing from
     live `pct config`, re-run fixed it). Until fixed, Docker had
     silently auto-created empty root-owned placeholder directories at
     the bind-mount targets, which is why the *first* Immich failure was
     a storage-permission error (`EACCES` creating `/data/encoded-video`)
     before the DB-credentials bug was even reached.

- **Authentik + Traefik + DNS hookup: DONE 2026-09-04, verified live.**
  `media-lab-03`/`04`/`05` only got the *code* in place (edge.yaml, the
  OIDC whitelist, the config template) -- none of it was actually live
  until this pass:
  1. Added `JELLYFIN_OAUTH_CLIENT_SECRET`/`IMMICH_OAUTH_CLIENT_SECRET`
     to SOPS (same surgical `sops --set` approach as
     `MEDIA_STACK_LAB_DB_PASSWORD`, verified the same way).
  2. Ran `./with-secrets-prod python3 terraform/lxc/reconcile-edge.py
     --stacks-dir terraform/lxc/stacks --apply --json` (full discovery
     scope, production target). **Two real mistakes caught before this
     ran for real**: an initial dry-run used the wrong wrapper
     (`./with-secrets`, defaulting to `pve-test-vm`) and a single-manifest
     scope that would have looked like it deleted every other stack's DNS
     records in the diff (discovery-vs-apply scope must always match --
     `--stacks-dir` full discovery, never a narrowed manifest list, once
     `--apply` is anywhere in the picture). Corrected both before
     touching production. Also inspected the 7 unrelated stacks the full
     apply would also touch (pre-existing drift, not caused by this
     work) by reusing the reconciler's own `_patch_from_existing` logic
     with `apply=False` hardcoded -- confirmed all 7 were cosmetic
     no-ops (identical URLs/matching-mode, just a reordered
     `property_mappings` list and an echoed-back default field).
     `write_count: 12` (4 creates for jellyfin/immich's app+provider, 8
     benign updates).
  3. **Realized DNS/Traefik don't self-push**: `reconcile-edge.py` only
     *renders* `.generated/technitium/zone-records.json` and
     `.generated/traefik/*.yml` -- getting them live is each target
     stack's own normal provisioning, same as it's always been for every
     other stack (confirmed directly: `deploy-technitium-stack.yml` and
     `deploy-proxy-stack.yml` are what actually push/copy them). Ran
     `./with-secrets-prod scripts/provision.sh --stack proxy-stack`
     (established path, same as any other stack) -- 91 tasks ok, smoke
     test passed. For Technitium, used a narrow standalone play reusing
     the real `technitium_dns_record` role instead of the full
     `--stack technitium-stack` provision, specifically because it's the
     homelab's one live authoritative DNS server (a full provision risks
     touching SSO/zone config and briefly restarting it) -- a
     deliberate, narrower exception for that one stack's outsized blast
     radius, not the general pattern.
  4. **Operator also asked for `media-stack-lab-bg` (192.168.80.10),
     the container's own reverse/breakglass record** -- added to the
     shared seed zone (`terraform/lxc/ansible/files/coredns-lab.zone`),
     matching the established pattern used by `authentik-bg`/
     `harbor-bg`/`netbox-bg`/`portainer-bg`/`proxy-bg`. Confirmed via
     `render-edge-technitium.py`'s own PTR-ownership logic
     (`_assign_ptr_ownership`) that it correctly auto-gets `ptr: true`
     (a unique IP, unlike jellyfin/immich which correctly stay
     `ptr: false` since they share Traefik's already-PTR'd IP with ~15
     other hostnames).
  - **Verified live end-to-end**: `dig` confirms all 4 DNS records
    (jellyfin, immich, media-stack-lab-bg forward, and its reverse);
    `curl` through Traefik with real TLS returns `302` for Jellyfin and
    `200` for Immich.

Written with `.github/prompts/plan-change.prompt.md` per
`docs/agent-design/step-packet-schema.md`. See `plan.md` for the full
step-by-step plan, research, and decisions.

**Every step block carries literal content or exact command sequences,
not just decisions to make** -- rewritten 2026-08-25 so the plan is
actually usable by a local model via `implement-step`, not just by a
frontier one. Two things in the plan are genuinely not step blocks at
all -- plain operator instructions instead: `media-lab-02-scaffold`
(running `scaffold-stack.sh` directly) and
`media-lab-06-jellyfin-sso-plugin` (a UI-only procedure, no config-file
or API path). Every real step block is unconditionally meant for the
local model to run via `implement-step`, which writes its hand-back
into this file -- see the Status section below.

## Quick facts

| | |
|---|---|
| Zone | `media_seg`, VLAN 80, `192.168.80.0/24`, gateway `192.168.80.1` (new) |
| Stack | one combined `media-stack-lab` (Jellyfin + Immich, one LXC) -- candidate `192.168.80.10`, VMID `80010` |
| Storage | NFS, matching legacy media-stack's existing `/nas-media/` pattern -- not local `docker_storage_size` |
| Dedup | none needed -- Immich's built-in Duplicates Utility |
| Immich SSO | native OAuth (no plugin) |
| Jellyfin SSO | `jellyfin-plugin-authentik` (scottfridwin) |
| Auth wiring | **not** a drop-in -- `discover-authentik-edge.py` has a hardcoded per-`(stack, route)` whitelist (6 existing entries: Harbor/Grafana/Portainer/Technitium/OpenWebUI/OpenSearch), each with its own redirect-URI branch. Adding Jellyfin+Immich means editing that shared script carefully, not just writing an `edge.yaml`. |
| Legacy media-stack | stays running, untouched. Not destroyed, not scheduled for retirement by this plan. |
| NAS rule | resolved 2026-09-04: `192.168.1.3`, flat LAN (not a zone), tcp+udp/2049 -- was a placeholder before, now real values in media-lab-00 |
| IP/VMID free? | confirmed 2026-09-04 via read-only production API check against `pve`: `192.168.80.10`/`80010` not in use by any LXC or QEMU guest |
| GPU passthrough | still open -- legacy Jellyfin's (VMID 102) hardware transcoding status not yet checked (`pvesh get /nodes/pve/lxc/102/config`), deferred by operator 2026-09-04 |

## Step status

Updated by the local model's hand-back after each `implement-step` run
(see `.github/prompts/implement-step.prompt.md`) -- the actual edit made
and the actual gate results, not a summary from chat. Read this before
authoring or approving the next step.

- `media-lab-00-create-media-seg-zone`: **done 2026-09-04.** Edited
  `terraform/lxc/network/pve.yaml`: added the `media_seg` SDN zone
  (attachments block), its member/container listing entry, and 4 policy
  rules (edge_seg->media_seg web UIs, media_seg->mgmt_seg Authentik,
  media_seg->192.168.1.3 tcp+udp/2049 NAS). No existing zone/rule
  touched -- insertions only. YAML parses cleanly.
  Gate note: the plan's literal gate command
  (`terragrunt --working-dir terraform/lxc/stacks run --all plan`)
  doesn't work as a real check in this repo -- it sweeps in
  pve-test-only scaffold stacks (net-*/test-*) that fail with
  "Failed to select workspace: EOF", unrelated to this change. Used
  this repo's actual documented pattern instead (see
  `docs/productionize-refactor/runbooks/`):
  `./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/gaming-stack-lab -no-color`
  (adjacent zone, closest analog). Ran it once with the edit and once
  stashed out (A/B) -- both produced the byte-identical
  `Plan: 6 to add, 0 to change, 0 to destroy`, a pre-existing
  state/workspace quirk in this stack's terragrunt setup, confirmed
  unrelated to this edit. Net result: zero incremental diff from
  `media_seg`'s addition. Separately worth noting: VLAN-type SDN zones
  aren't actually Terraform-managed in this repo yet
  (`terraform/lxc/network/NETWORK_CONTRACT.md` documents this as a known
  gap -- applied via `ansible/00-initial-setup/proxmox-sdn-setup.yml`
  instead), so the zone/VLAN creation itself was never going to appear
  as a Terraform-plannable resource regardless of gate wording.
  Not yet applied to production -- `terragrunt apply` and the real SDN
  zone creation are still ahead, out of scope for this plan-only step.
- `media-lab-01-stack-request`: **done 2026-09-04.** Created
  `terraform/lxc/stacks/media-stack-lab/stack-request.yaml`. Two real
  gaps found and fixed while authoring it (documented in the file's own
  header comment):
  - `playbook_content` was entirely missing from the plan's step block --
    `terraform/lxc/scaffold-stack.py` requires it unconditionally
    (`request["playbook_content"]`, no default). Without it,
    `media-lab-02-scaffold` would have failed immediately. Authored one
    modeled on `stack-request.example.yaml`'s minecraft-stack exemplar
    (lxc_base + docker_base roles, write compose, validate, up -d,
    wait_for) plus `deploy-netbox-stack.yml`'s secrets-`.env` pattern.
    Syntax-checked clean (`ansible-playbook --syntax-check`).
  - Jellyfin tag placeholder resolved to the real current stable
    (`10.11.11ubu2604-ls47`, confirmed via Docker Hub 2026-09-04), not
    left as a placeholder.
  - Renamed `DB_PASSWORD` -> `MEDIA_STACK_LAB_DB_PASSWORD` throughout
    (compose requirements + playbook's `.env` templating task) to match
    this repo's per-stack secret-naming convention and avoid a
    flat-environment collision risk. Not yet added to
    `terraform/secrets.common.enc.yaml` -- flagged in `contract_facts`,
    needed before any real deploy, out of scope for this step.
  All 4 gates pass: file exists, parses, NFS paths present, no hardcoded
  password.
- `media-lab-02-scaffold` (operator step, not run via `implement-step`):
  **done 2026-09-04, done by hand -- no `opencode`/local model, per
  explicit operator direction.** Wrote all 5 files directly:
  `stack.yaml`, `docker-compose.yml`, `STACK_CONTRACT.md`,
  `terragrunt.hcl`, `terraform/lxc/ansible/playbooks/deploy-media-stack-lab.yml`.
  Ran the same real validators the script would have --
  `validate-compose.sh --stack media-stack-lab` and
  `ansible-playbook --syntax-check` both pass; the `## Provides`/
  `## Dependencies` contract-section check passes (verified manually).
  `validate-stack-metadata.sh` passes but doesn't actually cover this
  stack -- its `ACTIVE_STACKS` list is fixed and has no way to check an
  arbitrary stack; flagging as a real repo-tooling gap, not something
  this step introduced. See `plan.md`'s hand-back on this step for the
  full detail.
  **Correction 2026-09-04, found only at actual `terragrunt plan` time
  (not by any of this step's own validators): `stack.yaml` was missing
  the `network:\n  zone: media_seg` block entirely.** Per
  `terraform/lxc/network/NETWORK_CONTRACT.md`, stack-to-zone membership
  is declared exactly there -- without it, Terraform resolved this
  stack as a plain untagged `vmbr0` bridge attachment instead of the
  `media_seg` SDN VLAN (confirmed live: a first `terragrunt plan` showed
  `attachment_type = "bridge"`, `zone = null`, `sdn_vnet = null`), and
  would have created the container on the wrong network entirely --
  the SDN zone/vnet/subnet resources wouldn't even have been created,
  since those are gated on `attachment_type == "sdn_vnet"`. Never caught
  by `validate-compose.sh`, the syntax-check, or any gate in this plan --
  this field simply wasn't in the plan's original `stack_yaml` content
  at all (media-lab-01), and wasn't cross-checked against a real
  SDN-attached exemplar (`gaming-stack-lab`'s `stack.yaml`) until this
  point. Fixed in both the live `stack.yaml` and `stack-request.yaml`'s
  historical record. Re-ran `terragrunt plan`: `attachment_type =
  "sdn_vnet"`, `zone = "media_seg"`, `bridge = "tvmedia"`,
  `Plan: 5 to add, 0 to change, 0 to destroy` -- matches the real
  `pentest_seg`/pentagi-stack precedent exactly.
- `media-lab-03-edge-yaml`: **done 2026-09-04.** Created
  `terraform/lxc/stacks/media-stack-lab/edge.yaml` with both routes
  (jellyfin, immich). One deliberate deviation from the plan's literal
  text: used `${LAB_IP_MEDIA_STACK_LAB}` for the backend URLs instead of
  the plan's hardcoded `192.168.80.10` -- every one of this repo's other
  12 `edge.yaml` files uses a `${LAB_IP_<STACK>}` var, none hardcode an
  IP, so the plan's literal content was the actual outlier here. Added
  `LAB_IP_MEDIA_STACK_LAB='192.168.80.10'` to `.env` (tracked,
  non-secret, matches the real established pattern next to
  `LAB_IP_WAZUH`/`LAB_IP_SECPIPE`) to back it. Confirmed technitium-stack
  is the live DNS target for this (not the retired CoreDNS `dns-stack`)
  via `render-edge-technitium.py` being the actual consumer of this
  file's `dns:` block.
  Both of this step's real gates pass (parses, has both routes: jellyfin
  and immich). Also ran `validate-edge-manifests.py` as a bonus check --
  found it fails on `host: ...${LAB_DOMAIN}` for ALL 16 pre-existing
  `edge.yaml` files repo-wide (it doesn't expand `${LAB_DOMAIN}` before
  checking the literal suffix), not something specific to this file --
  a pre-existing repo-tooling gap, not fixed here.
- `media-lab-04-extend-oidc-whitelist`: **done 2026-09-04.** Real
  discrepancy found before editing: there's actually a **7th** existing
  entry (`wazuh-stack`, added 2026-08-29, after this plan was written) --
  the plan's "find this exact dictionary" text only showed 6. Inserted
  after the real 7th entry, not the stale 6-entry text, in both
  `OIDC_ROUTE_CLIENT_IDS` and `OIDC_ROUTE_CLIENT_SECRETS`, plus two new
  branches in `_oidc_redirect_uris`. Also widened this step's own
  `existing-six-entries-untouched` gate check to include `wazuh-stack`
  in the protected-names regex -- as written it wouldn't have caught an
  accidental edit to that 7th entry at all.
  All 3 gates pass (no existing entry touched -- checked against all 7,
  not just 6; file parses; new entries present). Went further than the
  plan's own gates: ran the real `test_discover_authentik_edge.py` suite
  -- all 11 existing tests still pass, confirming no regression to any
  of the 7 live integrations. `git diff` is exactly the 4 intended
  insertions, nothing else touched.
  No live `reconcile-authentik-edge.py` run against real Authentik --
  out of scope for this step, per its own forbidden_actions.
- `media-lab-05-immich-oauth-config`: **done 2026-09-04.** Two real gaps
  found and fixed while authoring this step:
  - Location: the plan put the `.j2` template under
    `terraform/lxc/ansible/files/media-stack-lab/` -- but that directory
    has zero other `.j2` files anywhere in this repo; every real Jinja
    template lives under `terraform/lxc/ansible/templates/` instead
    (e.g. `deploy-ci-runner.yml`'s `terraformrc.j2`). Moved it to
    `terraform/lxc/ansible/templates/media-stack-lab/immich-config.json.j2`
    to match.
  - Variable: the plan's literal `{{ lab_fqdn_authentik }}` isn't a real
    variable anywhere in this repo -- would have rendered empty/undefined.
    Every other stack computes its own `<stack>_fqdn_authentik` from
    `lookup('env', 'LAB_FQDN_AUTHENTIK')` with a fallback (see
    `deploy-monitoring-stack.yml`'s `monitoring_lab_fqdn_authentik`).
    Added the equivalent `media_stack_lab_fqdn_authentik` var to the
    playbook and referenced that instead.
  Also added the templating task itself to
  `deploy-media-stack-lab.yml` (before "Validate docker compose
  configuration", per the plan's own instruction), matching
  `deploy-ci-runner.yml`'s `ansible.builtin.template` idiom.
  Both of this step's gates pass (renders as valid JSON once
  placeholders substituted; `clientSecret` still holds a Jinja
  placeholder, no real value). Playbook still syntax-checks clean after
  the new task and var. `stack-request.yaml`'s embedded
  `playbook_content` intentionally left un-synced -- it's a historical
  record of intent, already diverged from the real playbook since
  `media-lab-02`.
- `media-lab-06-jellyfin-sso-plugin`: **done 2026-09-04, automated --
  turned out NOT to be UI-only after all.** The plan's original premise
  (confirmed by checking the plugin's own docs at the time) was that
  this needed a manual UI click-through with no config-file or API
  path. Re-verified against Jellyfin's real source this session and
  found that's wrong: Jellyfin's core API has genuine, generic
  endpoints for all of it -- `POST /Repositories` (add repo),
  `POST /Packages/Installed/{name}?repositoryUrl=...` (install),
  `POST /Plugins/{pluginId}/Configuration` (set config, works for any
  plugin implementing standard config). Operator generated a Jellyfin
  API key (Dashboard -> API Keys, the one unavoidable manual bootstrap
  step -- same pattern as every other credential this session), added
  to SOPS as `JELLYFIN_API_KEY`. Ran the sequence live: add repo ->
  install plugin (`f4c1d2a3b5e647899abcdef012345678`, confirmed via
  direct `curl` against the plugin's real manifest.json after an
  earlier WebFetch-mediated read suspiciously returned the identical
  value on a "verbatim" retry -- worth double-checking, turned out to
  be correct) -> `docker restart media-stack-lab-jellyfin` (plugin
  DLLs don't hot-load) -> confirmed `Status: Active` -> `POST
  .../Configuration` with the real values.
  **Two real gotchas found by reading `PluginConfiguration.cs` directly
  instead of trusting the plan's original 3-field (URL/ID/secret)
  instructions:**
  - `ForceHttpsRedirect` (default `false`) must be `true` -- source
    comment: without it "the callback URL will use http:// and cause a
    redirect_uri mismatch in Authentik," which is exactly this
    deployment's situation (Traefik terminates TLS, Jellyfin only sees
    plain HTTP internally).
  - `EnableGroupSync` (default `true`) syncs Authentik group membership
    to Jellyfin admin rights every SSO login, gated by `AdminGroup`
    (default `jellyfin-admins`) -- no such Authentik group exists
    anywhere in this session's work. Left at default, the operator's
    first SSO login as `steve` could have silently downgraded their
    already-working local admin rights. Set `EnableGroupSync: false`
    instead (and `AllowedGroup: ""`, since Authentik's own edge-level
    OIDC gate on the route already restricts who reaches Jellyfin's
    login at all) -- group-based permission sync is a future opt-in
    once real Authentik groups exist for it, not now.
  **First real browser test found a genuine bug**: operator's first
  SSO attempt (`/authentik/login`) redirected to
  `/authentik/callback?error=invalid_request&error_description=...`,
  Jellyfin then threw `"The code field is required."` trying to
  process the error response. Root cause confirmed via Authentik's own
  provider API (`GET /api/v3/providers/oauth2/?search=jellyfin`):
  `grant_types: []`. This is the exact same documented bug that hit
  `opensearch-stack` before (`_oidc_provider_payload`'s comment in
  `reconcile-authentik-edge.py`: Authentik defaults an omitted
  `grant_types` to `[]` on create, which makes
  `/application/o/authorize/` reject every request as malformed) --
  `jellyfin` and `immich` were both newly-*created* providers via this
  script (unlike the 7 pre-existing/patched ones), so both hit it;
  `immich` was never actually tested yet but would have failed
  identically. Fixed by adding both to `_oidc_grant_types`'s explicit
  list (matching the `opensearch-stack`/`wazuh-stack` baseline) and
  re-running the same full-discovery `reconcile-edge.py --apply` --
  confirmed live via the provider API afterward: both now show
  `['authorization_code', 'client_credentials', 'password']`.
  **Second real browser test found a second, distinct genuine bug.**
  The grant_types fix got login past the redirect and Authentik's own
  auth prompt cleanly, but the callback then failed: Jellyfin logs
  showed `Error processing request: The request was canceled due to
  the configured HttpClient.Timeout of 100 seconds elapsing. URL GET
  /authentik/callback` -- a classic silent-firewall-drop symptom, not
  an application error. Root cause: the plugin's `AuthentikUrl`
  (`https://authentik.lab.gibbsgreatly.xyz`) is the *public*,
  Traefik-fronted address, so the plugin's server-to-server token
  exchange goes out via `edge_seg` on port 443 -- not the direct
  `mgmt_seg:9443` path `media-lab-00`'s original firewall rule assumed.
  No rule existed for that path at all (confirmed via the router's own
  rule counters: the default-deny had absorbed 1500 dropped packets).
  Added the missing rule (`media_seg -> 192.168.30.10:443`), this time
  using `place-before` targeting the existing deny rule explicitly --
  applying the lesson from the earlier `input`-chain ordering bug
  rather than repeating it. **Verified working end-to-end**: operator
  confirmed a successful login; the new rule's packet counter
  incremented from 0 to 1, confirming real traffic actually took the
  fixed path. **Confirmed 2026-09-04 (operator): `steve`'s SSO login
  landed on the existing migrated account**, not a fresh one --
  matches `UserSyncService.cs`'s lookup-before-create logic verified
  via source earlier. Still open: the same test for Glyn, whose
  Jellyfin and Authentik usernames are both currently `Glyn`
  (case matches, which is what the plugin's lookup needs) but who
  hasn't logged in via SSO yet to confirm live.

  **"Sign in with Authentik" button added to the normal login page**,
  automated (not manual UI) via Jellyfin's real core config API:
  `POST /System/Configuration/branding`, fields confirmed against the
  actual `BrandingOptions` class (`LoginDisclaimer`, `CustomCss`).
  Deliberately *not* a true auto-redirect on page load -- checked
  first: Jellyfin renders `LoginDisclaimer` via
  `element.innerHTML = DOMPurify.sanitize(...)`, which strips both
  `<script>` (never executes via `innerHTML` anyway) and
  `<meta http-equiv="refresh">` (DOMPurify hardens against exactly
  this auto-redirect pattern by design). A real `<form>`/`<button>`
  survives sanitization and is the plugin's own documented approach,
  so that's what got set instead -- one click on
  `https://jellyfin.lab.gibbsgreatly.xyz`, not a separate URL to
  remember.

  **Immich OAuth: also had a real bug, found and fixed 2026-09-04.**
  `immich-config.json.j2` hardcoded `issuerUrl` as
  `.../application/o/immich/`, but Authentik's real application slug
  (per `discover-authentik-edge.py`'s deterministic
  `edge-<stack>-<route>` naming, the same convention Grafana's OAuth
  config already relies on) is `edge-media-stack-lab-immich` --
  discovery returned a real 404, not a network/firewall failure.
  `clientId`/`clientSecret` also rendered empty: the template did a raw
  `lookup("env", ...)` with no default and no `mandatory()`, and
  neither `IMMICH_OAUTH_CLIENT_ID` nor (at original deploy time) the
  SOPS-backed `IMMICH_OAUTH_CLIENT_SECRET` was actually in the
  playbook's env. Fixed by adding vars to `deploy-media-stack-lab.yml`
  matching the established pattern
  (`deploy-monitoring-stack.yml`'s `grafana_oauth_client_id`):
  `default('immich', true)` for the client id, `mandatory()` for the
  secret, and the literal `edge-media-stack-lab-immich` issuer URL.
  Verified live: OIDC discovery now returns 200 from inside the
  `immich-server` container.

  **Immich connected to the NAS photos library, 2026-09-04.** Added a
  read-only bind mount of `/nas-media/pictures` (the NAS's existing
  photo library, distinct from `/nas-media/immich-photos` which is
  Immich's own upload storage) into `immich-server` at
  `/nas-photos-import` (`docker-compose.yml`), backing a new Immich
  **External Library** owned by `steve`. Registered and scanned live
  via the Libraries API (`POST /libraries`, `POST
  /libraries/{id}/scan`) -- found **9,136 photos + 218 videos** on the
  first scan. The LXC-level `mp3` mount point (host
  `/mnt/nas-media-ct80010/pictures`, already correctly UID/GID-remapped
  by the existing whole-tree `bindfs` unit backing `mp1`/`mp2`) was
  added by the operator directly via root SSH `pct set`, since it's a
  `root@pam`-only field and this session's harness permission layer
  blocked driving `pct` commands straight against the `pve` hypervisor
  host. A personal `IMMICH_API_KEY` (Steve's, via Account Settings ->
  API Keys) was added to SOPS for reuse by future Immich API
  automation, matching the existing `JELLYFIN_API_KEY` pattern.
- `media-lab-07-bring-across-existing-users`: **config copy done 2026-09-04,
  `steve`'s login/history check confirmed by the operator; Glyn's still
  pending (operator hasn't been able to check it yet).** Real correction
  to the plan's literal commands: legacy (`192.168.1.6`, VMID 102) and
  media-stack-lab (`192.168.80.10`, VMID 80010) are on **different
  hosts/LXCs** -- the plan's original single `docker run` with two `-v`
  mounts assumed same-host, which doesn't apply. Real sequence used: tar
  legacy's `/config/jellyfin` (root, read-only, legacy never stopped) ->
  `ansible fetch` to workstation -> `ansible copy` to media-stack-lab ->
  stop `media-stack-lab-jellyfin` -> extract into the
  `media-stack-lab_jellyfin-config` volume via a helper `alpine`
  container -> restart. 2.4GB, checksum-verified at both hops.
  **Version mismatch found and accepted as safe**: legacy runs Jellyfin
  10.11.5, media-stack-lab runs 10.11.11 -- not an exact match as the
  plan's literal gate asked for, but the safe direction (older config
  into newer binary is Jellyfin's normal supported upgrade path;
  operator confirmed proceeding rather than downgrading to pin an exact
  match). Startup logs confirm: 3 DB migrations applied cleanly
  (`AddNormalizedUsername`, `UpdateNormalizedUsername`,
  `AddUniqueNormalizedUsernameIndex`), all 5 legacy plugins loaded
  (TMDb, Studio Images, OMDb, MusicBrainz, AudioDB), and the real
  library definitions carried across too (`/movies`, `/tv`, `/music`
  all being watched -- confirms the whole config transferred, not just
  users). `Startup complete 0:00:07`, zero errors. Legacy confirmed
  still running normally afterward (`10.11.5` unchanged), never
  stopped or written to. Temp tarballs cleaned up on both hosts.
  **Per the plan's own mandatory gate**: `steve` logged in and confirmed
  watch history/continue-watching matches legacy (2026-09-04). **Still
  open for Glyn** -- same check, not done yet; this is a human check,
  not something to mark done from the copy succeeding alone. Note:
  Glyn's username is currently `Glyn` in both Authentik and Jellyfin
  (matching case), which is what the SSO plugin's lookup-before-create
  needs to land on the existing account rather than creating a new
  one -- but this hasn't been proven by an actual login yet.
