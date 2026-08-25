# media-stack-v2 plan

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md` for `model_hint: local` steps;
`model_hint: frontier` steps need a strong model and, where noted, direct
operator supervision.

## Research this plan is based on

- **Legacy state**: `terraform/lxc/stacks/media-stack/` -- VMID 102, plain
  LAN (`192.168.1.6`), Jellyfin only, deployed via the generic Tier 2
  Portainer path (`jellyfin-docker-compose.yml`), no `STACK_CONTRACT.md`,
  no SDN zone. Real, live NFS mounts already exist: `/nas-media/video/
  movies`, `/nas-media/video/tv`, `/nas-media/music`, bind-mounted
  straight into the container -- confirmed by reading the actual compose
  file, not assumed. That NFS mount is **not** Terraform/Ansible-managed
  anywhere in this repo (confirmed by search) -- manual host-level setup.
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
  at Authentik's OIDC provider. Authentik publishes an official
  integration guide (`integrations.goauthentik.io/media/immich/`).
  Redirect URIs: `app.immich:///oauth-callback` (mobile),
  `http://DOMAIN:PORT/auth/login` (web). Source:
  `docs.immich.app/administration/oauth/`.
- **Jellyfin has no first-party OIDC.** Chosen plugin:
  `scottfridwin/jellyfin-plugin-authentik` -- Authentik-specific, adds
  auto-provisioning, group-based permissions, admin permission sync,
  profile-picture sync. Repository URL to add in Jellyfin:
  `https://scottfridwin.github.io/jellyfin-plugin-authentik/manifest.json`.
  Needs: Authentik base URL, client ID, client secret. Authentik-side:
  redirect URI `https://<jellyfin-fqdn>/authentik/callback`, scopes
  `openid`, `profile`, `email` (groups included by default), OAuth2
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
  the new stack's image tag to match legacy's current version first.
- **Authentik wiring reuses an existing, live mechanism** -- not a manual
  click-through. `terraform/lxc/reconcile-authentik-edge.py`, driven by
  each stack's own `edge.yaml` (`apiVersion: homelab.gibbsgreatly.xyz/
  v1alpha1`, `kind: EdgeManifest`), already creates/updates an Authentik
  OAuth2/OIDC provider+application and writes the resulting client
  id/secret into env vars named by the manifest's own annotations. This
  is exactly what `monitoring-stack`/Grafana already does in production
  (`terraform/lxc/stacks/monitoring-stack/edge.yaml`) -- both new stacks
  here follow that literal shape, not a new integration approach.
- **Architecture**: two separate contract-driven stacks
  (`jellyfin-stack`, `immich-stack`), not one merged container --
  matches this repo's established one-LXC-per-service convention.
- **Zone precedent**: `docs/stack-lifecycle-refactor/
  stage-10-minecraft-exemplar.md` for the "author a stack-request.yaml,
  then run `scaffold-stack.sh`" split; `network/pve.yaml`'s existing
  zones fill VLANs 10/20/30/40/50/60/70 in a +10 pattern (`game_seg` at
  VLAN 60 exists but is scoped to gaming, not media).

## Decisions (resolved 2026-08-25)

- Zone: new `media_seg`, VLAN 80, `192.168.80.0/24`, gateway `192.168.80.1`.
- Storage: NFS, reusing legacy's existing `/nas-media/` exports.
- Two separate stacks, not one.
- Dedup: none -- Immich's built-in Duplicates Utility.
- Jellyfin SSO plugin: `jellyfin-plugin-authentik` (scottfridwin).

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
  rules both new stacks need (at minimum: LAN -> media_seg reachability
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

## Step: media-v2-01-immich-stack-request

```yaml
id: media-v2-01-immich-stack-request
title: Author stack-request.yaml for immich-stack
model_hint: frontier
depends_on: [media-v2-00-create-media-seg-zone]

change: >
  Create terraform/lxc/stacks/immich-stack/stack-request.yaml (copy
  terraform/lxc/stacks/stack-request.example.yaml as the starting shape).
  stack_yaml: hostname immich-stack, ip_address "192.168.80.10/24"
  (confirm free), gateway/dns_server "192.168.80.1", vmid 80010 (confirm
  free), cores 4, memory 4096, docker_storage_size "20G" (base OS +
  images + Postgres/model-cache only -- the photo library is NFS),
  deployment_tier apps, ansible_playbook deploy-immich-stack,
  portainer_agent false, provides: [{service: immich, port: 2283,
  protocol: tcp}].
  compose_requirements: the literal four-service compose from the
  research section above, adapted: container_name prefixed
  immich-stack-<service>, restart unless-stopped, model-cache as a named
  Docker volume, UPLOAD_LOCATION bind-mounted from an NFS-backed host
  path (e.g. /nas-media/immich-photos) -- NOT a Docker volume, NOT a size
  on docker_storage_size.
  compose_forbidden: a custom top-level networks: block, exposing
  database/redis ports externally, a plain postgres/pgvector image
  instead of the pinned vectorchord fork, UPLOAD_LOCATION as a named
  volume instead of the NFS bind mount.
  contract_facts: zone is media_seg (VLAN 80); prerequisite that
  /nas-media/immich-photos is already NFS-mounted on the LXC before
  first compose up (manual, not IaC-managed); OAuth is configured in a
  later step (media-v2-04), not at first boot; Implementation files
  section listing the five new paths under
  terraform/lxc/stacks/immich-stack/ and
  terraform/lxc/ansible/playbooks/deploy-immich-stack.yml as not
  existing yet.

scope:
  allowed_paths:
    - terraform/lxc/stacks/immich-stack/stack-request.yaml
  forbidden_actions:
    - "Running scaffold-stack.sh -- that's media-v2-02"
    - "Any terragrunt or provision.sh command"
    - "Mounting or modifying the NFS export itself"

gates:
  - id: stack-request-exists
    cmd: "test -f terraform/lxc/stacks/immich-stack/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: stack-request-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/immich-stack/stack-request.yaml'))\""
    expect: "exit 0"
    critical: true
```

## Step: media-v2-02-immich-scaffold

```yaml
id: media-v2-02-immich-scaffold
title: Run the stack scaffolder against immich-stack's stack-request.yaml
model_hint: local
depends_on: [media-v2-01-immich-stack-request]

change: >
  Run terraform/lxc/scaffold-stack.sh immich-stack. Do not author any of
  the five files by hand -- the scaffolder's own sub-agents do that,
  gated by its own validators. Your job is only to run it and report the
  outcome.

scope:
  allowed_paths:
    - terraform/lxc/stacks/immich-stack/
  forbidden_actions:
    - "Hand-editing any of the five generated files if the scaffolder fails partway -- report which validator failed instead"
    - "Any terragrunt or provision.sh command"

gates:
  - id: scaffold-exits-clean
    cmd: "terraform/lxc/scaffold-stack.sh immich-stack"
    expect: "exit 0"
    critical: true
```

## Step: media-v2-03-immich-edge-yaml

```yaml
id: media-v2-03-immich-edge-yaml
title: Author edge.yaml for immich-stack's Authentik OIDC client
model_hint: frontier
depends_on: [media-v2-02-immich-scaffold]

change: >
  Create terraform/lxc/stacks/immich-stack/edge.yaml, copying
  monitoring-stack/edge.yaml's exact shape (apiVersion
  homelab.gibbsgreatly.xyz/v1alpha1, kind EdgeManifest). metadata.name
  immich-edge, metadata.stack immich-stack, annotations
  repo.auth.oidc.client_id_env IMMICH_OAUTH_CLIENT_ID,
  repo.auth.oidc.client_secret_env IMMICH_OAUTH_CLIENT_SECRET.
  spec.routes: one route named immich, host immich.${LAB_DOMAIN},
  backend url http://192.168.80.10:2283, dns enabled target
  ${LAB_IP_PROXY}, tls resolver letsencrypt, auth.mode oidc -- literal
  copy of the shape, only the names/host/backend differ.

scope:
  allowed_paths:
    - terraform/lxc/stacks/immich-stack/edge.yaml
  forbidden_actions:
    - "Modifying any other stack's edge.yaml"
    - "Running reconcile-authentik-edge.py directly -- that happens via the deploy playbook's pre_task, added in this same step's playbook work, not run ad hoc here"

gates:
  - id: edge-yaml-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/immich-stack/edge.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: playbook-has-reconcile-pretask
    cmd: "grep -q 'reconcile-authentik-edge.py' terraform/lxc/ansible/playbooks/deploy-immich-stack.yml"
    expect: "exit 0"
    critical: true
```

## Step: media-v2-04-immich-configure-oauth

Real, delicate integration wiring done after both Immich and its
Authentik client exist -- supervise this one directly rather than
trusting a local model's report alone.

```yaml
id: media-v2-04-immich-configure-oauth
title: Enable OAuth in Immich pointing at the reconciled Authentik client
model_hint: frontier
depends_on: [media-v2-03-immich-edge-yaml]

change: >
  After immich-stack is deployed and media-v2-03's edge.yaml has been
  reconciled (IMMICH_OAUTH_CLIENT_ID/SECRET populated), enable OAuth via
  Immich's Administration > Settings > OAuth Authentication: issuer_url
  https://<authentik-fqdn>/application/o/immich/ (slug matches
  metadata.name from edge.yaml, confirm the actual slug Authentik
  assigned), client ID/secret from the reconciled env vars, redirect
  URIs app.immich:///oauth-callback (mobile) and
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

## Step: media-v2-05-jellyfin-stack-request

```yaml
id: media-v2-05-jellyfin-stack-request
title: Author stack-request.yaml for jellyfin-stack
model_hint: frontier
depends_on: [media-v2-00-create-media-seg-zone]

change: >
  Create terraform/lxc/stacks/jellyfin-stack/stack-request.yaml.
  stack_yaml: hostname jellyfin-stack, ip_address "192.168.80.11/24"
  (confirm free), gateway/dns_server "192.168.80.1", vmid 80011 (confirm
  free), cores 2, memory 2048, docker_storage_size "10G" (config only --
  media library is NFS), deployment_tier apps, ansible_playbook
  deploy-jellyfin-stack, portainer_agent false, provides: [{service:
  jellyfin, port: 8096, protocol: tcp}].
  compose_requirements: single service jellyfin, image
  lscr.io/linuxserver/jellyfin pinned to its current stable release tag
  -- check the actual current tag at authoring time, do NOT carry over
  legacy media-stack's unpinned :latest. container_name
  jellyfin-stack-jellyfin. Environment: PUID=1000, PGID=1000,
  TZ=Pacific/Auckland, JELLYFIN_PublishedServerUrl matching the new
  jellyfin.${LAB_DOMAIN} route (not the legacy gibbsgreatly.xyz bare
  host). Volumes: a named Docker volume for /config (NOT a raw host bind
  path like legacy's /config/jellyfin -- this repo's convention is named
  volumes), plus the same three NFS bind mounts legacy already uses
  unchanged: /nas-media/video/movies:/movies,
  /nas-media/video/tv:/tv, /nas-media/music:/music. Ports 8096, 8920,
  7359/udp, 1900/udp -- same as legacy. group_add ["44","104"],
  security_opt seccomp:unconfined -- same as legacy (hardware
  transcoding group IDs).
  compose_forbidden: a custom top-level networks: block, changing the
  three NFS mount paths (must match legacy exactly so the same NAS
  library is visible), an unpinned image tag.
  contract_facts: zone media_seg (VLAN 80); nothing depends on this
  stack; watch-history migration happens in media-v2-09, not at first
  boot; Implementation files listing the five new paths as not existing
  yet.

scope:
  allowed_paths:
    - terraform/lxc/stacks/jellyfin-stack/stack-request.yaml
  forbidden_actions:
    - "Running scaffold-stack.sh -- that's media-v2-06"
    - "Any terragrunt or provision.sh command"
    - "Changing the /nas-media/ mount paths from what legacy already uses"

gates:
  - id: stack-request-exists
    cmd: "test -f terraform/lxc/stacks/jellyfin-stack/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: stack-request-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/jellyfin-stack/stack-request.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: nfs-paths-match-legacy
    cmd: "grep -q '/nas-media/video/movies' terraform/lxc/stacks/jellyfin-stack/stack-request.yaml && grep -q '/nas-media/video/tv' terraform/lxc/stacks/jellyfin-stack/stack-request.yaml && grep -q '/nas-media/music' terraform/lxc/stacks/jellyfin-stack/stack-request.yaml"
    expect: "exit 0"
    critical: true
```

## Step: media-v2-06-jellyfin-scaffold

```yaml
id: media-v2-06-jellyfin-scaffold
title: Run the stack scaffolder against jellyfin-stack's stack-request.yaml
model_hint: local
depends_on: [media-v2-05-jellyfin-stack-request]

change: >
  Run terraform/lxc/scaffold-stack.sh jellyfin-stack. Do not author any
  of the five files by hand. Your job is only to run it and report the
  outcome.

scope:
  allowed_paths:
    - terraform/lxc/stacks/jellyfin-stack/
  forbidden_actions:
    - "Hand-editing any of the five generated files if the scaffolder fails partway -- report which validator failed instead"
    - "Any terragrunt or provision.sh command"

gates:
  - id: scaffold-exits-clean
    cmd: "terraform/lxc/scaffold-stack.sh jellyfin-stack"
    expect: "exit 0"
    critical: true
```

## Step: media-v2-07-jellyfin-edge-yaml

```yaml
id: media-v2-07-jellyfin-edge-yaml
title: Author edge.yaml for jellyfin-stack's Authentik OIDC client
model_hint: frontier
depends_on: [media-v2-06-jellyfin-scaffold]

change: >
  Create terraform/lxc/stacks/jellyfin-stack/edge.yaml, same shape as
  immich-stack's (media-v2-03). metadata.name jellyfin-edge,
  metadata.stack jellyfin-stack, annotations
  repo.auth.oidc.client_id_env JELLYFIN_OAUTH_CLIENT_ID,
  repo.auth.oidc.client_secret_env JELLYFIN_OAUTH_CLIENT_SECRET.
  spec.routes: one route named jellyfin, host jellyfin.${LAB_DOMAIN},
  backend url http://192.168.80.11:8096, dns enabled target
  ${LAB_IP_PROXY}, tls resolver letsencrypt, auth.mode oidc.

scope:
  allowed_paths:
    - terraform/lxc/stacks/jellyfin-stack/edge.yaml
  forbidden_actions:
    - "Modifying any other stack's edge.yaml"

gates:
  - id: edge-yaml-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/jellyfin-stack/edge.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: playbook-has-reconcile-pretask
    cmd: "grep -q 'reconcile-authentik-edge.py' terraform/lxc/ansible/playbooks/deploy-jellyfin-stack.yml"
    expect: "exit 0"
    critical: true
```

## Step: media-v2-08-jellyfin-configure-sso-plugin

```yaml
id: media-v2-08-jellyfin-configure-sso-plugin
title: Install and configure jellyfin-plugin-authentik
model_hint: frontier
depends_on: [media-v2-07-jellyfin-edge-yaml]

change: >
  After jellyfin-stack is deployed and media-v2-07's edge.yaml has been
  reconciled: in Authentik, set the OAuth2 provider's redirect URI to
  https://jellyfin.${LAB_DOMAIN}/authentik/callback and confirm scopes
  openid/profile/email (groups included by default), client type
  Confidential. In Jellyfin: add plugin repository
  https://scottfridwin.github.io/jellyfin-plugin-authentik/manifest.json,
  install "Authentik SSO" from the Catalog, configure it with Authentik
  base URL, client ID, client secret from the reconciled
  JELLYFIN_OAUTH_CLIENT_ID/SECRET env vars.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Disabling Jellyfin's existing local-password login while testing -- keep it available until SSO login is verified working"

gates:
  - id: plugin-installed
    cmd: "curl -s http://192.168.80.11:8096/Plugins | python3 -c \"import json,sys; d=json.load(sys.stdin); exit(0 if any('Authentik' in p.get('Name','') for p in d) else 1)\""
    expect: "exit 0"
    critical: true
```

## Step: media-v2-09-migrate-watch-history

Real user data, not a mechanical step. Read before overwriting; verify
the copy against the source before treating it as done.

```yaml
id: media-v2-09-migrate-watch-history
title: Migrate users and watch history from legacy media-stack's Jellyfin
model_hint: frontier
depends_on: [media-v2-06-jellyfin-scaffold]

change: >
  Confirm legacy media-stack's Jellyfin image version (docker inspect
  the running jellyfin container on media-stack, VMID 102). Pin
  jellyfin-stack's compose to that exact same tag before first boot --
  do not let it start on a different version first, or the config
  migration needs surgical SQL-table copying instead of a plain copy.
  Stop the new jellyfin-stack container (not legacy -- legacy stays live
  until this is verified). Copy legacy's entire /config directory (the
  named volume or bind path backing it, containing jellyfin.db and
  library.db -- users, watch history, library config) onto
  jellyfin-stack's config volume, preserving ownership. Start
  jellyfin-stack, verify existing users can log in with their existing
  local passwords and see correct watch history before considering this
  done. Only after that verification should the SSO plugin
  (media-v2-08) or an image-version upgrade be layered on.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Modifying or deleting anything in legacy media-stack's /config -- read/copy only, this must stay a working fallback until decommissioning is explicitly approved"
    - "Upgrading jellyfin-stack's image tag before the config copy is verified"

gates:
  - id: image-versions-matched-before-copy
    cmd: "docker inspect --format '{{.Config.Image}}' jellyfin (on media-stack) vs jellyfin-stack-jellyfin (on jellyfin-stack) -- confirm identical tag"
    expect: "identical"
    critical: true
  - id: existing-user-can-login-with-history-intact
    cmd: "manual verification: log in as an existing user, confirm watch history/continue-watching matches legacy"
    expect: "matches"
    critical: true
```

## Step: media-v2-10-decommission-legacy-media-stack

**Not authorized by this plan.** This is the one genuinely destructive
step here -- destroying the legacy container -- and per CLAUDE.md needs
its own fresh operator approval when the time actually comes, not a
green light inherited from planning this far ahead. Included only so the
plan is complete and the dependency is explicit.

```yaml
id: media-v2-10-decommission-legacy-media-stack
title: Destroy legacy media-stack (VMID 102) after verification
model_hint: frontier
depends_on: [media-v2-04-immich-configure-oauth, media-v2-08-jellyfin-configure-sso-plugin, media-v2-09-migrate-watch-history]

change: >
  Only after jellyfin-stack and immich-stack are both live, SSO-verified,
  and watch history is confirmed correct for a real sample of users over
  a real period of use (not just immediately after migration): destroy
  legacy media-stack (VMID 102) via the normal terragrunt destroy path.
  Requires a fresh, explicit operator "proceed" at the time -- this plan
  does not pre-approve it.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Running this step without a fresh, explicit operator approval given at the time, regardless of how long ago this plan was written"

gates:
  - id: operator-approval-given-today
    cmd: "n/a -- this is a human approval gate, not a runnable check"
    expect: "explicit operator sign-off in chat, dated at time of execution"
    critical: true
```

---

## Not covered by this plan

- Confirming candidate IPs/VMIDs are actually free (read-only check,
  before `terragrunt apply`).
- `terragrunt plan`/`apply` for the zone and both stacks,
  `provision.sh --stack <name>`, and health-check validation -- real
  infrastructure steps, stay manual/operator-run.
- Hardware transcoding passthrough for the new jellyfin-stack (legacy's
  `group_add`/`security_opt` are carried over as a starting point, but
  GPU device passthrough itself isn't addressed here).
- Backup strategy for the photo library, Postgres data, and Jellyfin
  config -- a real gap for anything holding irreplaceable personal data.
- A rollback plan if SSO integration breaks login for either app after
  legacy is decommissioned.
