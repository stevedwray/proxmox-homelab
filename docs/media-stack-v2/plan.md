# media-stack-v2 plan

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md`.

**Rewritten 2026-08-25 to actually serve the goal: make this doable by a
local model.** The first version described *what* each step should
decide; that's still frontier work, just done here in advance instead of
left for whoever executes the step. Every step block below now carries
the real, literal content or exact command sequence to apply -- the
residual work is transcription and running specified checks, not
judgment. Two things in this plan are genuinely not step blocks at all,
and are written as plain operator instructions instead:
`media-v2-02-scaffold` (running `scaffold-stack.sh` directly) and
`media-v2-06-jellyfin-sso-plugin` (a UI-only procedure, confirmed by
checking the plugin's own docs, not assumed). Everything else is a real
step block, meant to be run through `implement-step` as-is.

**Not a replacement plan.** Legacy `media-stack` (VMID 102) keeps running,
untouched, for as long as the operator wants.

## Research this plan is based on

(Unchanged from the previous version -- see git history for the full
research trail. Summary: legacy media-stack's real NFS mounts and compose
content, Immich's real 4-service upstream compose, Immich's native OAuth
support, Jellyfin's lack of native OIDC and the chosen
`jellyfin-plugin-authentik` plugin, Immich's built-in Duplicates Utility
making a separate dedup app unnecessary, Jellyfin's official
same-version-config-copy migration guidance, and the corrected finding
that `discover-authentik-edge.py`'s OIDC wiring is a hardcoded
per-`(stack,route)` whitelist, not a generic drop-in.)

**New this pass**: Immich supports a declarative JSON config file
(`IMMICH_CONFIG_FILE` env var, mounted into the container) for OAuth
settings -- confirmed from `docs.immich.app/install/config-file/`'s real
schema. That's what makes `media-v2-05` literal instead of "go click
Administration > Settings in the browser."

## Decisions (resolved 2026-08-25)

- Zone: new `media_seg`, VLAN 80, `192.168.80.0/24`, gateway `192.168.80.1`.
- Storage: NFS, reusing legacy's existing `/nas-media/` exports.
- One combined stack (`media-stack-v2`), not split into two.
- Dedup: none -- Immich's built-in Duplicates Utility.
- Jellyfin SSO plugin: `jellyfin-plugin-authentik` (scottfridwin) --
  native OIDC-in-app, confirmed over `auth.mode: forwardAuth` (simpler to
  wire, but just an access gate in front of Jellyfin's own separate
  login, no real identity integration -- rejected for that reason).
- Additive, not destructive: legacy `media-stack` is never modified or
  destroyed by this plan.
- **Genuinely unknown, flagged rather than guessed**: the NAS's actual
  reachable address/zone for the new `media_seg -> NAS` firewall rule
  (legacy media-stack reaches it over plain LAN with no zone rule at
  all, since it predates the SDN model -- the exact NFS version/ports
  needed aren't in this repo anywhere). `media-v2-00`'s NAS rule is a
  placeholder for this reason, not a step failure.

---

## Step: media-v2-00-create-media-seg-zone

```yaml
id: media-v2-00-create-media-seg-zone
title: Create media_seg SDN zone (VLAN 80, 192.168.80.0/24)
depends_on: []

change: >
  Insert this exact block into terraform/lxc/network/pve.yaml
  immediately after the game_seg zone block (search for
  "game_seg — Game services" to find it), in the zones: section:

    # media_seg — Media services (VLAN 80, 192.168.80.0/24)
    media_seg:
      description: Media services — Jellyfin, Immich (media-stack-v2)
      type: sdn_vnet
      bridge: tvmedia
      firewall: false
      sdn:
        zone: tvmedia
        zone_type: vlan
        bridge: vmbr0
        nodes:
          - pve
        vnet: tvmedia
        vlan_tag: 80
        alias: pve media segment
        subnet: "192.168.80.0/24"
        gateway: "192.168.80.1"
        snat: false

  In the members section (search for "game_seg:" a second time, under
  the members/containers listing near "gaming-stack-lab (VMID 60010)"),
  insert:

    media_seg:
      description: Media services — Jellyfin + Immich, additive alongside legacy media-stack
      attachment: media_seg
      containers:
        - "media-stack-v2 (VMID 80010) — 192.168.80.10"

  In the policies: section, insert these two rules (copy the exact
  shape of the existing "edge_seg -> pentest_seg" and "infra_seg ->
  mgmt_seg ... Authentik" rules already in the file):

    - from: edge_seg
      to: media_seg
      protocol: tcp
      ports: [8096, 2283]
      description: Traefik to Jellyfin and Immich web UIs (media-stack-v2)
    - from: media_seg
      to: mgmt_seg
      protocol: tcp
      ports: [9443]
      description: media-stack-v2 (Jellyfin+Immich) to Authentik for OIDC

  Do NOT add a media_seg -> NAS rule yet -- the NAS's real address/zone
  and required NFS ports aren't established anywhere in this repo
  (legacy media-stack reaches it over flat LAN with no zone rule at
  all). Flag this gap in your report rather than guessing a subnet or
  port; it needs a real answer from the operator before that rule can be
  written.

scope:
  allowed_paths:
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Modifying any existing zone's subnet, gateway, or firewall rule"
    - "Guessing the NAS rule's subnet/ports -- report the gap instead"
    - "Running terragrunt apply -- plan only in this step"

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
depends_on: [media-v2-00-create-media-seg-zone]

change: >
  Create terraform/lxc/stacks/media-stack-v2/stack-request.yaml with
  exactly this content (one placeholder remains -- the Jellyfin image
  tag -- see the inline note; look up the current
  lscr.io/linuxserver/jellyfin stable tag before writing the file, do
  not leave the placeholder text in the actual file):

    stack_yaml:
      hostname: media-stack-v2
      ip_address: "192.168.80.10/24"
      gateway: "192.168.80.1"
      dns_server: "192.168.80.1"
      vmid: 80010
      cores: 6
      memory: 6144
      swap: 512
      rootfs_size: 8
      storage_profile: platform-default
      docker_storage_size: "30G"
      template_name: "debian-13.1-2-docker-template.tar.gz"
      tags:
        - docker
        - media
        - jellyfin
        - immich
      depends_on: []
      provides:
        - service: jellyfin
          port: 8096
          protocol: tcp
        - service: immich
          port: 2283
          protocol: tcp
      ansible_playbook: deploy-media-stack-v2
      deployment_tier: apps
      portainer_agent: false

    compose_requirements: |
      Five services in one compose file, container_name prefixed
      media-stack-v2-<service>, restart: unless-stopped on all five:

      jellyfin:
        image: lscr.io/linuxserver/jellyfin:<CURRENT STABLE TAG -- look
          this up now, do not ship :latest>
        environment:
          - PUID=1000
          - PGID=1000
          - TZ=Pacific/Auckland
          - JELLYFIN_PublishedServerUrl=https://jellyfin.${LAB_DOMAIN}
        volumes:
          - jellyfin-config:/config
          - /nas-media/video/movies:/movies
          - /nas-media/video/tv:/tv
          - /nas-media/music:/music
        ports: [8096:8096, 8920:8920, 7359:7359/udp, 1900:1900/udp]
        group_add: ["44", "104"]
        security_opt: [seccomp:unconfined]

      immich-server:
        image: ghcr.io/immich-app/immich-server:${IMMICH_VERSION:-release}
        environment:
          - IMMICH_CONFIG_FILE=/immich-config.json
        volumes:
          - /nas-media/immich-photos:/data
          - /etc/localtime:/etc/localtime:ro
          - ./immich-config.json:/immich-config.json:ro
        ports: [2283:2283]
        depends_on: [redis, database]

      immich-machine-learning:
        image: ghcr.io/immich-app/immich-machine-learning:${IMMICH_VERSION:-release}
        volumes: [model-cache:/cache]

      redis:
        image: docker.io/valkey/valkey:9@sha256:3acc0687f2a2e1091fae6450d7842dd658c941338cf0a873ddd9e14b9e4ea4dd

      database:
        image: ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:bcf63357191b76a916ae5eb93464d65c07511da41e3bf7a8416db519b40b1c23
        environment:
          - POSTGRES_PASSWORD=${DB_PASSWORD}
          - POSTGRES_USER=immich
          - POSTGRES_DB=immich
          - POSTGRES_INITDB_ARGS=--data-checksums
        volumes: [immich-db-data:/var/lib/postgresql/data]
        shm_size: 128mb

      top-level volumes: block declaring jellyfin-config, model-cache,
      immich-db-data as named Docker volumes.

      DB_PASSWORD must be a real SOPS-backed secret referenced as
      ${DB_PASSWORD} (env-file substitution, matching this repo's
      existing with-secrets pattern) -- never a literal password in
      this file or in compose_requirements' own text.

    compose_forbidden: |
      a custom top-level networks: block, exposing database/redis ports
      externally, a plain postgres/pgvector image instead of the pinned
      vectorchord fork, UPLOAD_LOCATION as a named volume instead of the
      /nas-media/immich-photos bind mount, changing the three Jellyfin
      NFS mount paths from what legacy already uses, an unpinned
      Jellyfin image tag, a literal database password anywhere in this
      file.

    contract_facts: |
      - Zone: media_seg (VLAN 80)
      - Nothing depends on this stack
      - Legacy media-stack (VMID 102) keeps running unaffected --
        additive, not migration-then-destroy
      - Prerequisite: /nas-media/immich-photos must already be
        NFS-mounted on the LXC before first compose up (manual, not
        IaC-managed, same gap as legacy's own NFS mounts)
      - OAuth/SSO configured in media-v2-04/05/06, not at first boot
      - Watch history brought across in media-v2-07, not at first boot
      - Implementation files: terraform/lxc/stacks/media-stack-v2/
        stack.yaml, terragrunt.hcl, docker-compose.yml,
        STACK_CONTRACT.md (all new), plus
        terraform/lxc/ansible/playbooks/deploy-media-stack-v2.yml (new)
        -- none of these exist yet.

scope:
  allowed_paths:
    - terraform/lxc/stacks/media-stack-v2/stack-request.yaml
  forbidden_actions:
    - "Running scaffold-stack.sh -- that's media-v2-02"
    - "Any terragrunt or provision.sh command"
    - "Mounting or modifying the NFS export itself"
    - "Touching legacy media-stack (VMID 102) in any way"
    - "Writing a literal database password into the file"

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
  - id: no-hardcoded-password
    cmd: "! grep -qE 'POSTGRES_PASSWORD=[^$]' terraform/lxc/stacks/media-stack-v2/stack-request.yaml"
    expect: "exit 0 (i.e. no literal password found)"
    critical: true
```

## Operator step: media-v2-02-scaffold

Not a step block -- this is the operator running a command directly, not
something to hand to `implement-step`. Depends on `media-v2-01-stack-request`
(the `stack-request.yaml` it needs as input). Steps after this one
(`media-v2-03` onward) depend on it having landed.

Run `terraform/lxc/scaffold-stack.sh media-stack-v2` directly. If it fails
partway, don't hand-edit any of the five generated files -- check which
validator failed and re-run instead.

## Step: media-v2-03-edge-yaml

```yaml
id: media-v2-03-edge-yaml
title: Author edge.yaml with both routes (jellyfin, immich)
depends_on: [media-v2-02-scaffold]

change: >
  Create terraform/lxc/stacks/media-stack-v2/edge.yaml with exactly this
  content:

    apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
    kind: EdgeManifest
    metadata:
      name: media-stack-v2-edge
      stack: media-stack-v2
      annotations:
        repo.auth.oidc.client_id_env: JELLYFIN_OAUTH_CLIENT_ID
        repo.auth.oidc.client_secret_env: JELLYFIN_OAUTH_CLIENT_SECRET
    spec:
      routes:
        - name: jellyfin
          host: jellyfin.${LAB_DOMAIN}
          backend:
            type: url
            url: http://192.168.80.10:8096
          dns:
            enabled: true
            target: ${LAB_IP_PROXY}
            ttl: 5m
          tls:
            resolver: letsencrypt
          auth:
            mode: oidc
        - name: immich
          host: immich.${LAB_DOMAIN}
          backend:
            type: url
            url: http://192.168.80.10:2283
          dns:
            enabled: true
            target: ${LAB_IP_PROXY}
            ttl: 5m
          tls:
            resolver: letsencrypt
          auth:
            mode: oidc

  Note the metadata.annotations block only names Jellyfin's env vars --
  reading discover-authentik-edge.py's _build_route_intents shows the
  per-route app/provider naming is keyed by (stack, route), not by this
  annotation, so both routes still get independent Authentik clients;
  the annotation is documentation-consistency only, matching every
  other stack's edge.yaml in this repo. Immich's client_id/secret env
  var names (IMMICH_OAUTH_CLIENT_ID/SECRET) are set directly in
  media-v2-04's whitelist entry instead.

scope:
  allowed_paths:
    - terraform/lxc/stacks/media-stack-v2/edge.yaml
  forbidden_actions:
    - "Modifying any other stack's edge.yaml"
    - "Editing discover-authentik-edge.py or reconcile-authentik-edge.py -- that's media-v2-04"

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

Touches a shared script 6 live integrations depend on -- the gate is
what makes this safe to hand to a local model at all. If it fails, stop;
do not apply.

```yaml
id: media-v2-04-extend-oidc-whitelist
title: Add jellyfin/immich routes to discover-authentik-edge.py's whitelist
depends_on: [media-v2-03-edge-yaml]

change: >
  In terraform/lxc/discover-authentik-edge.py, find this exact
  dictionary (search for "OIDC_ROUTE_CLIENT_IDS"):

    OIDC_ROUTE_CLIENT_IDS: dict[tuple[str, str], tuple[str, str]] = {
        ("harbor-stack", "harbor"): ("HARBOR_OIDC_CLIENT_ID", "harbor"),
        ("monitoring-stack", "grafana"): ("GRAFANA_OAUTH_CLIENT_ID", "grafana"),
        ("portainer-stack", "portainer"): ("PORTAINER_OAUTH_CLIENT_ID", "portainer"),
        ("technitium-stack", "technitium"): ("TECHNITIUM_OIDC_CLIENT_ID", "technitium"),
        ("ai-services-stack", "openwebui"): ("OPENWEBUI_OIDC_CLIENT_ID", "openwebui"),
        ("opensearch-stack", "dashboards"): ("OPENSEARCH_OIDC_CLIENT_ID", "opensearch-dashboards"),
    }

  Add exactly these two lines before the closing brace, changing
  nothing else in the dict:

        ("media-stack-v2", "jellyfin"): ("JELLYFIN_OAUTH_CLIENT_ID", "jellyfin"),
        ("media-stack-v2", "immich"): ("IMMICH_OAUTH_CLIENT_ID", "immich"),

  Do the equivalent for OIDC_ROUTE_CLIENT_SECRETS (same file, right
  below): add
        ("media-stack-v2", "jellyfin"): "JELLYFIN_OAUTH_CLIENT_SECRET",
        ("media-stack-v2", "immich"): "IMMICH_OAUTH_CLIENT_SECRET",

  Then in _oidc_redirect_uris (search for that function name), add
  these two branches immediately before the final "return ()" line:

      if _oidc_route_key(intent) == ("media-stack-v2", "jellyfin"):
          return (f"{base_url}/authentik/callback",)
      if _oidc_route_key(intent) == ("media-stack-v2", "immich"):
          return (f"{base_url}/auth/login",)

  Change nothing else in the file. Immich's mobile deep-link redirect
  (app.immich:///oauth-callback) is set in Immich's own config file
  (media-v2-05), not here.

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

## Step: media-v2-05-immich-oauth-config

```yaml
id: media-v2-05-immich-oauth-config
title: Add Immich's OAuth config file, templated from the reconciled Authentik client
depends_on: [media-v2-04-extend-oidc-whitelist]

change: >
  Create terraform/lxc/ansible/files/media-stack-v2/immich-config.json.j2
  (Jinja2 template, rendered by the deploy playbook, not committed with
  real values) with exactly this content:

    {
      "oauth": {
        "enabled": true,
        "issuerUrl": "https://{{ lab_fqdn_authentik }}/application/o/immich/",
        "clientId": "{{ lookup('env', 'IMMICH_OAUTH_CLIENT_ID') }}",
        "clientSecret": "{{ lookup('env', 'IMMICH_OAUTH_CLIENT_SECRET') }}",
        "scope": "openid email profile",
        "mobileOverrideEnabled": true,
        "mobileRedirectUri": "app.immich:///oauth-callback",
        "autoRegister": true,
        "buttonText": "Login with Authentik"
      }
    }

  This is the real, declarative config-file mechanism Immich supports
  (IMMICH_CONFIG_FILE env var, confirmed from docs.immich.app/install/
  config-file/'s actual schema) -- not a manual Administration Settings
  click-through. Add a task to deploy-media-stack-v2.yml that templates
  this file to the stack's compose directory as immich-config.json
  (matching stack-request.yaml's compose_requirements, which already
  bind-mounts ./immich-config.json:/immich-config.json:ro and sets
  IMMICH_CONFIG_FILE=/immich-config.json).

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/media-stack-v2/immich-config.json.j2
    - terraform/lxc/ansible/playbooks/deploy-media-stack-v2.yml
  forbidden_actions:
    - "Writing real client_id/secret values directly into the .j2 template or committing a rendered immich-config.json with real values"
    - "Disabling Immich's local-password login -- oauth.enabled: true doesn't remove it; keep both available until OIDC login is verified"

gates:
  - id: template-parses-as-valid-json-once-rendered
    cmd: "python3 -c \"import json; json.loads(open('terraform/lxc/ansible/files/media-stack-v2/immich-config.json.j2').read().replace('{{ lab_fqdn_authentik }}','x').replace(\\\"{{ lookup('env', 'IMMICH_OAUTH_CLIENT_ID') }}\\\",'x').replace(\\\"{{ lookup('env', 'IMMICH_OAUTH_CLIENT_SECRET') }}\\\",'x'))\""
    expect: "exit 0"
    critical: true
  - id: no-real-secret-committed
    cmd: "grep '\"clientSecret\"' terraform/lxc/ansible/files/media-stack-v2/immich-config.json.j2 | grep -q '{{'"
    expect: "exit 0 (i.e. the clientSecret line still contains a Jinja placeholder, not a real value)"
    critical: true
```

## Operator step: media-v2-06-jellyfin-sso-plugin

Not a step block -- genuinely UI-only, confirmed by checking the plugin's
own docs, which describe no config-file or API path. Depends on
`media-v2-04-extend-oidc-whitelist` having landed (its output values are
what get typed in below).

In Jellyfin's admin dashboard (Dashboard > Plugins > Repositories), add
repository URL exactly:
<https://scottfridwin.github.io/jellyfin-plugin-authentik/manifest.json>
Then Dashboard > Plugins > Catalog, install "Authentik SSO", restart
Jellyfin when prompted. Then Dashboard > Plugins > Authentik SSO, fill in
exactly these three fields (values are the reconciled output from
media-v2-04's Authentik client, already known at this point -- no
guessing): Authentik URL = https://{{ lab_fqdn_authentik }}, Client ID =
value of JELLYFIN_OAUTH_CLIENT_ID, Client Secret = value of
JELLYFIN_OAUTH_CLIENT_SECRET. Save. In Authentik itself, confirm the
jellyfin route's OAuth2 provider has redirect URI
`https://jellyfin.${LAB_DOMAIN}/authentik/callback` and scopes
openid/profile/email (already set correctly by media-v2-04's redirect-URI
branch and reconcile-authentik-edge.py's default scope list -- this is a
confirmation, not a new decision). Keep Jellyfin's existing
local-password login enabled until SSO login is verified working.

Confirm with: `curl -s http://192.168.80.10:8096/Plugins` should list a
plugin with "Authentik" in its name.

## Step: media-v2-07-bring-across-existing-users

Real user data. Every command is literal, but the final gate is a
human check, not a script -- do not skip that just because the rest is
mechanical.

```yaml
id: media-v2-07-bring-across-existing-users
title: Bring existing Jellyfin users and watch history into media-stack-v2
depends_on: [media-v2-02-scaffold]

change: >
  Run exactly this sequence:

    LEGACY_TAG=$(docker inspect --format '{{.Config.Image}}' jellyfin)
    echo "Legacy tag: $LEGACY_TAG -- confirm media-stack-v2's jellyfin service uses this exact tag before continuing"
    docker stop media-stack-v2-jellyfin
    docker run --rm -v jellyfin-config:/dest -v /opt/media-stack/config/jellyfin:/src:ro alpine \
      sh -c "cp -a /src/. /dest/"
    docker start media-stack-v2-jellyfin

  (Adjust the legacy source path if it differs from
  /opt/media-stack/config/jellyfin -- confirm the real bind-mount source
  path from media-stack's own compose/inventory before running the copy,
  do not assume.) This is a copy, not a move -- legacy's own /config is
  never written to. After the copy, log in to media-stack-v2's Jellyfin
  as an existing user with their existing password and manually confirm
  watch history/continue-watching matches legacy. Only after that human
  check passes should media-v2-06 (SSO plugin) or a Jellyfin image
  upgrade be layered on. Legacy media-stack keeps running throughout and
  after -- this step never turns anything off on it.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Any write to legacy media-stack's /config -- read/copy only, forever"
    - "Stopping, restarting, or otherwise touching legacy's jellyfin container"
    - "Upgrading media-stack-v2's Jellyfin image tag before the config copy is verified"
    - "Reporting this step done based on the copy succeeding alone -- the human login/history check is mandatory"

gates:
  - id: image-versions-matched-before-copy
    cmd: "test \"$(docker inspect --format '{{.Config.Image}}' jellyfin)\" = \"$(docker inspect --format '{{.Config.Image}}' media-stack-v2-jellyfin)\""
    expect: "exit 0"
    critical: true
  - id: legacy-still-running-unmodified
    cmd: "test \"$(docker inspect --format '{{.State.Status}}' jellyfin)\" = running"
    expect: "exit 0"
    critical: true
  - id: existing-user-can-login-with-history-intact
    cmd: "n/a -- human verification: log in as an existing user on media-stack-v2, confirm watch history/continue-watching matches legacy"
    expect: "operator confirms match"
    critical: true
```

---

## Not covered by this plan

- Confirming the candidate IP/VMID (`192.168.80.10`/`80010`) are
  actually free, and the real legacy Jellyfin config bind-mount source
  path (assumed `/opt/media-stack/config/jellyfin` in media-v2-07 --
  confirm before running).
- The `media_seg -> NAS` firewall rule -- genuinely unknown NAS
  address/NFS version, flagged in media-v2-00 rather than guessed.
- `terragrunt apply` for the zone and the stack,
  `provision.sh --stack media-stack-v2`, and health-check validation --
  real infrastructure steps, stay manual/operator-run.
- Hardware transcoding passthrough for media-stack-v2's Jellyfin.
- Backup strategy for the photo library, Postgres data, and Jellyfin
  config.
- **Retiring legacy `media-stack`.** Not in this plan at all -- the
  operator's own future call, with its own fresh approval whenever (if
  ever) it's made.
