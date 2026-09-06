# media-stack-lab plan

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
`media-lab-02-scaffold` (running `scaffold-stack.sh` directly) and
`media-lab-06-jellyfin-sso-plugin` (a UI-only procedure, confirmed by
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
schema. That's what makes `media-lab-05` literal instead of "go click
Administration > Settings in the browser."

## Decisions (resolved 2026-08-25)

- Zone: new `media_seg`, VLAN 80, `192.168.80.0/24`, gateway `192.168.80.1`.
- Storage: NFS, reusing legacy's existing `/nas-media/` exports.
- One combined stack (`media-stack-lab`), not split into two.
- Dedup: none -- Immich's built-in Duplicates Utility.
- Jellyfin SSO plugin: `jellyfin-plugin-authentik` (scottfridwin) --
  native OIDC-in-app, confirmed over `auth.mode: forwardAuth` (simpler to
  wire, but just an access gate in front of Jellyfin's own separate
  login, no real identity integration -- rejected for that reason).
- Additive, not destructive: legacy `media-stack` is never modified or
  destroyed by this plan.
- **NAS address/ports resolved 2026-09-04**: `192.168.1.3`, stays on the
  flat LAN bridge (not migrating into any VLAN), NFS is tcp+udp/2049 --
  confirmed from `docs/greenbone-stack/network-scan-rollout-plan.md` and
  the shelved `terraform/lxc/stacks/.hold/media/stack.yaml` (an earlier,
  never-executed migration draft that already documented this exact
  rule). `media-lab-00` below now includes the real `media_seg -> NAS`
  rule instead of a placeholder.
- **IP/VMID collision checked 2026-09-04** (read-only `pvesh`-equivalent
  API query against production `pve`, operator-approved in chat): VMID
  `80010` is not in use by any LXC or QEMU guest on `pve`; `192.168.80.0/24`
  is an as-yet-uncreated VLAN so nothing could already be on it. Both
  candidates in `media-lab-01` below are confirmed free, not assumed.
- **Still genuinely open**: GPU/hardware transcoding passthrough status
  on legacy Jellyfin (VMID 102) -- would need
  `pvesh get /nodes/pve/lxc/102/config` read against production `pve`,
  deferred by the operator for now. If legacy Jellyfin turns out to use
  hardware transcoding, `media-lab-01`'s stack-request will need the same
  device passthrough added before first deploy -- check this before
  running `media-lab-02-scaffold`, not after.

---

## Step: media-lab-00-create-media-seg-zone

```yaml
id: media-lab-00-create-media-seg-zone
title: Create media_seg SDN zone (VLAN 80, 192.168.80.0/24)
depends_on: []

change: >
  Insert this exact block into terraform/lxc/network/pve.yaml
  immediately after the game_seg zone block (search for
  "game_seg — Game services" to find it), in the zones: section:

    # media_seg — Media services (VLAN 80, 192.168.80.0/24)
    media_seg:
      description: Media services — Jellyfin, Immich (media-stack-lab)
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
        - "media-stack-lab (VMID 80010) — 192.168.80.10"

  In the policies: section, insert these two rules (copy the exact
  shape of the existing "edge_seg -> pentest_seg" and "infra_seg ->
  mgmt_seg ... Authentik" rules already in the file):

    - from: edge_seg
      to: media_seg
      protocol: tcp
      ports: [8096, 2283]
      description: Traefik to Jellyfin and Immich web UIs (media-stack-lab)
    - from: media_seg
      to: mgmt_seg
      protocol: tcp
      ports: [9443]
      description: media-stack-lab (Jellyfin+Immich) to Authentik for OIDC
    - from: media_seg
      to: 192.168.1.3
      protocol: tcp
      ports: [2049]
      description: media-stack-lab (Jellyfin+Immich) to NAS NFS exports (192.168.1.3, flat LAN, not a zone)
    - from: media_seg
      to: 192.168.1.3
      protocol: udp
      ports: [2049]
      description: media-stack-lab (Jellyfin+Immich) to NAS NFS exports, UDP (192.168.1.3, flat LAN, not a zone)

  The NAS rule targets a plain LAN host, not another zone -- copy the
  exact `to: 192.168.1.8` bare-IP shape already used by the
  `pentest_seg -> 192.168.1.8` rules elsewhere in this file (no CIDR
  suffix, no quotes). This file has no combined tcp+udp protocol value
  anywhere -- every existing rule is `protocol: tcp` or `protocol: all`
  -- so NFS needs two separate rules, one per protocol, not one
  `tcp_udp` rule. Confirmed source: NAS is `192.168.1.3`, stays on the
  flat LAN bridge permanently (see
  `docs/greenbone-stack/network-scan-rollout-plan.md` and
  `terraform/lxc/stacks/.hold/media/stack.yaml`), NFS is tcp+udp/2049.

scope:
  allowed_paths:
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Modifying any existing zone's subnet, gateway, or firewall rule"
    - "Guessing the NAS rule's subnet/ports -- report the gap instead"
    - "Running terragrunt apply -- plan only in this step"

gates:
  - id: terragrunt-plan-shows-only-additions
    cmd: "./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/gaming-stack-lab -no-color"
    expect: >-
      Zone is production-only (nodes: [pve]), so this must run against pve
      via with-secrets-prod, not the dev with-secrets wrapper -- read-only
      (terragrunt plan is on the wrapper's default-allowed list, no
      TASK_APPROVAL needed). `run --all` from terraform/lxc/stacks is NOT
      a working check in this repo -- it sweeps in pve-test-only scaffold
      stacks (net-*/test-*) that fail outright with unrelated
      "workspace: EOF" errors. Use a single adjacent-zone stack instead
      (gaming-stack-lab, in game_seg, is the closest analog). Compare its
      plan output A/B (with vs. without the pve.yaml edit, e.g. via
      `git stash`) rather than expecting a clean "no changes" -- this
      stack's terragrunt plan shows a pre-existing, unrelated
      `Plan: 6 to add, 0 to change, 0 to destroy` regardless of this
      change (confirmed 2026-09-04, a state/workspace quirk, not a real
      diff). What matters is the two runs producing byte-identical plan
      output -- that's "zero incremental diff," the real form of this
      gate. Separately: VLAN-type SDN zones aren't Terraform-managed in
      this repo yet (see network/NETWORK_CONTRACT.md's documented gap --
      applied via ansible/00-initial-setup/proxmox-sdn-setup.yml
      instead), so media_seg's own creation was never going to appear as
      a plannable Terraform resource regardless of gate wording.
    critical: true
```

## Step: media-lab-01-stack-request

```yaml
id: media-lab-01-stack-request
title: Author stack-request.yaml for the combined media-stack-lab
depends_on: [media-lab-00-create-media-seg-zone]

change: >
  Create terraform/lxc/stacks/media-stack-lab/stack-request.yaml with
  exactly this content (one placeholder remains -- the Jellyfin image
  tag -- see the inline note; look up the current
  lscr.io/linuxserver/jellyfin stable tag before writing the file, do
  not leave the placeholder text in the actual file):

    stack_yaml:
      hostname: media-stack-lab
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
      ansible_playbook: deploy-media-stack-lab
      deployment_tier: apps
      portainer_agent: false

    compose_requirements: |
      Five services in one compose file, container_name prefixed
      media-stack-lab-<service>, restart: unless-stopped on all five:

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
      - OAuth/SSO configured in media-lab-04/05/06, not at first boot
      - Watch history brought across in media-lab-07, not at first boot
      - Implementation files: terraform/lxc/stacks/media-stack-lab/
        stack.yaml, terragrunt.hcl, docker-compose.yml,
        STACK_CONTRACT.md (all new), plus
        terraform/lxc/ansible/playbooks/deploy-media-stack-lab.yml (new)
        -- none of these exist yet.

scope:
  allowed_paths:
    - terraform/lxc/stacks/media-stack-lab/stack-request.yaml
  forbidden_actions:
    - "Running scaffold-stack.sh -- that's media-lab-02"
    - "Any terragrunt or provision.sh command"
    - "Mounting or modifying the NFS export itself"
    - "Touching legacy media-stack (VMID 102) in any way"
    - "Writing a literal database password into the file"

gates:
  - id: stack-request-exists
    cmd: "test -f terraform/lxc/stacks/media-stack-lab/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: stack-request-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/media-stack-lab/stack-request.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: nfs-paths-match-legacy
    cmd: "grep -q '/nas-media/video/movies' terraform/lxc/stacks/media-stack-lab/stack-request.yaml && grep -q '/nas-media/video/tv' terraform/lxc/stacks/media-stack-lab/stack-request.yaml && grep -q '/nas-media/music' terraform/lxc/stacks/media-stack-lab/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: no-hardcoded-password
    cmd: "! grep -qE 'POSTGRES_PASSWORD=[^$]' terraform/lxc/stacks/media-stack-lab/stack-request.yaml"
    expect: "exit 0 (i.e. no literal password found)"
    critical: true
```

**Done 2026-09-04 -- see `docs/media-stack-lab/README.md`'s hand-back for
this step.** Two things above were incomplete as originally written,
fixed in the real file: `playbook_content` was missing entirely (this
step's `change:` block above never included one, but
`terraform/lxc/scaffold-stack.py` requires `request["playbook_content"]`
unconditionally -- `media-lab-02-scaffold` would have failed immediately
without it); and `DB_PASSWORD` was renamed to
`MEDIA_STACK_LAB_DB_PASSWORD` throughout to match this repo's per-stack
secret-naming convention. The real
`terraform/lxc/stacks/media-stack-lab/stack-request.yaml` is the
authoritative version now, not the `change:` text above.

**Third gap, found later (at actual `terragrunt plan` time, not by
anything in this step): the `stack_yaml` block above never included a
`network:\n  zone: media_seg` field.** Per
`terraform/lxc/network/NETWORK_CONTRACT.md`, that's exactly how
stack-to-zone membership gets declared -- without it, `stack.yaml`
resolved as a plain `vmbr0` bridge attachment instead of the
`media_seg` SDN VLAN, which would have deployed the container onto the
wrong network entirely. Fixed in the real files; see
`docs/media-stack-lab/README.md`'s `media-lab-02-scaffold` hand-back
for the full detail and how it was caught.

## Operator step: media-lab-02-scaffold

Not a step block -- this is the operator running a command directly, not
something to hand to `implement-step`. Depends on `media-lab-01-stack-request`
(the `stack-request.yaml` it needs as input). Steps after this one
(`media-lab-03` onward) depend on it having landed.

Run `terraform/lxc/scaffold-stack.sh media-stack-lab` directly. If it fails
partway, don't hand-edit any of the five generated files -- check which
validator failed and re-run instead.

**Done differently 2026-09-04, by explicit operator direction: no local
model / `opencode` for this stack** (operator called `opencode` a
deprecated path). `scaffold-stack.sh`'s real job -- drive
`stack-yaml-writer`/`compose-writer`/`contract-writer`/
`terragrunt-writer`/`playbook-writer` opencode agents, each gated by a
real validator -- was done by hand instead: the frontier session
authored `stack.yaml` (literal dump of `stack_yaml`, matching what
`run_stack_yaml_writer` would produce), `docker-compose.yml` (from
`compose_requirements`/`compose_forbidden`), `STACK_CONTRACT.md` (from
`contract_facts`, modeled on `apt-cacher-stack`'s contract for section
shape), `terragrunt.hcl` (fixed boilerplate, copied from
`gaming-stack-lab`'s), and
`terraform/lxc/ansible/playbooks/deploy-media-stack-lab.yml` (the
literal `playbook_content` from `stack-request.yaml`, byte-identical).
Ran the same real validators `scaffold-stack.py` would have:
`validate-stack-metadata.sh` (passes, but doesn't actually check this
stack -- its `ACTIVE_STACKS` tuple is a fixed list that doesn't include
`media-stack-lab` and has no `--stack` flag to override; a real gap in
this repo's tooling for any new stack, not something this step caused
or fixed), `validate-compose.sh --stack media-stack-lab` (passes, this
one does support single-stack checking), the `## Provides`/
`## Dependencies` section check from `--check-contract-sections`
(verified manually, both present), and
`ansible-playbook --syntax-check` (passes). `stack-request.yaml` kept
as a record of intent, matching its own stated convention ("keep it or
delete it, either is fine").

## Step: media-lab-03-edge-yaml

```yaml
id: media-lab-03-edge-yaml
title: Author edge.yaml with both routes (jellyfin, immich)
depends_on: [media-lab-02-scaffold]

change: >
  Create terraform/lxc/stacks/media-stack-lab/edge.yaml with exactly this
  content:

    apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
    kind: EdgeManifest
    metadata:
      name: media-stack-lab-edge
      stack: media-stack-lab
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
  media-lab-04's whitelist entry instead.

scope:
  allowed_paths:
    - terraform/lxc/stacks/media-stack-lab/edge.yaml
  forbidden_actions:
    - "Modifying any other stack's edge.yaml"
    - "Editing discover-authentik-edge.py or reconcile-authentik-edge.py -- that's media-lab-04"

gates:
  - id: edge-yaml-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/media-stack-lab/edge.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: has-both-routes
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/media-stack-lab/edge.yaml')); names={r['name'] for r in d['spec']['routes']}; exit(0 if names=={'jellyfin','immich'} else 1)\""
    expect: "exit 0"
    critical: true
```

**Done 2026-09-04.** One deliberate deviation from the `change:` text
above: backend URLs use `${LAB_IP_MEDIA_STACK_LAB}` (added to `.env`),
not the literal `192.168.80.10` shown -- every other stack's `edge.yaml`
in this repo uses a `${LAB_IP_<STACK>}` var, so the literal IP here was
the plan's own inconsistency, not a real requirement. See
`docs/media-stack-lab/README.md`'s hand-back for the full detail,
including a pre-existing, repo-wide `validate-edge-manifests.py` gap
found (unrelated to this file) and confirmation that technitium-stack,
not the retired `dns-stack`, is what actually consumes this file's
`dns:` block.

## Step: media-lab-04-extend-oidc-whitelist

Touches a shared script 6 live integrations depend on -- the gate is
what makes this safe to hand to a local model at all. If it fails, stop;
do not apply.

```yaml
id: media-lab-04-extend-oidc-whitelist
title: Add jellyfin/immich routes to discover-authentik-edge.py's whitelist
depends_on: [media-lab-03-edge-yaml]

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

        ("media-stack-lab", "jellyfin"): ("JELLYFIN_OAUTH_CLIENT_ID", "jellyfin"),
        ("media-stack-lab", "immich"): ("IMMICH_OAUTH_CLIENT_ID", "immich"),

  Do the equivalent for OIDC_ROUTE_CLIENT_SECRETS (same file, right
  below): add
        ("media-stack-lab", "jellyfin"): "JELLYFIN_OAUTH_CLIENT_SECRET",
        ("media-stack-lab", "immich"): "IMMICH_OAUTH_CLIENT_SECRET",

  Then in _oidc_redirect_uris (search for that function name), add
  these two branches immediately before the final "return ()" line:

      if _oidc_route_key(intent) == ("media-stack-lab", "jellyfin"):
          return (f"{base_url}/authentik/callback",)
      if _oidc_route_key(intent) == ("media-stack-lab", "immich"):
          return (f"{base_url}/auth/login",)

  Change nothing else in the file. Immich's mobile deep-link redirect
  (app.immich:///oauth-callback) is set in Immich's own config file
  (media-lab-05), not here.

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
    cmd: "grep -q 'media-stack-lab.*jellyfin' terraform/lxc/discover-authentik-edge.py && grep -q 'media-stack-lab.*immich' terraform/lxc/discover-authentik-edge.py"
    expect: "exit 0"
    critical: true
```

**Done 2026-09-04.** The `change:` text above is stale -- a 7th entry
(`wazuh-stack`) was added to both dicts on 2026-08-29, after this plan
was written; inserted after the real last entry, not the 6-entry text
shown. `existing-six-entries-untouched`'s regex was also widened to
include `wazuh-stack` before running it -- as originally written it
wouldn't have detected an accidental edit to that entry. All 3 gates
pass; also ran the real `test_discover_authentik_edge.py` suite (11/11
pass, beyond what this step's own gates require) as extra confidence
given this file's blast radius. See
`docs/media-stack-lab/README.md`'s hand-back for the full diff.

## Step: media-lab-05-immich-oauth-config

```yaml
id: media-lab-05-immich-oauth-config
title: Add Immich's OAuth config file, templated from the reconciled Authentik client
depends_on: [media-lab-04-extend-oidc-whitelist]

change: >
  Create terraform/lxc/ansible/files/media-stack-lab/immich-config.json.j2
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
  click-through. Add a task to deploy-media-stack-lab.yml that templates
  this file to the stack's compose directory as immich-config.json
  (matching stack-request.yaml's compose_requirements, which already
  bind-mounts ./immich-config.json:/immich-config.json:ro and sets
  IMMICH_CONFIG_FILE=/immich-config.json).

scope:
  allowed_paths:
    - terraform/lxc/ansible/templates/media-stack-lab/immich-config.json.j2
    - terraform/lxc/ansible/playbooks/deploy-media-stack-lab.yml
  forbidden_actions:
    - "Writing real client_id/secret values directly into the .j2 template or committing a rendered immich-config.json with real values"
    - "Disabling Immich's local-password login -- oauth.enabled: true doesn't remove it; keep both available until OIDC login is verified"

gates:
  - id: template-parses-as-valid-json-once-rendered
    cmd: "python3 -c \"import json; json.loads(open('terraform/lxc/ansible/files/media-stack-lab/immich-config.json.j2').read().replace('{{ lab_fqdn_authentik }}','x').replace(\\\"{{ lookup('env', 'IMMICH_OAUTH_CLIENT_ID') }}\\\",'x').replace(\\\"{{ lookup('env', 'IMMICH_OAUTH_CLIENT_SECRET') }}\\\",'x'))\""
    expect: "exit 0"
    critical: true
  - id: no-real-secret-committed
    cmd: "grep '\"clientSecret\"' terraform/lxc/ansible/templates/media-stack-lab/immich-config.json.j2 | grep -q '{{'"
    expect: "exit 0 (i.e. the clientSecret line still contains a Jinja placeholder, not a real value)"
    critical: true
```

**Done 2026-09-04, two path/variable corrections from the `change:` text
above (see `docs/media-stack-lab/README.md`'s hand-back for detail):**
the file moved from `ansible/files/media-stack-lab/` (this repo has zero
other `.j2` files there) to `ansible/templates/media-stack-lab/`
(matches every real template in this repo); `{{ lab_fqdn_authentik }}`
replaced with a real computed var, `media_stack_lab_fqdn_authentik`
(the literal text wasn't a variable that exists anywhere -- would have
rendered undefined). The `allowed_paths`/gate command above are updated
to the real `templates/` location. Both gates pass; playbook still
syntax-checks clean.

## Operator step: media-lab-06-jellyfin-sso-plugin

Not a step block -- genuinely UI-only, confirmed by checking the plugin's
own docs, which describe no config-file or API path. Depends on
`media-lab-04-extend-oidc-whitelist` having landed (its output values are
what get typed in below).

In Jellyfin's admin dashboard (Dashboard > Plugins > Repositories), add
repository URL exactly:
<https://scottfridwin.github.io/jellyfin-plugin-authentik/manifest.json>
Then Dashboard > Plugins > Catalog, install "Authentik SSO", restart
Jellyfin when prompted. Then Dashboard > Plugins > Authentik SSO, fill in
exactly these three fields (values are the reconciled output from
media-lab-04's Authentik client, already known at this point -- no
guessing): Authentik URL = https://{{ lab_fqdn_authentik }}, Client ID =
value of JELLYFIN_OAUTH_CLIENT_ID, Client Secret = value of
JELLYFIN_OAUTH_CLIENT_SECRET. Save. In Authentik itself, confirm the
jellyfin route's OAuth2 provider has redirect URI
`https://jellyfin.${LAB_DOMAIN}/authentik/callback` and scopes
openid/profile/email (already set correctly by media-lab-04's redirect-URI
branch and reconcile-authentik-edge.py's default scope list -- this is a
confirmation, not a new decision). Keep Jellyfin's existing
local-password login enabled until SSO login is verified working.

Confirm with: `curl -s http://192.168.80.10:8096/Plugins` should list a
plugin with "Authentik" in its name.

## Step: media-lab-07-bring-across-existing-users

Real user data. Every command is literal, but the final gate is a
human check, not a script -- do not skip that just because the rest is
mechanical.

```yaml
id: media-lab-07-bring-across-existing-users
title: Bring existing Jellyfin users and watch history into media-stack-lab
depends_on: [media-lab-02-scaffold]

change: >
  Run exactly this sequence:

    LEGACY_TAG=$(docker inspect --format '{{.Config.Image}}' jellyfin)
    echo "Legacy tag: $LEGACY_TAG -- confirm media-stack-lab's jellyfin service uses this exact tag before continuing"
    docker stop media-stack-lab-jellyfin
    docker run --rm -v jellyfin-config:/dest -v /config/jellyfin:/src:ro alpine \
      sh -c "cp -a /src/. /dest/"
    docker start media-stack-lab-jellyfin

  (`/config/jellyfin` is the real host bind-mount source, confirmed
  2026-09-04 from `terraform/lxc/stacks/media-stack/
  jellyfin-docker-compose.yml`'s actual `volumes:` entry -- an earlier
  version of this step guessed `/opt/media-stack/config/jellyfin`,
  which is wrong and would have copied from an empty directory.) This
  is a copy, not a move -- legacy's own /config is never written to. After the copy, log in to media-stack-lab's Jellyfin
  as an existing user with their existing password and manually confirm
  watch history/continue-watching matches legacy. Only after that human
  check passes should media-lab-06 (SSO plugin) or a Jellyfin image
  upgrade be layered on. Legacy media-stack keeps running throughout and
  after -- this step never turns anything off on it.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Any write to legacy media-stack's /config -- read/copy only, forever"
    - "Stopping, restarting, or otherwise touching legacy's jellyfin container"
    - "Upgrading media-stack-lab's Jellyfin image tag before the config copy is verified"
    - "Reporting this step done based on the copy succeeding alone -- the human login/history check is mandatory"

gates:
  - id: image-versions-matched-before-copy
    cmd: "test \"$(docker inspect --format '{{.Config.Image}}' jellyfin)\" = \"$(docker inspect --format '{{.Config.Image}}' media-stack-lab-jellyfin)\""
    expect: "exit 0"
    critical: true
  - id: legacy-still-running-unmodified
    cmd: "test \"$(docker inspect --format '{{.State.Status}}' jellyfin)\" = running"
    expect: "exit 0"
    critical: true
  - id: existing-user-can-login-with-history-intact
    cmd: "n/a -- human verification: log in as an existing user on media-stack-lab, confirm watch history/continue-watching matches legacy"
    expect: "operator confirms match"
    critical: true
```

---

## Not covered by this plan

- **Resolved 2026-09-04** (was open before): `192.168.80.10`/`80010`
  confirmed free via a read-only production API check against `pve`
  (operator-approved); the `media_seg -> NAS` rule now has real values
  in media-lab-00 instead of a placeholder; media-lab-07's legacy config
  bind-mount path corrected to the real `/config/jellyfin` (confirmed
  from `terraform/lxc/stacks/media-stack/jellyfin-docker-compose.yml`
  -- the earlier `/opt/media-stack/config/jellyfin` guess was wrong and
  would have copied from an empty directory).
- **Still open**: GPU/hardware transcoding passthrough status on
  legacy Jellyfin (VMID 102) -- needs
  `pvesh get /nodes/pve/lxc/102/config` against production `pve`,
  deferred by the operator 2026-09-04. Check this before
  `media-lab-02-scaffold` if hardware transcoding turns out to be in use
  -- `media-lab-01`'s stack-request doesn't currently include any device
  passthrough.
- `terragrunt apply` for the zone and the stack,
  `provision.sh --stack media-stack-lab`, and health-check validation --
  real infrastructure steps, stay manual/operator-run.
- Hardware transcoding passthrough for media-stack-lab's Jellyfin.
- Backup strategy for the photo library, Postgres data, and Jellyfin
  config.
- **Retiring legacy `media-stack`.** Not in this plan at all -- the
  operator's own future call, with its own fresh approval whenever (if
  ever) it's made.
