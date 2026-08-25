# media-stack-v2 plan

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md` for `model_hint: local` steps;
`model_hint: frontier` steps need a strong model and, where noted, direct
operator supervision.

**Not a replacement plan.** Legacy `media-stack` (VMID 102) keeps running,
untouched, for as long as the operator wants. This plan only stands up a
new, additive `media-stack-v2` and brings existing Jellyfin users/watch
history across so it's a real alternative to switch to whenever ready --
it does not schedule or assume retiring the old one.

## Research this plan is based on

- **Legacy state**: `terraform/lxc/stacks/media-stack/` -- VMID 102, plain
  LAN (`192.168.1.6`), Jellyfin only, deployed via the generic Tier 2
  Portainer path (`jellyfin-docker-compose.yml`), no `STACK_CONTRACT.md`,
  no SDN zone. Real, live NFS mounts already exist: `/nas-media/video/
  movies`, `/nas-media/video/tv`, `/nas-media/music`, bind-mounted
  straight into the container -- confirmed by reading the actual compose
  file, not assumed. That NFS mount is **not** Terraform/Ansible-managed
  anywhere in this repo (confirmed by search) -- manual host-level setup.
- **One combined stack, not two** -- operator's explicit preference over
  this repo's usual one-LXC-per-service convention. Jellyfin and both
  Immich services and its two supporting containers (5 services total)
  all live in one compose file, one LXC, one `stack.yaml`.
- **Immich upstream facts** (fetched live from
  `github.com/immich-app/immich/main/docker/docker-compose.yml`): four
  services -- `immich-server` (port 2283, depends on redis+database),
  `immich-machine-learning` (own `model-cache` volume), `redis` (actually
  `valkey/valkey:9`, digest-pinned), `database`
  (`ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0`,
  digest-pinned -- Immich's vector search requires this specific fork,
  not vanilla postgres/pgvector).
- **Immich OAuth**: native, first-party, no plugin. Enable in
  Administration > Settings > OAuth Authentication, `issuer_url` pointing
  at Authentik's OIDC provider. Redirect URIs:
  `app.immich:///oauth-callback` (mobile),
  `http://DOMAIN:PORT/auth/login` (web). Source:
  `docs.immich.app/administration/oauth/`.
- **Jellyfin has no first-party OIDC.** Chosen plugin:
  `scottfridwin/jellyfin-plugin-authentik` -- Authentik-specific, adds
  auto-provisioning, group-based permissions, admin permission sync,
  profile-picture sync. Repository URL to add in Jellyfin:
  `https://scottfridwin.github.io/jellyfin-plugin-authentik/manifest.json`.
  Redirect URI `https://<jellyfin-fqdn>/authentik/callback`, scopes
  `openid`/`profile`/`email` (groups included by default), OAuth2
  provider client type Confidential.
- **Dedup**: none needed. Immich ships an official, ML-based Duplicates
  Utility enabled by default (`docs.immich.app/features/
  duplicates-utility/`) -- third-party tools like `immich_duplicate_finder`
  predate this and are now redundant.
- **Watch-history migration**: Jellyfin's own official migration doc
  (`jellyfin.org/docs/general/administration/migrate/`) confirms the
  reliable path is copying the whole config directory (holds
  `jellyfin.db`, users + watch-history) onto the new container, **only
  if both run the same Jellyfin version** -- cross-version copying needs
  surgical SQL-table copying instead, which this plan avoids by pinning
  the new stack's Jellyfin image tag to match legacy's current version
  first. **Legacy's own /config is read-only for this whole plan** --
  copy from it, never modify it, so it keeps working exactly as-is for
  as long as anyone's still using it.
- **Authentik wiring is not a generic drop-in -- corrected finding.**
  `terraform/lxc/reconcile-authentik-edge.py` and
  `terraform/lxc/discover-authentik-edge.py` do real, reusable OIDC
  provider/application reconciliation from `edge.yaml`, but which
  `(stack, route)` pairs actually get a client is a **hardcoded
  whitelist** (`OIDC_ROUTE_CLIENT_IDS`/`OIDC_ROUTE_CLIENT_SECRETS` in
  `discover-authentik-edge.py`, 6 existing entries: harbor-stack/harbor,
  monitoring-stack/grafana, portainer-stack/portainer,
  technitium-stack/technitium, ai-services-stack/openwebui,
  opensearch-stack/dashboards), each paired with its own hardcoded
  redirect-URI branch in `_oidc_redirect_uris`. Writing an `edge.yaml`
  alone does nothing for a route not in that whitelist. Adding
  media-stack-v2's two routes means editing this shared script directly
  -- real code work touching something 6 live production integrations
  already depend on, done additively (new entries only, never touching
  the existing 6).
- **Zone precedent**: `docs/stack-lifecycle-refactor/
  stage-10-minecraft-exemplar.md` for the "author a stack-request.yaml,
  then run `scaffold-stack.sh`" split; `network/pve.yaml`'s existing
  zones fill VLANs 10/20/30/40/50/60/70 in a +10 pattern (`game_seg` at
  VLAN 60 exists but is scoped to gaming, not media).

## Decisions (resolved 2026-08-25)

- Zone: new `media_seg`, VLAN 80, `192.168.80.0/24`, gateway `192.168.80.1`.
- Storage: NFS, reusing legacy's existing `/nas-media/` exports.
- **One combined stack** (`media-stack-v2`), not split into two -- needs
  its own directory name distinct from legacy's still-live
  `terraform/lxc/stacks/media-stack/` to avoid a Terraform-state
  collision, but is one LXC hosting both apps.
- Dedup: none -- Immich's built-in Duplicates Utility.
- Jellyfin SSO plugin: `jellyfin-plugin-authentik` (scottfridwin) --
  native OIDC-in-app, confirmed over the alternative of `auth.mode:
  forwardAuth` (Authentik gating Traefik via the existing shared
  forward-auth outpost, no whitelist edit needed). forwardAuth is
  simpler to wire up but is just an access gate in front of Jellyfin's
  own separate login, not real per-user identity integration (no
  auto-provisioning, group-based permissions, or profile-picture sync) --
  rejected for that reason, keeping media-v2-04's whitelist edit in the
  plan.
- **Additive, not destructive**: legacy `media-stack` is never modified
  or destroyed by this plan. No step here schedules or assumes its
  retirement.

---

## Step: media-v2-00-create-media-seg-zone

Real Terraform/SDN/MikroTik work, not a stack-request.yaml field, and not
a step a local model should attempt.

```yaml
id: media-v2-00-create-media-seg-zone
title: Create media_seg SDN zone (VLAN 80, 192.168.80.0/24)
model_hint: frontier
depends_on: []

change: >
  Add a media_seg zone to terraform/lxc/network/pve.yaml following the
  existing zone blocks' exact shape (see infra_seg/ai_seg/game_seg for
  the pattern). VLAN 80, subnet 192.168.80.0/24, gateway 192.168.80.1.
  Add the matching MikroTik trunk/VLAN interface and cross-zone firewall
  rules the new stack needs (at minimum: LAN -> media_seg reachability
  for the workstation; media_seg -> Authentik for OIDC; media_seg ->
  NAS for NFS). Additive-only (new zone, no changes to existing zones) --
  CLAUDE.md's tier for that is apply + scripts/provision.sh --stack
  <name> against 1-2 adjacent-zone stacks to confirm no regression, not
  a full teardown.

scope:
  allowed_paths:
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Modifying any existing zone's subnet, gateway, or firewall rule"
    - "Applying directly against pve without this repo's normal branch/validate/promote workflow"

gates:
  - id: terragrunt-plan-shows-only-additions
    cmd: "./with-secrets terragrunt --working-dir terraform/lxc/stacks run --all plan"
    expect: "plan shows only new resources for media_seg -- zero changes/deletions to any existing zone"
    critical: true
```

## Step: media-v2-01-stack-request

```yaml
id: media-v2-01-stack-request
title: Author stack-request.yaml for the combined media-stack-v2
model_hint: frontier
depends_on: [media-v2-00-create-media-seg-zone]

change: >
  Create terraform/lxc/stacks/media-stack-v2/stack-request.yaml (copy
  terraform/lxc/stacks/stack-request.example.yaml as the starting shape).
  stack_yaml: hostname media-stack-v2, ip_address "192.168.80.10/24"
  (confirm free), gateway/dns_server "192.168.80.1", vmid 80010 (confirm
  free), cores 6, memory 6144 (Jellyfin transcoding + Immich ML
  inference + Postgres combined in one LXC -- an estimate, not verified
  under real load; monitor and adjust after deploy), docker_storage_size
  "30G" (base OS + images + Postgres + model-cache + Jellyfin config
  only -- all media libraries stay NFS, not local storage),
  deployment_tier apps, ansible_playbook deploy-media-stack-v2,
  portainer_agent false, provides: [{service: jellyfin, port: 8096,
  protocol: tcp}, {service: immich, port: 2283, protocol: tcp}].
  compose_requirements: five services in one compose file --
  (1) jellyfin: image lscr.io/linuxserver/jellyfin pinned to its current
  stable release tag (check the actual current tag at authoring time,
  do NOT carry over legacy's unpinned :latest), container_name
  media-stack-v2-jellyfin, env PUID=1000/PGID=1000/TZ=Pacific/Auckland/
  JELLYFIN_PublishedServerUrl matching jellyfin.${LAB_DOMAIN}, a named
  Docker volume for /config (not legacy's raw host bind path -- this
  repo's convention is named volumes), the same three NFS bind mounts
  legacy already uses unchanged (/nas-media/video/movies:/movies,
  /nas-media/video/tv:/tv, /nas-media/music:/music), ports 8096/8920/
  7359 udp/1900 udp, group_add ["44","104"], security_opt
  seccomp:unconfined -- all matching legacy's existing working config.
  (2) immich-server: ghcr.io/immich-app/immich-server:${IMMICH_VERSION:-release},
  container_name media-stack-v2-immich-server, port 2283, depends_on
  redis+database, UPLOAD_LOCATION bind-mounted from an NFS-backed host
  path (e.g. /nas-media/immich-photos) -- NOT a Docker volume.
  (3) immich-machine-learning:
  ghcr.io/immich-app/immich-machine-learning:${IMMICH_VERSION:-release},
  container_name media-stack-v2-immich-ml, model-cache as a named Docker
  volume. (4) redis (actually valkey/valkey:9, digest-pinned per
  upstream), container_name media-stack-v2-redis. (5) database
  (ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0,
  digest-pinned per upstream -- not a plain postgres/pgvector image),
  container_name media-stack-v2-database. All restart: unless-stopped
  (repo convention, not upstream's bare `always`).
  compose_forbidden: a custom top-level networks: block, exposing
  database/redis ports externally, a plain postgres/pgvector image
  instead of the pinned vectorchord fork, UPLOAD_LOCATION as a named
  volume instead of the NFS bind mount, changing the three Jellyfin NFS
  mount paths from what legacy already uses, an unpinned Jellyfin image
  tag.
  contract_facts: zone media_seg (VLAN 80); nothing depends on this
  stack; legacy media-stack (VMID 102) keeps running unaffected --
  this is additive, not a migration-then-destroy; prerequisite that
  /nas-media/immich-photos is already NFS-mounted on the LXC before
  first compose up (manual, not IaC-managed); OAuth/SSO configured in
  later steps, not at first boot; watch-history brought across in
  media-v2-06, also not at first boot; Implementation files section
  listing the five new paths under terraform/lxc/stacks/media-stack-v2/
  and terraform/lxc/ansible/playbooks/deploy-media-stack-v2.yml as not
  existing yet.

scope:
  allowed_paths:
    - terraform/lxc/stacks/media-stack-v2/stack-request.yaml
  forbidden_actions:
    - "Running scaffold-stack.sh -- that's media-v2-02"
    - "Any terragrunt or provision.sh command"
    - "Mounting or modifying the NFS export itself"
    - "Touching legacy media-stack (VMID 102) in any way"

gates:
  - id: stack-request-exists
    cmd: "test -f terraform/lxc/stacks/media-stack-v2/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: stack-request-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/media-stack-v2/stack-request.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: nfs-paths-match-legacy
    cmd: "grep -q '/nas-media/video/movies' terraform/lxc/stacks/media-stack-v2/stack-request.yaml && grep -q '/nas-media/video/tv' terraform/lxc/stacks/media-stack-v2/stack-request.yaml && grep -q '/nas-media/music' terraform/lxc/stacks/media-stack-v2/stack-request.yaml"
    expect: "exit 0"
    critical: true
```

## Step: media-v2-02-scaffold

```yaml
id: media-v2-02-scaffold
title: Run the stack scaffolder against media-stack-v2's stack-request.yaml
model_hint: local
depends_on: [media-v2-01-stack-request]

change: >
  Run terraform/lxc/scaffold-stack.sh media-stack-v2. Do not author any
  of the five files by hand -- the scaffolder's own sub-agents do that,
  gated by its own validators. Your job is only to run it and report the
  outcome.

scope:
  allowed_paths:
    - terraform/lxc/stacks/media-stack-v2/
  forbidden_actions:
    - "Hand-editing any of the five generated files if the scaffolder fails partway -- report which validator failed instead"
    - "Any terragrunt or provision.sh command"

gates:
  - id: scaffold-exits-clean
    cmd: "terraform/lxc/scaffold-stack.sh media-stack-v2"
    expect: "exit 0"
    critical: true
```

## Step: media-v2-03-edge-yaml

```yaml
id: media-v2-03-edge-yaml
title: Author edge.yaml with both routes (jellyfin, immich)
model_hint: frontier
depends_on: [media-v2-02-scaffold]

change: >
  Create terraform/lxc/stacks/media-stack-v2/edge.yaml, copying
  monitoring-stack/edge.yaml's exact shape (apiVersion
  homelab.gibbsgreatly.xyz/v1alpha1, kind EdgeManifest).
  metadata.name media-stack-v2-edge, metadata.stack media-stack-v2.
  spec.routes: two entries -- {name: jellyfin, host:
  jellyfin.${LAB_DOMAIN}, backend: {type: url, url:
  http://192.168.80.10:8096}, dns: {enabled: true, target:
  ${LAB_IP_PROXY}, ttl: 5m}, tls: {resolver: letsencrypt}, auth: {mode:
  oidc}} and {name: immich, host: immich.${LAB_DOMAIN}, backend: {type:
  url, url: http://192.168.80.10:2283}, dns/tls same shape, auth: {mode:
  oidc}}. discover-authentik-edge.py's _build_route_intents derives one
  Authentik app+provider per route (keyed by stack+route name), so this
  one manifest correctly produces two independent OIDC clients --
  confirmed by reading that function, not assumed.

scope:
  allowed_paths:
    - terraform/lxc/stacks/media-stack-v2/edge.yaml
  forbidden_actions:
    - "Modifying any other stack's edge.yaml"
    - "Editing discover-authentik-edge.py or reconcile-authentik-edge.py -- that's media-v2-04, kept separate since it touches shared code"

gates:
  - id: edge-yaml-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/media-stack-v2/edge.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: has-both-routes
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/media-stack-v2/edge.yaml')); names={r['name'] for r in d['spec']['routes']}; exit(0 if names=={'jellyfin','immich'} else 1)\""
    expect: "exit 0"
    critical: true
```

## Step: media-v2-04-extend-oidc-whitelist

**Not a step for a local model.** This edits a shared script 6 live
production integrations (Harbor, Grafana, Portainer, Technitium,
OpenWebUI, OpenSearch) already depend on. The gate below is what makes
this safe to attempt at all -- if it doesn't pass clean, stop and don't
apply.

```yaml
id: media-v2-04-extend-oidc-whitelist
title: Add jellyfin/immich routes to discover-authentik-edge.py's whitelist
model_hint: frontier
depends_on: [media-v2-03-edge-yaml]

change: >
  In terraform/lxc/discover-authentik-edge.py, add two entries to
  OIDC_ROUTE_CLIENT_IDS: ("media-stack-v2", "jellyfin"):
  ("JELLYFIN_OAUTH_CLIENT_ID", "jellyfin"), ("media-stack-v2", "immich"):
  ("IMMICH_OAUTH_CLIENT_ID", "immich"). Add matching entries to
  OIDC_ROUTE_CLIENT_SECRETS: ("media-stack-v2", "jellyfin"):
  "JELLYFIN_OAUTH_CLIENT_SECRET", ("media-stack-v2", "immich"):
  "IMMICH_OAUTH_CLIENT_SECRET". Add two branches to _oidc_redirect_uris:
  for ("media-stack-v2", "jellyfin") return
  (f"{base_url}/authentik/callback",); for ("media-stack-v2", "immich")
  return (f"{base_url}/auth/login",) -- Immich's mobile deep-link
  redirect (app.immich:///oauth-callback) is configured directly in
  Immich's own OAuth settings in media-v2-05, not through this script.
  Do not reorder, rename, or otherwise touch any of the existing 6
  entries or branches.

scope:
  allowed_paths:
    - terraform/lxc/discover-authentik-edge.py
  forbidden_actions:
    - "Any change to the existing 6 (stack, route) entries or their redirect-URI branches"
    - "Editing reconcile-authentik-edge.py in this step"
    - "Running reconcile-authentik-edge.py against real Authentik in this step -- that's a separate, supervised action after this diff is reviewed"

gates:
  - id: existing-six-entries-untouched
    cmd: "git diff terraform/lxc/discover-authentik-edge.py | grep -E '^-' | grep -E 'harbor-stack|monitoring-stack|portainer-stack|technitium-stack|ai-services-stack|opensearch-stack'"
    expect: "no output -- any match here means an existing entry was touched, which must not happen"
    critical: true
  - id: file-still-imports-cleanly
    cmd: "python3 -c \"import ast; ast.parse(open('terraform/lxc/discover-authentik-edge.py').read())\""
    expect: "exit 0"
    critical: true
  - id: new-entries-present
    cmd: "grep -q 'media-stack-v2.*jellyfin' terraform/lxc/discover-authentik-edge.py && grep -q 'media-stack-v2.*immich' terraform/lxc/discover-authentik-edge.py"
    expect: "exit 0"
    critical: true
```

## Step: media-v2-05-configure-immich-oauth

```yaml
id: media-v2-05-configure-immich-oauth
title: Enable OAuth in Immich pointing at the reconciled Authentik client
model_hint: frontier
depends_on: [media-v2-04-extend-oidc-whitelist]

change: >
  After media-stack-v2 is deployed and reconcile-authentik-edge.py has
  been run against the updated edge.yaml (IMMICH_OAUTH_CLIENT_ID/SECRET
  populated), enable OAuth via Immich's Administration > Settings >
  OAuth Authentication: issuer_url https://<authentik-fqdn>/application/o/<slug>/
  (confirm the actual slug Authentik assigned for the immich route),
  client ID/secret from the reconciled env vars, redirect URIs
  app.immich:///oauth-callback (mobile) and
  https://immich.${LAB_DOMAIN}/auth/login (web).

scope:
  allowed_paths: []
  forbidden_actions:
    - "Disabling Immich's existing local-password login while testing -- keep it available until OIDC login is verified working"

gates:
  - id: oauth-enabled-in-system-config
    cmd: "curl -s -H \"Authorization: Bearer $IMMICH_ADMIN_API_KEY\" https://immich.${LAB_DOMAIN}/api/system-config | python3 -c \"import json,sys; d=json.load(sys.stdin); exit(0 if d['oauth']['enabled'] else 1)\""
    expect: "exit 0"
    critical: true
```

## Step: media-v2-06-configure-jellyfin-sso-plugin

```yaml
id: media-v2-06-configure-jellyfin-sso-plugin
title: Install and configure jellyfin-plugin-authentik
model_hint: frontier
depends_on: [media-v2-04-extend-oidc-whitelist]

change: >
  After media-stack-v2 is deployed and reconcile-authentik-edge.py has
  been run: in Authentik, confirm the jellyfin route's OAuth2 provider
  redirect URI is https://jellyfin.${LAB_DOMAIN}/authentik/callback,
  scopes openid/profile/email, client type Confidential. In Jellyfin:
  add plugin repository
  https://scottfridwin.github.io/jellyfin-plugin-authentik/manifest.json,
  install "Authentik SSO" from the Catalog, configure it with Authentik
  base URL, client ID/secret from the reconciled
  JELLYFIN_OAUTH_CLIENT_ID/SECRET env vars.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Disabling Jellyfin's existing local-password login while testing -- keep it available until SSO login is verified working"

gates:
  - id: plugin-installed
    cmd: "curl -s http://192.168.80.10:8096/Plugins | python3 -c \"import json,sys; d=json.load(sys.stdin); exit(0 if any('Authentik' in p.get('Name','') for p in d) else 1)\""
    expect: "exit 0"
    critical: true
```

## Step: media-v2-07-bring-across-existing-users

Real user data, additive only. Legacy stays running and unmodified
throughout -- this step only ever reads from it.

```yaml
id: media-v2-07-bring-across-existing-users
title: Bring existing Jellyfin users and watch history into media-stack-v2
model_hint: frontier
depends_on: [media-v2-02-scaffold]

change: >
  Confirm legacy media-stack's Jellyfin image version (docker inspect
  the running jellyfin container on media-stack, VMID 102, read-only).
  Pin media-stack-v2's Jellyfin service to that exact same tag before
  first boot -- do not let it start on a different version first, or
  this needs surgical SQL-table copying instead of a plain copy. Stop
  media-stack-v2's jellyfin service only (never touch legacy). Copy
  legacy's entire /config directory (containing jellyfin.db and
  library.db -- users, watch history, library config) onto
  media-stack-v2's jellyfin config volume, preserving ownership -- this
  is a copy, not a move; legacy's own /config is never modified. Start
  media-stack-v2's jellyfin service, verify existing users can log in
  with their existing local passwords and see correct watch history.
  Only after that verification should the SSO plugin (media-v2-06) or a
  Jellyfin image-version upgrade be layered on. Legacy media-stack
  keeps running throughout and after -- this step does not end with
  turning anything off.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Any write to legacy media-stack's /config -- read/copy only, forever, not just until this step is done"
    - "Stopping, restarting, or otherwise touching legacy's jellyfin container"
    - "Upgrading media-stack-v2's Jellyfin image tag before the config copy is verified"

gates:
  - id: image-versions-matched-before-copy
    cmd: "docker inspect --format '{{.Config.Image}}' jellyfin (on media-stack) vs media-stack-v2-jellyfin (on media-stack-v2) -- confirm identical tag"
    expect: "identical"
    critical: true
  - id: existing-user-can-login-with-history-intact
    cmd: "manual verification: log in as an existing user on media-stack-v2, confirm watch history/continue-watching matches legacy"
    expect: "matches"
    critical: true
  - id: legacy-still-running-unmodified
    cmd: "docker inspect --format '{{.State.Status}}' jellyfin (on media-stack) -- confirm still running"
    expect: "running"
    critical: true
```

---

## Not covered by this plan

- Confirming the candidate IP/VMID are actually free (read-only check,
  before `terragrunt apply`).
- `terragrunt plan`/`apply` for the zone and the stack,
  `provision.sh --stack media-stack-v2`, and health-check validation --
  real infrastructure steps, stay manual/operator-run.
- Hardware transcoding passthrough for media-stack-v2's Jellyfin
  (legacy's `group_add`/`security_opt` are carried over as a starting
  point, but GPU device passthrough itself isn't addressed here).
- Backup strategy for the photo library, Postgres data, and Jellyfin
  config -- a real gap for anything holding irreplaceable personal data.
- **Retiring legacy `media-stack`.** Deliberately not in this plan at
  all, not even as a deferred step -- that's the operator's own future
  call, made whenever (if ever) it's wanted, with its own fresh approval
  at that time. This plan's job ends at "media-stack-v2 works as a real
  alternative," not "legacy is gone."
