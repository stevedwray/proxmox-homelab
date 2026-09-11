# torrent-stack-modernization — plan

Replaces legacy `torrent-stack` (VMID 100, flat LAN `192.168.1.5`,
unauthenticated, untracked config) with a new `torrent-stack-lab`
stack in `media_seg` (VLAN 80) — the same zone as `media-stack-lab`
(Jellyfin/Immich) — behind Traefik + Authentik forwardAuth, on
Harbor-proxied, version-pinned images, with Jellyseerr added for
request integration with Jellyfin/Radarr/Sonarr. Fresh install for
config: no arr database, quality profile, or qBittorrent setting is
migrated from the live LXC (operator decision, see `README.md`) — the
indexer/VPN config there hasn't been reliable and isn't worth carrying
forward. No content migration is needed either, but for a different
reason: the actual downloaded movies/TV already land on the same real
NAS content the new stack will write to (operator-confirmed,
2026-09-12 — see `README.md`), so there's nothing to copy. Two real
pieces of legacy's storage ARE reused directly, not migrated: the NAS
library path (`/nas-media/...`, already shared with `media-stack-lab`)
and legacy's own local `/incoming` staging filesystem, shared between
both stacks for now (operator request, 2026-09-12). The legacy stack
otherwise keeps running untouched until an explicit, separate cutover
decision — this plan does not schedule or assume one.

Steps follow `docs/agent-design/step-packet-schema.md`'s shape (`id`/
`change`/`scope`/`gates`) for the discipline it forces — a literal,
git-diffable edit and an unambiguous pass/fail gate per step — but
**execution here is direct, not handed off to a local model via
`implement-step`** (operator decision, 2026-09-12: this stack is
complex enough, with enough real ways to go wrong, to keep a frontier
model driving it end to end). Each step still: does exactly what
`change` says, touches only `scope.allowed_paths`, runs every gate,
and gets a result recorded before moving to the next one. Genuinely
operator-only actions are plain prose below, not step blocks — see
"Operator-only actions" at the end.

---

### torrent-lab-01-env-ip

```yaml
id: torrent-lab-01-env-ip
title: Reserve the new stack's IP as a non-secret env var
depends_on: []

change: >
  Add a new line to .env, immediately after the existing
  LAB_IP_MEDIA_STACK_LAB line (currently line 98): `export
  LAB_IP_TORRENT_STACK_LAB='192.168.80.11'                   #
  torrent-stack-lab (arr suite + gluetun + jellyseerr) service IPv4
  (media_seg VLAN 80); fresh install alongside legacy torrent-stack
  (192.168.1.5, flat LAN, unaffected), see
  docs/torrent-stack-modernization/plan.md`. Do NOT add this to
  .env.template -- CORRECTED during execution 2026-09-12: the
  original draft of this step assumed .env.template mirrors every
  LAB_IP_* var, modeled on LAB_IP_MEDIA_STACK_LAB, but checking the
  actual file found that's false -- none of the last 5 app-tier
  stacks added (media-stack-lab, pentagi-stack, greenbone-stack,
  mcp-utility-stack, secpipe-stack) have their IP in .env.template,
  only in .env. Follow the real, repeated convention, not the
  incorrect plan-time assumption. Also do not add this to .env.pve,
  .env.pve-framework, or any secrets.*.enc.yaml file.

scope:
  allowed_paths:
    - .env
  forbidden_actions:
    - "Any change outside this one file"
    - "Adding this to .env.template, .env.pve, .env.pve-framework, or any secrets.*.enc.yaml file"

gates:
  - id: line-present
    cmd: "grep -c 'LAB_IP_TORRENT_STACK_LAB=.192.168.80.11.' .env"
    expect: "1"
    critical: true
```

---

### torrent-lab-01a-confirm-incoming-mount

Operator request (2026-09-12): legacy torrent-stack's `/incoming` — a
separate, local (non-NAS) filesystem mount, not part of its rootfs or
docker storage — should be reused, shared between legacy torrent-stack
and torrent-stack-lab, for now. This step finds the real host-side
fact needed before `torrent-lab-02` can write a correct
`host_bind_mounts` entry for it.

```yaml
id: torrent-lab-01a-confirm-incoming-mount
title: Discover and record the real host path backing legacy torrent-stack's /incoming mount
depends_on: [torrent-lab-01-env-ip]

change: >
  From a host with real network reachability to pve (this plan's own
  authoring session had none at all -- a read-only Proxmox API check
  failed with "No route to host" from the sandbox used to research and
  write this plan, so this step cannot run from an isolated
  environment; it needs the operator's own machine or a normal
  ./with-secrets-prod session with real LAN access), run either `ssh
  root@pve pct config 100` or `./with-secrets-prod pvesh get
  /nodes/pve/lxc/100/config` (both read-only, pre-approved under
  CLAUDE.md's Production Credential Controls -- pct/pvesh config reads
  are not mutating) and find the mpN: line whose mp= value is
  /incoming. Record two things into a new "Confirmed facts" bullet
  under this workspace's README.md "Real findings" section: (1) the
  exact mpN: line, and (2) which of two cases it is -- a BIND mount
  (the storage field is a plain host directory path) or a VOLUME mount
  (the storage field names a Proxmox storage pool, e.g.
  "local-zfs:vm-100-disk-1"). This distinction matters: a bind mount's
  host directory can safely be added as a second mp on
  torrent-stack-lab directly (same trick media-stack-lab already uses
  for /mnt/nas-media). A volume mount cannot be safely double-mounted
  onto two containers at once -- same risk class as mounting one block
  device in two places simultaneously -- and would need converting to
  a bind mount (or re-exporting from the host) before it can be
  shared. If this step finds a volume mount, record that finding, stop,
  and flag it back to the operator rather than proceeding into
  torrent-lab-02's host_bind_mounts content, which assumes a bind
  mount.

scope:
  allowed_paths:
    - docs/torrent-stack-modernization/README.md
  forbidden_actions:
    - "Any mutating pct or pvesh command -- read-only inspection only"
    - "Editing any file other than this README"
    - "Proceeding to add a host_bind_mounts entry anywhere if the finding is a volume mount, not a bind mount"

gates:
  - id: finding-recorded
    cmd: "grep -c 'mp.*incoming\\|/incoming' docs/torrent-stack-modernization/README.md"
    expect: "at least 1 (the real mpN: line and its bind-vs-volume classification are now recorded, not left as TBD)"
    critical: true
```

**DONE, 2026-09-12.** Ran via `./with-secrets-prod` (approved,
`TASK_APPROVAL=torrent-lab-01a-confirm-incoming-mount`) from the
operator's workstation against the read-only Proxmox API (`pct`/`pvesh`
aren't installed locally, so this used
`GET /nodes/pve/lxc/100/config` directly instead — same read-only
effect). Real finding: `mp2: "/storage/ct-100/incoming,mp=/incoming,
backup=1,size=1T"` — a **BIND mount** (plain host directory), not a
volume mount, confirmed safe to share. Contrast VMID 100's own `mp0`
("apps-containers:subvol-100-disk-1,mp=/var/lib/docker,size=20G"),
which IS a storage-pool-backed volume — the exact case this step was
designed to catch and stop on, and did not hit here. Also incidentally
confirmed `mp1: "/mnt/nas-media-ct100,mp=/nas,backup=0"` — legacy's own
NAS bind mount, under a different host directory name than
media-stack-lab's `/mnt/nas-media` (doesn't change this plan's design,
which already reuses media-stack-lab's own mount rather than legacy's).
See README.md's "Real findings" for the full record.
Note for the earlier "no LAN route" caveat above: that failure was
specific to `pve-test-vm` being unreachable when this plan was first
drafted (`./with-secrets` defaults there) — the operator's workstation
does have a real route to `pve` itself, confirmed by this step
actually running.

---

### torrent-lab-02-stack-yaml

```yaml
id: torrent-lab-02-stack-yaml
title: Author torrent-stack-lab's stack.yaml
depends_on: [torrent-lab-01-env-ip, torrent-lab-01a-confirm-incoming-mount]

change: >
  Create terraform/lxc/stacks/torrent-stack-lab/stack.yaml with
  exactly the literal content below (transcribe verbatim — this
  schema is repo-specific, not a generic pattern; model the field
  shape on terraform/lxc/stacks/media-stack-lab/stack.yaml if anything
  is ambiguous, but the values below are exact, not illustrative).
  torrent-lab-01a's live finding (2026-09-12, via `pct config 100` on
  pve) is already folded in below -- /storage/ct-100/incoming is a
  confirmed real BIND mount, not a placeholder.

scope:
  allowed_paths:
    - terraform/lxc/stacks/torrent-stack-lab/stack.yaml
  forbidden_actions:
    - "Any change outside this one file"
    - "Running terragrunt plan/apply — validation only in this step"

gates:
  - id: yaml-syntax-valid
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/torrent-stack-lab/stack.yaml'))\""
    expect: "exit 0"
    critical: true
```

**Gate note (found during execution 2026-09-12):** the originally
written gate, `terraform/lxc/validate-stack-metadata.sh`, only checks
a small hardcoded `ACTIVE_STACKS` tuple inside
`validate-stack-metadata.py` itself -- there is no flag to validate an
arbitrary stack. Checked before trusting a clean run: none of the last
several "-lab"/app-tier stacks (`media-stack-lab`, `gaming-stack-lab`,
`greenbone-stack`, `pentagi-stack`, `secpipe-stack`, ...) are in that
list either, so running it would have silently validated nothing for
`torrent-stack-lab` while still reporting "passed." Following that
same established precedent (none of those were added to the list),
`torrent-stack-lab` isn't added either -- replaced with a real YAML
syntax check instead.

Literal content for `terraform/lxc/stacks/torrent-stack-lab/stack.yaml`:

```yaml
hostname: torrent-stack-lab
ip_address: 192.168.80.11/24
gateway: 192.168.80.1
dns_server: 192.168.80.1
network:
  zone: media_seg
vmid: 80011
cores: 2
memory: 4096
swap: 512
rootfs_size: 8
storage_profile: platform-default
docker_storage_size: 20G
template_name: debian-13.1-2-docker-template.tar.gz
tags:
- docker
- media
- torrent
depends_on: []
provides:
- service: qbittorrent
  port: 8080
  protocol: tcp
- service: prowlarr
  port: 9696
  protocol: tcp
- service: radarr
  port: 7878
  protocol: tcp
- service: sonarr
  port: 8989
  protocol: tcp
- service: lidarr
  port: 8686
  protocol: tcp
- service: jellyseerr
  port: 5055
  protocol: tcp
ansible_playbook: deploy-torrent-stack-lab
deployment_tier: apps
portainer_agent: true
portainer_server_ip: "${lab_ip_portainer}"
portainer_stacks:
- name: torrent-stack-lab
  compose_file: docker-compose.yml
  env:
  - name: LAB_DOMAIN
    value: "$${lab_domain}"

# Documentation/consistency only -- NOT applied by Terraform (bind-type
# mount points are root@pam-only on Proxmox, same restriction
# media-stack-lab's host_bind_mounts already documents). mp0 reuses the
# SAME host path media-stack-lab already has mounted on pve
# (/mnt/nas-media, itself NFS-mounted from 192.168.1.3) -- backup=0
# here, same reasoning as mp1 below: media-stack-lab's own container
# already backs up this content, a second container re-backing up the
# identical NFS-mounted tree would be redundant. No new NFS
# setup needed on the pve host, just a second bind-mount-point pointing
# at the same already-mounted directory. mp1's host_path
# (/storage/ct-100/incoming) is legacy torrent-stack's own real
# /incoming storage, confirmed live 2026-09-12 via
# `pct config 100` on pve (mp2: "/storage/ct-100/incoming,mp=/incoming,
# backup=1,size=1T") -- a plain host directory (BIND mount), not a
# Proxmox-managed volume, so it's safe to add as a second mp elsewhere;
# contrast VMID 100's own mp0
# ("apps-containers:subvol-100-disk-1,mp=/var/lib/docker,size=20G"),
# which IS a storage-pool-backed volume and could NOT be safely
# double-mounted this way. Shared (not owned) so both stacks'
# qBittorrent instances write to the same real directory, operator
# request 2026-09-12 -- see plan.md's Operator-only actions for the
# accepted concurrency risk. backup=0 here deliberately, unlike VMID
# 100's own backup=1 on the same directory -- one backup job covering
# it (legacy's) is enough; a second container backing up the identical
# 1TB tree would be redundant. Apply both via direct root SSH `pct set
# 80011 -mp0 /mnt/nas-media,mp=/nas-media,backup=0 -mp1
# /storage/ct-100/incoming,mp=/incoming,backup=0` (operator-only, see
# plan.md "Operator-only actions"), then confirm live via
# `pvesh get /nodes/pve/lxc/80011/config`.
host_bind_mounts:
- host_path: /mnt/nas-media
  lxc_path: /nas-media
- host_path: /storage/ct-100/incoming
  lxc_path: /incoming
```

---

### torrent-lab-03-compose

```yaml
id: torrent-lab-03-compose
title: Author torrent-stack-lab's docker-compose.yml
depends_on: [torrent-lab-02-stack-yaml]

change: >
  Create terraform/lxc/stacks/torrent-stack-lab/docker-compose.yml
  with 7 services: gluetun, qbittorrent, flaresolverr, prowlarr,
  radarr, sonarr, lidarr, jellyseerr. Follow compose_requirements
  below exactly; nothing in compose_forbidden. Every image reference
  must resolve through Harbor's existing proxy-cache projects
  (${REGISTRY_HOST}/dockerhub/..., ${REGISTRY_HOST}/ghcr/...,
  ${REGISTRY_HOST}/lscr/...) as media-stack-lab's
  jellyfin-docker-compose.yml already does for its own image -- never
  a bare upstream registry reference.

compose_requirements: |
  - Top-level `name: torrent-stack-lab` (must match the Portainer
    stack.yaml "name:" exactly, same reasoning documented in
    media-stack-lab/jellyfin-docker-compose.yml's header comment).
  - `gluetun`: image ${REGISTRY_HOST}/dockerhub/qmcgaw/gluetun,
    pinned to a specific vX.Y.Z release tag (v3.41.3 was current as of
    2026-09-12 research -- verify against
    https://hub.docker.com/v2/repositories/qmcgaw/gluetun/tags before
    using; never :latest or a pr-* tag). cap_add: [NET_ADMIN]. devices:
    [/dev/net/tun]. environment: VPN_TYPE=wireguard,
    VPN_SERVICE_PROVIDER=custom, VPN_PORT_FORWARDING=on,
    VPN_PORT_FORWARDING_PROVIDER=protonvpn,
    HEALTH_TARGET_ADDRESS=8.8.8.8, HEALTH_VPN_DURATION_INITIAL=10s,
    DOT=off, DNS_PLAINTEXT_ADDRESS=1.1.1.1, TZ=Pacific/Auckland. Do
    NOT use the deprecated DNS_ADDRESS/DNS_SERVER env vars the legacy
    compose used. volumes: a named `gluetun-config` volume at
    /gluetun, plus a bind mount
    /opt/stacks/torrent-stack-lab/gluetun/wireguard/wg0.conf (host
    path, placed manually -- see plan.md's Operator-only actions) to
    /run/secrets/wg0.conf:ro. ports: "8080:8888" (qbittorrent WebUI,
    published here because qbittorrent shares this container's network
    namespace), "6881:6881/tcp", "6881:6881/udp". restart:
    unless-stopped.
  - `qbittorrent`: image ${REGISTRY_HOST}/lscr/linuxserver/qbittorrent,
    pinned to a specific X.Y.Z_vA.B.C-lsNN build tag (5.2.3_v2.0.14-ls475
    was current as of 2026-09-12 research -- verify against
    https://hub.docker.com/v2/repositories/linuxserver/qbittorrent/tags
    before using). container_name: torrent-stack-lab-qbittorrent.
    network_mode: "service:gluetun". depends_on: [gluetun]. environment:
    PUID=1000, PGID=1000, TZ=Pacific/Auckland, WEBUI_PORT=8888. volumes:
    named `qbittorrent-config` volume at /config, plus
    `/incoming:/downloads` (an LXC-local bind mount, NOT a Docker
    named volume -- see torrent-lab-01a-confirm-incoming-mount and
    torrent-lab-02-stack-yaml's host_bind_mounts entry for it).
    `/incoming` is the operator's real, existing local-filesystem
    staging directory that legacy torrent-stack's qBittorrent already
    uses -- reused/shared between both stacks "for now" (operator
    request, 2026-09-12), not a fresh empty directory this stack owns.
    Do NOT also mount /nas-media into qbittorrent -- it never writes to
    the library directly; radarr/sonarr/lidarr are the ones that import
    (move) a finished download from the shared `/incoming` directory
    into their own /nas-media/... mount, the same completed-download-
    handling split legacy already used. No ports: or Traefik
    labels here -- it shares gluetun's network namespace, matching the
    documented gluetun/qbittorrent pattern already used by legacy
    torrent-stack and media-stack-lab's own compose conventions.
    restart: unless-stopped.
  - `flaresolverr`: image
    ${REGISTRY_HOST}/ghcr/flaresolverr/flaresolverr, pinned to a
    specific vX.Y.Z release tag (v3.5.0 was current as of 2026-09-12
    research -- verify against
    https://github.com/FlareSolverr/FlareSolverr/releases before
    using). environment: LOG_LEVEL=info, TZ=Pacific/Auckland. No
    ports: published to the host and no Traefik labels -- internal
    only, reached by prowlarr at http://flaresolverr:8191 over the
    Compose default bridge network. restart: unless-stopped.
  - `prowlarr`, `radarr`, `sonarr`, `lidarr`: each image
    ${REGISTRY_HOST}/lscr/linuxserver/<app>, each pinned to a specific
    non-nightly/non-develop version tag (2.6.3 / 6.3.0 / 4.0.19 / 3.1.0
    respectively were current as of 2026-09-12 research -- verify each
    against https://hub.docker.com/v2/repositories/linuxserver/<app>/tags
    before using). Each: environment PUID=1000, PGID=1000,
    TZ=Pacific/Auckland. Each has its own named config volume
    (`prowlarr-config`, `radarr-config`, `sonarr-config`,
    `lidarr-config`) at /config. **Mount the exact same NAS subpaths
    media-stack-lab's Jellyfin already reads -- NOT the /nas-media root**
    (media-stack-lab/jellyfin-docker-compose.yml only ever mounts the
    specific subdirectory, never /nas-media itself; mounting the whole
    tree would give each app read/write access to every other app's
    library too). radarr mounts /nas-media/video/movies:/movies and
    /nas-media/video/movies:/media/movies (dual path, matching legacy's
    own convention); sonarr mounts /nas-media/video/tv:/tv and
    /nas-media/video/tv:/media/tv; lidarr mounts /nas-media/music:/music
    and /nas-media/music:/media/music. Operator-confirmed 2026-09-12:
    legacy torrent-stack's own downloads already land in this same real
    movies/tv NAS content, not a separate copy -- so no data migration
    is needed here at all (a docs/plan/pve-migration-inventory.md line
    describing "/nas-media/... and /nas/... as different NFS export
    paths" apparently describes each LXC's own differently-named local
    mount point, not two different libraries on the NAS side -- trust
    the operator's live knowledge over that doc). radarr, sonarr, and
    lidarr each also mount /incoming:/downloads (see the `incoming`
    bullet under qbittorrent below -- an LXC-local bind mount, not a
    Docker-managed volume, because it is shared host-filesystem storage
    with legacy torrent-stack, not something this stack owns). prowlarr
    has no library or downloads mount at all -- it only talks to the
    other arr apps' and flaresolverr's HTTP APIs. Ports:
    9696/7878/8989/8686 respectively, host-published (needed for
    Traefik to reach them; see torrent-lab-07-edge). restart:
    unless-stopped for all four.
  - `jellyseerr`: image ${REGISTRY_HOST}/ghcr/fallenbagel/jellyseerr,
    pinned to a specific vX.Y.Z release tag (v3.4.1 was the latest
    GitHub release as of 2026-09-12 research -- verify against
    https://github.com/Fallenbagel/jellyseerr/releases before using;
    do not trust the Docker Hub fallenbagel/jellyseerr tag list without
    cross-checking, it was found stale by roughly a year during this
    plan's research). environment: LOG_LEVEL=info, TZ=Pacific/Auckland.
    Named `jellyseerr-config` volume at /app/config. port 5055,
    host-published. restart: unless-stopped. Do not wire its Jellyfin
    or Radarr/Sonarr connections into this compose file (API keys)
    -- that's a one-time UI configuration step done after first boot,
    not IaC.
  - No top-level `networks:` block -- every service uses the Compose
    default bridge network (gluetun/qbittorrent's network_mode:
    service: override is the only exception, and needs no networks:
    entry of its own).
  - No `logging:` override on any service -- omit it entirely so each
    container inherits docker_base's syslog-to-Graylog default. Do NOT
    repeat the json-file log-driver gap already found on 6 other
    stacks in this repo.

compose_forbidden: |
  a :latest, :nightly, :develop, or :rolling tag on any image; a
  top-level networks: block; publishing gluetun's 6881 port pair
  without also keeping VPN_PORT_FORWARDING=on (the tunnel handles
  inbound P2P via the VPN provider's forwarded port, not a host-level
  port-forward, so 6881 is best-effort/optional but must not be the
  ONLY inbound path assumed); mounting /nas-media anywhere as
  read-only for radarr/sonarr/lidarr (they must be able to write
  imports); a qBittorrent BT_backup/ bind mount (fresh install, no
  session to preserve); any Authentik/OIDC client ID or secret
  hardcoded into an environment: block (forwardAuth handles auth at
  the edge, not inside these containers, so none of them need OIDC
  credentials at all); a logging: block on any service.

scope:
  allowed_paths:
    - terraform/lxc/stacks/torrent-stack-lab/docker-compose.yml
  forbidden_actions:
    - "Any change outside this one file"
    - "Running docker compose up -- validation only in this step"

gates:
  - id: compose-validate
    cmd: "terraform/lxc/validate-compose.sh --stack torrent-stack-lab"
    expect: "exit 0"
    critical: true
  - id: no-floating-tags
    cmd: "grep -E 'image:.*:(latest|nightly|develop|rolling)\\b' terraform/lxc/stacks/torrent-stack-lab/docker-compose.yml"
    expect: "no match (grep exit 1)"
    critical: true
  - id: no-logging-override
    cmd: "grep -c '^\\s*logging:' terraform/lxc/stacks/torrent-stack-lab/docker-compose.yml"
    expect: "0"
    critical: true
```

**DONE, 2026-09-12.** All 3 gates passed. Tags verified against each
registry's raw tag API directly (curl + JSON parsing, not a
paraphrased summary -- an earlier paraphrase-based lookup during
research had wrongly picked prowlarr `2.6.3`, which the raw data shows
is not actually a stable/promoted tag): gluetun `v3.41.3`, qbittorrent
`5.2.3_v2.0.14-ls475`, flaresolverr `v3.5.0`, prowlarr
`2.5.2.5491-ls159`, radarr `6.3.0.10514-ls315`, sonarr
`4.0.19.2979-ls323`, lidarr `3.1.0.4875-ls41`. **Real discrepancy
found and worth recording**: Jellyseerr's GitHub releases page shows
`v3.4.1` as latest, but pulling the complete raw tag list from both
Docker Hub and GHCR directly shows neither registry has ever published
a container image past `2.7.3` -- pinned to `2.7.3`, the actual latest
pullable tag, not the source release number. `qbittorrent-config` etc.
volumes and the `/incoming`/`/nas-media/...` bind mounts match
`torrent-lab-02`'s `host_bind_mounts` and this step's own
`compose_requirements` exactly.

---

### torrent-lab-04-contract

```yaml
id: torrent-lab-04-contract
title: Author torrent-stack-lab's STACK_CONTRACT.md
depends_on: [torrent-lab-03-compose]

change: >
  Create terraform/lxc/stacks/torrent-stack-lab/STACK_CONTRACT.md
  modeled section-for-section on
  terraform/lxc/stacks/media-stack-lab/STACK_CONTRACT.md (Purpose,
  Network, Inputs, Provides, Dependencies, Persistent State, What May
  Depend on This Stack, What Must Not Be Edited Casually, Playbook).
  Populate every section from this stack's own real facts: Purpose
  states this replaces legacy torrent-stack via a fresh config install
  (no arr database or qBittorrent settings carried over — the
  indexer/VPN config there hasn't been reliable) while directly reusing
  legacy's real NAS library content and local /incoming staging
  filesystem rather than migrating either, standing up alongside
  legacy, additive not destructive, same as media-stack-lab's own
  framing relative to legacy media-stack.
  Network table: zone media_seg (VLAN 80), IP 192.168.80.11/24,
  gateway 192.168.80.1, VMID 80011, plus the firewall rule list from
  torrent-lab-08-network-policy. Inputs: LAB_DOMAIN (.env, existing).
  Provides: the 6 services and ports from stack.yaml's provides: list.
  Dependencies: none at platform level; runtime dependency on the same
  NAS NFS export media-stack-lab already mounts (192.168.1.3, flat
  LAN, via the shared /mnt/nas-media host bind mount) and on Authentik
  for forwardAuth once edge.yaml is live -- five of the six routes
  (qbittorrent, prowlarr, radarr, sonarr, lidarr); jellyseerr
  deliberately has no edge-level auth dependency at all (auth.mode:
  none, operator decision 2026-09-12 -- it gates itself via its own
  "Sign in with Jellyfin" instead, so household members without a full
  Authentik account can still use it) -- plus a real, load-bearing
  dependency on legacy torrent-stack's own local /incoming storage
  (shared, not owned by this stack; see torrent-lab-01a). Persistent
  State: 7 named Docker volumes owned by this stack alone
  (gluetun-config, qbittorrent-config, prowlarr-config, radarr-config,
  sonarr-config, lidarr-config, jellyseerr-config) plus two things this
  stack does NOT own but writes into: /nas-media (shared with
  media-stack-lab/Jellyfin) and /incoming (shared with legacy
  torrent-stack -- see What Must Not Be Edited Casually). What Must Not
  Be Edited Casually: the /nas-media path must keep matching
  media-stack-lab's own mount so both stacks read/write the same
  library; /incoming is shared, concurrently, with legacy
  torrent-stack's own still-running qBittorrent -- accepted by the
  operator as a temporary state (2026-09-12), not a long-term design;
  revisit when legacy is decommissioned (real risk: duplicate
  downloads, category collisions, one instance's cleanup removing a
  file the other still references); WireGuard credentials at
  /opt/stacks/torrent-stack-lab/gluetun/wireguard/wg0.conf are never
  committed or SOPS'd; legacy torrent-stack (VMID 100) is never
  stopped, restarted, or has its OWN config/database written to by
  anything in this stack's deploy path -- sharing /incoming's files is
  the one deliberate exception to "never touch legacy." Playbook:
  deploy-torrent-stack-lab.

scope:
  allowed_paths:
    - terraform/lxc/stacks/torrent-stack-lab/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside this one file"

gates:
  - id: required-sections-present
    cmd: "grep -c '^## Provides$\\|^## Dependencies$' terraform/lxc/stacks/torrent-stack-lab/STACK_CONTRACT.md"
    expect: "2 (same ACTIVE_STACKS limitation as torrent-lab-02 -- validate-stack-metadata.sh's --check-contract-sections wouldn't check this file either, confirmed by running it)"
    critical: true
```

**DONE, 2026-09-12.**

---

### torrent-lab-05-terragrunt

```yaml
id: torrent-lab-05-terragrunt
title: Author torrent-stack-lab's terragrunt.hcl
depends_on: [torrent-lab-02-stack-yaml]

change: >
  Create terraform/lxc/stacks/torrent-stack-lab/terragrunt.hcl with
  exactly the literal content below -- this file is identical
  boilerplate across every stack in terraform/lxc/stacks/, transcribed
  verbatim from terraform/lxc/stacks/media-stack-lab/terragrunt.hcl
  with no changes at all (it derives stack_name from the directory
  name automatically).

scope:
  allowed_paths:
    - terraform/lxc/stacks/torrent-stack-lab/terragrunt.hcl
  forbidden_actions:
    - "Any change outside this one file"
    - "Running terragrunt plan/apply/validate -- authoring only in this step"

gates:
  - id: hcl-matches-precedent
    cmd: "diff terraform/lxc/stacks/media-stack-lab/terragrunt.hcl terraform/lxc/stacks/torrent-stack-lab/terragrunt.hcl"
    expect: "no differences (exit 0)"
    critical: true
```

Literal content for `terraform/lxc/stacks/torrent-stack-lab/terragrunt.hcl`:

```hcl
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "${get_repo_root()}/terraform/lxc//"
}

inputs = {
  stack_name      = basename(get_terragrunt_dir())
  stack_yaml_path = "${get_terragrunt_dir()}/stack.yaml"
}
```

---

### torrent-lab-06-playbook

```yaml
id: torrent-lab-06-playbook
title: Author the deploy-torrent-stack-lab Ansible playbook
depends_on: [torrent-lab-03-compose]

change: >
  Create terraform/lxc/ansible/playbooks/deploy-torrent-stack-lab.yml,
  modeled on terraform/lxc/ansible/playbooks/deploy-media-stack-lab.yml's
  structure (same lxc_base + docker_base + portainer_agent roles, same
  daemon.json Harbor-trust-plus-Graylog-syslog task, same
  flush_handlers-before-deploy ordering) but simplified for one
  compose file instead of two split projects -- there is no
  pre-split-migration guard block to carry over (torrent-stack-lab has
  no prior combined-project history to migrate away from; this is a
  first deploy). stack_name: torrent-stack-lab. Read the compose file
  via lookup('file', ...) exactly as deploy-media-stack-lab.yml does,
  write it to /opt/stacks/torrent-stack-lab/docker-compose.yml, run
  `docker compose config` to validate, then `docker compose up -d`,
  each guarded by `when: not ansible_check_mode` exactly as the
  Minecraft exemplar playbook in
  terraform/lxc/stacks/stack-request.example.yaml does. Do not
  template any OAuth/OIDC client secret into this playbook --
  forwardAuth needs none.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-torrent-stack-lab.yml
  forbidden_actions:
    - "Any change outside this one file"
    - "Running ansible-playbook against any real host -- syntax-check only in this step"

gates:
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check playbooks/deploy-torrent-stack-lab.yml"
    expect: "exit 0 (must run from terraform/lxc/ansible/ -- its own ansible.cfg sets roles_path=roles; running from repo root fails with role 'lxc_base' not found, confirmed during execution 2026-09-12)"
    critical: true
```

**DONE, 2026-09-12.** Gate passed once run from the correct directory
(the plan's original gate command, run from repo root, was itself
wrong -- corrected above).

---

### torrent-lab-07-edge

```yaml
id: torrent-lab-07-edge
title: Author torrent-stack-lab's edge.yaml (EdgeManifest)
depends_on: [torrent-lab-02-stack-yaml]

change: >
  Create terraform/lxc/stacks/torrent-stack-lab/edge.yaml as an
  EdgeManifest v1alpha1 (see
  docs/provisioning-refactor/edge-manifest-v1alpha1.md), modeled on
  terraform/lxc/stacks/media-stack-lab/edge.yaml's structure. metadata
  name: torrent-stack-lab-edge, stack: torrent-stack-lab. Six routes,
  one per web-facing service (qbittorrent, prowlarr, radarr, sonarr,
  lidarr, jellyseerr) -- flaresolverr gets no route at all, it is
  internal-only. Every route: host <name>.${LAB_DOMAIN}, backend type
  url pointing at http://${LAB_IP_TORRENT_STACK_LAB}:<port> (8080 for
  qbittorrent since it's published via gluetun on that port; 9696,
  7878, 8989, 8686, 5055 for the others), dns.enabled true with
  target ${LAB_IP_PROXY} and ttl 5m, tls.resolver letsencrypt. Five of
  the six (qbittorrent, prowlarr, radarr, sonarr, lidarr) get
  auth.mode: forwardAuth -- none of them support native SSO, matching
  the edge-manifest doc's own guidance that forwardAuth is for
  "services that don't have their own auth but need user gating," and
  these are single-operator admin tools where one shared gate is
  correct. jellyseerr is the deliberate exception: auth.mode: none
  (operator decision 2026-09-12) -- it's a household-facing request
  portal, not an admin tool, and forwardAuth would require every
  household member to already hold a full Authentik lab account just
  to reach Jellyseerr's own login screen, blocking anyone who only has
  a Jellyfin account. Jellyseerr's own built-in "Sign in with Jellyfin"
  login becomes the real gate instead -- same posture
  media-stack-lab/edge.yaml already gives Jellyfin and Immich
  themselves (auth.mode: oidc there, not forwardAuth, precisely
  because those apps also handle their own per-user identity rather
  than sitting behind a blanket admin gate). Do not add a
  repo.auth.oidc.client_id_env/client_secret_env annotation to
  metadata -- that pattern is only for auth.mode: oidc routes, and
  none of these six routes use oidc (jellyseerr uses none, not oidc,
  despite also being household-facing -- it has no native OIDC client
  of its own, only "sign in with Jellyfin").

scope:
  allowed_paths:
    - terraform/lxc/stacks/torrent-stack-lab/edge.yaml
  forbidden_actions:
    - "Any change outside this one file"
    - "Adding an auth.mode: oidc route for any of these six services"
    - "Adding auth.mode: forwardAuth to the jellyseerr route"

gates:
  - id: edge-manifest-validate
    cmd: "set -a && source .env && set +a && python3 terraform/lxc/validate-edge-manifests.py terraform/lxc/stacks/torrent-stack-lab/edge.yaml"
    expect: "exit 0, no validation errors (must source .env first -- the validator resolves ${LAB_DOMAIN} etc. from the real environment, not as a literal string; confirmed during execution 2026-09-12 by seeing media-stack-lab's own edge.yaml fail identically without it)"
    critical: true
  - id: jellyseerr-auth-mode
    cmd: "grep -A13 'name: jellyseerr' terraform/lxc/stacks/torrent-stack-lab/edge.yaml | grep -c 'mode: none'"
    expect: "1 (jellyseerr uses auth.mode: none, not forwardAuth)"
    critical: true
```

**DONE, 2026-09-12.** Both gates passed once `.env` was sourced first
(cross-checked against `media-stack-lab`'s own `edge.yaml`, which fails
the exact same way unsourced — a real, general requirement of this
validator, not specific to this file).

---

### torrent-lab-08-network-policy

```yaml
id: torrent-lab-08-network-policy
title: Add new (not modified) firewall policy entries to pve.yaml for torrent-stack-lab
depends_on: [torrent-lab-02-stack-yaml]

change: >
  In terraform/lxc/network/pve.yaml, add torrent-stack-lab to the
  media_seg zone's containers: list (append
  "torrent-stack-lab (VMID 80011) -- 192.168.80.11" as a new list item,
  do not touch the existing media-stack-lab line above it). Then add
  two entirely NEW entries to the top-level policies: list (append at
  the end, immediately after the last existing media_seg policy entry
  -- do not edit any existing policy entry's ports or hosts, including
  the existing edge_seg -> media_seg tcp/8096,2283 rule, which stays
  exactly as it is for Jellyfin/Immich): (1) from: edge_seg, to:
  media_seg, protocol: tcp, ports: [9696, 7878, 8989, 8686, 8080,
  5055], description explaining this is Traefik to
  torrent-stack-lab's prowlarr/radarr/sonarr/lidarr/qbittorrent(via
  gluetun)/jellyseerr web UIs, added as a new rule rather than
  widening the existing Jellyfin/Immich rule so this stays an additive
  change under this repo's validation tiers; (2) from: media_seg, to:
  internet, protocol: udp, ports: [51820], description explaining this
  is gluetun's WireGuard VPN tunnel egress, the same real gap the
  superseded docs/application-migration/01-torrent-stack-lab.md plan
  identified for its abandoned dl_seg zone -- media_seg needs the same
  rule since gluetun now lives there instead.

scope:
  allowed_paths:
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Editing any existing policy entry's ports, from, to, or description fields"
    - "Editing any zone other than media_seg's containers list"
    - "Running terragrunt plan/apply -- authoring only in this step"

gates:
  - id: existing-jellyfin-rule-untouched
    cmd: "grep -A3 'to: media_seg' terraform/lxc/network/pve.yaml | grep -c '8096, 2283\\|\\[8096, 2283\\]'"
    expect: "at least 1 (the original Jellyfin/Immich rule's port list is unchanged)"
    critical: true
  - id: new-rules-present
    cmd: "grep -c '51820' terraform/lxc/network/pve.yaml"
    expect: "1"
    critical: true
  - id: yaml-syntax-valid
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/network/pve.yaml'))\""
    expect: "exit 0"
    critical: true
```

**DONE, 2026-09-12.** All gates passed; `git diff` reviewed directly
and confirmed purely additive (2 new lines: the containers-list entry
and the two new policy blocks; zero lines changed or removed anywhere
else in the file).

---

### torrent-lab-09-mikrotik-playbook

```yaml
id: torrent-lab-09-mikrotik-playbook
title: Author (do not run) the MikroTik playbook for media_seg's new WireGuard egress rule
depends_on: [torrent-lab-08-network-policy]

change: >
  Create
  ansible/00-initial-setup/mikrotik-firewall-media-seg-wireguard-egress.yml,
  modeled directly on the idempotent
  read-check-insert-before-anchor-reread-assert pattern in
  ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml
  (same mikrotik_host/mikrotik_user/mikrotik_password env-var-lookup
  vars, same REST base URL construction, same idempotency check before
  inserting). This playbook's one rule: source
  192.168.80.0/24 (media_seg subnet), destination any
  (internet-bound), protocol udp, dst-port 51820, action accept,
  comment "media_seg -> internet udp/51820 (torrent-stack-lab gluetun
  WireGuard)", placed before whatever anchor rule the greenbone
  playbook itself found and documents as the actual containment/deny
  point for its own zone -- re-derive the correct anchor for media_seg
  specifically by the same live-inspection method that playbook's own
  header comment describes (do not assume the same anchor rule
  applies to a different zone without checking). This step authors the
  file only; running it against the live MikroTik is a production
  network mutation and happens under the Operator-only actions section
  of this plan, not here.

scope:
  allowed_paths:
    - ansible/00-initial-setup/mikrotik-firewall-media-seg-wireguard-egress.yml
  forbidden_actions:
    - "Running this playbook against any real host, including via --check"
    - "Any change outside this one file"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check ansible/00-initial-setup/mikrotik-firewall-media-seg-wireguard-egress.yml"
    expect: "exit 0"
    critical: true
```

**DONE, 2026-09-12, then CORRECTED the same day after a real live
check.** Operator-only action #1 (confirm media_seg's real MikroTik
anchor) was done for real via a read-only GET against
`/ip/firewall/filter` (operator confirmed this session has that read
access) — and it invalidated the first draft's design. The first
draft guessed the anchor would be a forward drop/reject on
`in-interface=vlan80-media` (the interface name itself was right,
confirmed live) and fell back to an unanchored "no `place-before`"
insert if that guess found nothing. **The real anchor (rule `*8A`,
comment "media_seg default-deny to LAN and other zones") matches on
`src-address=192.168.80.0/24`, not `in-interface` at all** — so the
first draft's guess would have matched zero rules, taken the fallback
path, and landed the new accept rule *after* the deny in evaluation
order: permanently dead, exactly the "rule appended after an existing
catch-all is silently dead" failure mode this file's own header
already quoted from precedent, just not yet caught in its own logic.
Fixed to match on `src-address` (the confirmed real field), with the
fallback path removed entirely — there is now exactly one, confirmed
way to do this, not two. Also matched the established "internet"
convention found live in the same read (rule `*89`): `dst-address:
!192.168.0.0/16`, not an unscoped destination. Validated the fixed
Jinja anchor-detection logic offline against the real fetched JSON
(not just `--syntax-check`, which can't catch this class of bug) — it
correctly finds `*8A` and asserts on its exact fields. Added a final
order-check task (`list.index()` on rule comments) asserting the new
rule's position is before the deny's, since presence alone doesn't
prove it'll ever fire.

---

## Operator-only actions (not step blocks)

These are either genuinely production-mutating (require the
Preflight/Approval/Execute/After-Action flow from `CLAUDE.md`'s
Production Credential Controls), physically manual, or both. None of
them are safe or possible for an unsupervised local-model step.

1. ~~Confirm the anchor rule for media_seg on the live MikroTik~~ —
   **DONE, 2026-09-12.** Read-only GET against `/ip/firewall/filter`
   confirmed the real anchor (rule `*8A`, `src-address=192.168.80.0/24`,
   NOT the guessed `in-interface=vlan80-media`) — see
   `torrent-lab-09`'s corrected step for the full finding. This
   directly disproved the first playbook draft's assumption before it
   was ever run for real; `torrent-lab-09`'s file is already fixed to
   match.

2. ~~`terragrunt plan` on `pve-test-vm` for the `torrent-lab-08`
   `pve.yaml` policy change~~ — **CORRECTED and DONE, 2026-09-12.**
   `pve-test-vm` turned out to be unreachable when this was attempted
   (100% packet loss, not a transient blip) — operator clarified it's
   deliberately kept powered down, reserved only for specific
   high-risk structural tests, and real validation work happens
   directly on `pve`. This contradicts the Validation Tiers table's
   literal wording for the additive-network-tier row (which names
   `pve-test-vm`), but matches `CLAUDE.md`'s own overriding instruction
   elsewhere to trust real operational practice over a tier row's
   literal defaults. Validated directly against `pve` instead, via
   `./with-secrets-prod terragrunt plan --working-dir` (read-only,
   allowed without approval per the Command Classification table):
   - `torrent-stack-lab` itself: `Plan: 6 to add, 0 to change, 0 to
     destroy` — a clean brand-new-stack plan (LXC, its network SDN
     attachment, ansible inventory file, cleanup hook), touching
     nothing existing.
   - `media-stack-lab` (the only other real `media_seg` tenant, the
     adjacent-zone regression check this tier calls for): showed
     `2 to add, 0 to change, 1 to destroy` — NOT clean on first look.
     Investigated before trusting either way: reverted `pve.yaml` to
     its pre-`torrent-lab-08` content AND removed the
     `torrent-stack-lab` directory entirely, re-ran the same plan, got
     the *identical* result. This proves the drift
     (`local_file.ansible_inventory` replacement over
     `portainer_server_ip` resolving to a real value where it was
     previously blank, plus a `stack_cleanup` null_resource wanting
     recreation) is 100% pre-existing and unrelated to this work — not
     something introduced by `torrent-lab-08`. Files restored to their
     exact committed state afterward (`git diff HEAD` confirmed clean).
     Real, separate finding worth the operator's attention on its own
     time, not a blocker for this stack.
   `scripts/provision.sh --stack media-stack-lab` (the second half of
   this tier's regression check) was not run — it would actually apply
   the drift above rather than just show it, and that's outside this
   task's scope to decide.

3. ~~Preflight summary → operator approval → run the MikroTik
   playbook~~ — **DONE, 2026-09-12.** Operator approved and ran
   `./with-secrets ansible-playbook
   ansible/00-initial-setup/mikrotik-firewall-media-seg-wireguard-egress.yml`
   directly (this session's own attempt was blocked by the Claude Code
   harness's auto-mode classifier — a layer below this repo's own
   approval flow, not bypassable). Result: `ok=11, failed=0, skipped=0`
   — every task ran including both order-check assertions, none
   failed (`changed=0` is a known `ansible.builtin.uri` reporting quirk
   — it doesn't auto-mark POSTs as changed — not evidence nothing
   happened). Independently re-verified afterward with a fresh
   read-only GET (not just trusting the playbook's own self-report):
   the new rule (`*8E`) is live at position 120, matches every expected
   field (`chain=forward, action=accept, protocol=udp,
   src=192.168.80.0/24, dst=!192.168.0.0/16, dst-port=51820`), and sits
   immediately before the `media_seg` default-deny (`*8A`) at position
   121 — correctly placed, confirmed by actual rule order, not just
   presence.

4. ~~`terragrunt apply`~~ — **DONE, 2026-09-12.** Operator ran it
   directly (this session's own attempt was blocked by the Claude Code
   harness's auto-mode classifier, same as `torrent-lab-09`'s MikroTik
   playbook). `Apply complete! Resources: 6 added, 0 changed, 0
   destroyed` — matches the pre-validated plan exactly. Confirmed live:
   `container_id = 80011`, `ip_address = "192.168.80.11/24"`,
   `zone = "media_seg"`, `target_node = "pve"`. **`pct set 80011 -mp0
   /mnt/nas-media,mp=/nas-media,backup=0 -mp1
   /storage/ct-100/incoming,mp=/incoming,backup=0` (the bind mounts)
   was NOT yet run** — the operator went straight to `provision.sh`
   (item 5) instead, which failed before the mounts would have mattered
   (see below). Still needed before a real deploy can succeed
   end-to-end: `pct` isn't installed on the workstation, run via `ssh
   root@pve pct set ...` or the equivalent Proxmox API call.

5. ~~`./with-secrets-prod scripts/provision.sh --stack
   torrent-stack-lab`~~ — **ATTEMPTED 2026-09-12, FAILED, real bug
   found and fixed, not yet re-run.** Failed at "Start torrent-stack-lab
   via docker compose" with `invalid reference format` on every image
   — `REGISTRY_HOST` was never written into the stack's `.env` file, so
   every `${REGISTRY_HOST}/...` reference resolved to a blank host
   (leading slash, no host). Root cause: Ansible's `command` module
   doesn't inherit the control machine's environment when running over
   SSH to a remote LXC — `docker_registry_host` was already computed as
   a playbook variable but never actually written where Docker Compose
   reads it (its own project `.env`). Fixed in
   `terraform/lxc/ansible/playbooks/deploy-torrent-stack-lab.yml`
   (added the missing line, matching `media-stack-lab`'s immich `.env`
   task, which does this correctly — its jellyfin one has the identical
   gap, flagged to the operator separately, not fixed here, unrelated
   stack). `terragrunt apply` (item 4) was unaffected by this failure —
   it completed first and stayed applied. Re-run needed, after the bind
   mounts (item 4) are actually set.

6. **Generate or export a ProtonVPN WireGuard config and place it** at
   `/opt/stacks/torrent-stack-lab/gluetun/wireguard/wg0.conf` on the
   new LXC, then restart the `gluetun` container. Never committed to
   git or SOPS, same rule as the legacy stack's credentials.

7. **Add `192.168.80.11` to the NAS's NFS allowlist** for whichever
   share backs `/mnt/nas-media` (same ADM-side step
   `media-stack-lab` needed) — likely already covered if the same
   `/mnt/nas-media` host mount is shared, but confirm rather than
   assume, since ADM allowlists can be per-client-IP. `/incoming` needs
   no NFS allowlist change at all — it's local Proxmox-host disk, not a
   NAS export.

8. **Validate end-to-end** (search → grab → download → import →
   visible on NAS, same checklist shape as the superseded plan's
   Step 6) before considering this a real replacement for the legacy
   stack.

9. **Wire Jellyseerr's Jellyfin/Radarr/Sonarr connections** via its
   own setup wizard (API keys, not IaC) — genuinely a one-time UI
   step, matching the `STACK_CONTRACT.md`'s note that this isn't
   templated into the compose file. This is also where Jellyseerr's
   own auth actually gets configured — since it has `auth.mode: none`
   at the edge (operator decision 2026-09-12), its own "Sign in with
   Jellyfin" setup during this wizard IS the real access control, not
   an afterthought. Set a real admin account here; don't leave it on
   whatever the setup wizard defaults to.

10. **Disable each arr app's and qBittorrent's built-in web-UI auth**
    (Settings → General → Authentication → None) once forwardAuth is
    confirmed working end-to-end for that app — avoids double-login,
    same as the superseded plan correctly called out. Leave API-key
    auth in place for intra-stack calls. **This does NOT apply to
    Jellyseerr** — its own auth is the only gate it has (`auth.mode:
    none` at the edge), so its built-in login must stay enabled, not
    be disabled. **qBittorrent specifically** also needs its own
    Host-header allowlist updated (WebUI → Options → Web UI) to accept
    requests arriving as `qbittorrent.${LAB_DOMAIN}` — its WebUI
    rejects requests with an unrecognized Host header by default,
    which otherwise looks indistinguishable from a broken forwardAuth
    setup.

11. **Watch for the real risk of sharing `/incoming` between two live
    qBittorrent instances** (legacy's and torrent-stack-lab's,
    operator request 2026-09-12) — duplicate downloads of the same
    torrent, category-folder collisions, or one instance's cleanup
    removing a file the other still references. Explicitly accepted as
    a temporary state, not a long-term design (see `STACK_CONTRACT.md`)
    — revisit (stop sharing, give torrent-stack-lab its own directory)
    once legacy is decommissioned or the overlap proves actively
    troublesome.

12. **In the new Radarr/Sonarr/Lidarr, point root folders at
    `/movies`, `/tv`, `/music` and use each app's own "Import Existing
    Movies/Series" / unmonitored library scan** to recognize whatever
    legacy has already deposited in `/nas-media/...`. This is expected
    and necessary regardless of the mount design — the fresh-install
    decision means these apps start with empty databases, so nothing
    carries over automatically; each app has to (re)discover its own
    library against the files that are already really there, the same
    workflow as pointing any fresh arr install at a pre-existing
    folder of media.

13. **Cutover and decommission of legacy `torrent-stack`** (VMID 100)
    is a separate, later, explicitly operator-initiated decision — not
    scheduled or assumed by this plan, matching how `media-stack-lab`
    treats legacy `media-stack`.
