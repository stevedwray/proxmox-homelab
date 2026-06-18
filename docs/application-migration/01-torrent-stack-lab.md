# Sprint 01: torrent-stack-lab

Deploy the torrent stack (gluetun + arr suite) into `dl_seg` (VLAN 55) as
`torrent-stack-lab`, with Traefik + Authentik access. Validate against real config
data rsynced from the live stack. Cut over and decommission the legacy LXC.

---

## Context: existing stack

**Live stack:** `torrent-stack` at `192.168.1.5` (LAN bridge, vmbr0)
**VMID:** unknown — confirm with `./with-secrets-prod pvesh get /nodes/pve/lxc`
**Portainer endpoint:** `tcp://192.168.1.5:9001`

**Running services:**

| Container | Image | Ports |
|---|---|---|
| gluetun | qmcgaw/gluetun | 8080 (qbittorrent WebUI), 6881 (torrent) |
| qbittorrent | lscr.io/linuxserver/qbittorrent | via gluetun network |
| prowlarr | lscr.io/linuxserver/prowlarr | 9696 |
| radarr | lscr.io/linuxserver/radarr | 7878 |
| sonarr | lscr.io/linuxserver/sonarr | 8989 |
| lidarr | blampe/lidarr | 8686 |
| flaresolverr | ghcr.io/flaresolverr/flaresolverr | 8191 (internal only) |

**Config and data:**

| Path on LXC | Migrate? | Purpose |
|---|---|---|
| `/config/torrents/gluetun/wireguard/wg0.conf` | Manual | WireGuard credentials (sensitive, not in SOPS) |
| `/config/torrents/prowlarr/` | Yes — rsync | Indexer configs, tracker API keys |
| `/config/torrents/radarr/` | Yes — rsync | Movie library DB, quality profiles, custom formats |
| `/config/torrents/sonarr/` | Yes — rsync | TV library DB, quality profiles, monitored state |
| `/config/torrents/lidarr/` | Yes — rsync | Music library DB |
| `/config/torrents/qbittorrent/` | Settings only | `qBittorrent.conf` (categories, paths, limits); skip `BT_backup/` (torrent session) |
| `/incoming/` | No — create empty | New download landing zone; in-flight torrents not preserved |
| `/nas/video/movies` | No — same NAS export | NFS mount, same data, new client IP |
| `/nas/video/tv` | No — same NAS export | NFS mount, same data, new client IP |
| `/nas/music` | No — same NAS export | NFS mount, same data, new client IP |

The arr databases (radarr.db, sonarr.db, lidarr.db) are the valuable state — library
contents, history, quality config. qbittorrent starts fresh with no active torrents;
that's intentional and acceptable.

**Old IaC (recoverable from git):**
- `terraform/torrent-stack/main.tf` — commit `49b1f1e` (uses old `telmate/proxmox` provider)
- `terraform/torrent-stack/ansible/playbook.yml` — commit `49b1f1e` (compose + directory scaffold)
- `terraform/ansible/shared-roles/lxc_tun_device/` — commit `7f8ff8a` (TUN via SSH, superseded)

The old compose is the reference for services, environment vars, and volume paths.
The provisioning approach is replaced entirely by the new `bpg/proxmox` + Ansible pattern.

---

## Target architecture

**Lab stack:** `torrent-stack-lab` at `192.168.55.22/24`, gateway `192.168.55.1`
**Zone:** `dl_seg`, VLAN 55

```
Internet
   │ udp/51820 (WireGuard)
   ▼
gluetun (VPN exit for all download traffic)
   │
   ├── qbittorrent (network_mode: service:gluetun)
   │
LXC 192.168.55.22
   │
   ├── prowlarr:9696
   ├── radarr:7878
   ├── sonarr:8989
   ├── lidarr:8686
   ├── flaresolverr:8191 (internal only — prowlarr uses it directly)
   └── docker-socket-proxy:2375 (Traefik discovery)
   │
   ├── NFS → 192.168.1.3 (NAS)
   │     /nas/video/movies
   │     /nas/video/tv
   │     /nas/music
   │
   └── /incoming (local, in-progress downloads)

Traefik (edge_seg) → forwardAuth → Authentik (mgmt_seg)
   ├── qbittorrent.lab.gibbsgreatly.xyz → 192.168.55.22:8080 (gluetun publishes this)
   ├── radarr.lab.gibbsgreatly.xyz      → 192.168.55.22:7878
   ├── sonarr.lab.gibbsgreatly.xyz      → 192.168.55.22:8989
   ├── prowlarr.lab.gibbsgreatly.xyz    → 192.168.55.22:9696
   └── lidarr.lab.gibbsgreatly.xyz      → 192.168.55.22:8686
```

flaresolverr has no Traefik route — it's an internal solver used by prowlarr
via `http://flaresolverr:8191` on the Docker bridge network.

---

## Pre-conditions (sprint gate)

Do not start until all are satisfied:

- [ ] `dl_seg` (VLAN 55, 192.168.55.0/24) defined in `terraform/lxc/network/pve.yaml` and applied
- [ ] MikroTik rules in place:
  - [ ] `dl_seg → 192.168.1.3 tcp+udp/2049` (NFS to NAS)
  - [ ] `dl_seg → internet udp/51820` (WireGuard)
  - [ ] `dl_seg → infra_seg tcp/80,443,3142` (Harbor + apt-cacher)
  - [ ] `dl_seg → mgmt_seg tcp/9001` (Portainer agent)
  - [ ] `edge_seg → dl_seg tcp/2375` (Traefik socket-proxy)
  - [ ] `edge_seg → dl_seg tcp/7878,8989,9696,8686,8080` (Traefik → arr UIs)
  - [ ] `mgmt_seg → dl_seg tcp/9001` (infra Portainer → agent)
  - [ ] `mgmt_seg → LAN tcp/9001` (temporary: infra Portainer → legacy LAN agents, remove after all sprints)
- [ ] Harbor images mirrored (see image list below)
- [ ] `configure-tun.yml` Ansible playbook created (modeled on `configure-keyctl.yml`)
- [ ] NAS NFS export paths confirmed (exact export name from ADM, not just mount path)
- [ ] ADM NFS share: `192.168.55.22` added to allowlist for each relevant share
- [ ] Infra Portainer (mgmt_seg) running and reachable
- [ ] Authentik forwardAuth middleware configured and tested (should already exist for other stacks)

### Harbor images to mirror

| Source image | Harbor proxy path |
|---|---|
| `qmcgaw/gluetun` | `harbor.lab.gibbsgreatly.xyz/proxy/qmcgaw/gluetun` |
| `lscr.io/linuxserver/qbittorrent` | `harbor.lab.gibbsgreatly.xyz/proxy/linuxserver/qbittorrent` |
| `lscr.io/linuxserver/prowlarr` | `harbor.lab.gibbsgreatly.xyz/proxy/linuxserver/prowlarr` |
| `lscr.io/linuxserver/radarr` | `harbor.lab.gibbsgreatly.xyz/proxy/linuxserver/radarr` |
| `lscr.io/linuxserver/sonarr` | `harbor.lab.gibbsgreatly.xyz/proxy/linuxserver/sonarr` |
| `blampe/lidarr` | `harbor.lab.gibbsgreatly.xyz/proxy/blampe/lidarr` |
| `ghcr.io/flaresolverr/flaresolverr` | `harbor.lab.gibbsgreatly.xyz/proxy/flaresolverr/flaresolverr` |

Note: `lscr.io` is LinuxServer's container registry. Harbor proxy rules for `lscr.io`
need to be configured as a separate proxy endpoint in Harbor if not already present.

---

## Step 1: Stop the live stack for config extraction

Stop the live stack containers so the SQLite databases (radarr.db, sonarr.db, lidarr.db)
are in a consistent state for copying. In-flight torrents are not preserved — that's
acceptable. The live stack LXC remains running; only the Docker containers are stopped.

```bash
# In Portainer (legacy or infra): torrent-stack endpoint → stack → Stop
# Confirm all containers are stopped before proceeding
```

Take a snapshot for safety:
```bash
./with-secrets-prod pct snapshot <vmid> pre-migration-$(date +%Y%m%d)
```

---

## Step 2: Extract arr config to staging

```bash
# Rsync the arr configs (the valuable state)
rsync -avz root@192.168.1.5:/config/torrents/prowlarr/   /tmp/torrent-config/prowlarr/
rsync -avz root@192.168.1.5:/config/torrents/radarr/     /tmp/torrent-config/radarr/
rsync -avz root@192.168.1.5:/config/torrents/sonarr/     /tmp/torrent-config/sonarr/
rsync -avz root@192.168.1.5:/config/torrents/lidarr/     /tmp/torrent-config/lidarr/

# qbittorrent: settings only, skip the torrent session (BT_backup/)
rsync -avz --exclude='BT_backup/' \
    root@192.168.1.5:/config/torrents/qbittorrent/ \
    /tmp/torrent-config/qbittorrent/

# Do NOT copy /incoming — will be created empty on the lab LXC
# Do NOT copy gluetun/wireguard — WireGuard is placed manually (Step 4)
```

After extraction, the live stack can be restarted if needed — but note that if
it runs simultaneously with the lab stack against the same NAS exports, two radarr
instances will conflict on imports. The simplest approach: **keep the live stack
stopped during the lab validation window.** No in-flight torrents to lose.

---

## Step 3: Provision torrent-stack-lab LXC

Create `terraform/lxc/stacks/torrent-stack-lab/stack.yaml`. This is based on
`.hold/torrent/stack.yaml` with the following changes:

- hostname: `torrent-stack-lab`
- ip_address: `192.168.55.22/24`
- zone: `dl_seg`
- `tun: true` (new field, triggers configure-tun.yml playbook)
- `mount=nfs` feature flag

```yaml
hostname: torrent-stack-lab
ip_address: "192.168.55.22/24"
gateway: "192.168.55.1"
vmid: null   # assigned by Proxmox on create
cores: 2
memory: 4096
rootfs_size: "50G"
docker_storage_size: "30G"
tags: "torrent,dl-seg,docker"
ansible_playbook: "docker-base"
portainer_agent: true
tun: true    # enables configure-tun.yml null_resource
features:
  mount: nfs
  nesting: true
```

**Run Terraform to create the LXC:**
```bash
./with-secrets terragrunt apply
```

The `configure-tun.yml` playbook (to be created, modeled on `configure-keyctl.yml`)
runs `pct set <vmid> -features nesting=1,tun=1` via SSH delegation to the pve host.
This is the same pattern already working for keyctl.

**NFS fstab (Ansible):**

The Ansible playbook adds fstab entries on the LXC for the NAS NFS mounts.
The exact NAS export paths must be confirmed from ADM before this step.

```
<nas-ip>:<export-path>/video/movies  /nas/video/movies  nfs  defaults,_netdev  0 0
<nas-ip>:<export-path>/video/tv      /nas/video/tv      nfs  defaults,_netdev  0 0
<nas-ip>:<export-path>/music         /nas/music         nfs  defaults,_netdev  0 0
```

The `/incoming` directory is local to the LXC — created by Ansible, not NFS:
```
/incoming  (owned 1000:1000, mode 0755)
```

---

## Step 4: Place config and credentials

Transfer arr configs to the lab LXC, then place WireGuard manually.

```bash
# Transfer arr configs
rsync -avz /tmp/torrent-config/prowlarr/    root@192.168.55.22:/config/torrents/prowlarr/
rsync -avz /tmp/torrent-config/radarr/      root@192.168.55.22:/config/torrents/radarr/
rsync -avz /tmp/torrent-config/sonarr/      root@192.168.55.22:/config/torrents/sonarr/
rsync -avz /tmp/torrent-config/lidarr/      root@192.168.55.22:/config/torrents/lidarr/
rsync -avz /tmp/torrent-config/qbittorrent/ root@192.168.55.22:/config/torrents/qbittorrent/

# WireGuard: copy from live LXC (or from wherever you have it safely stored)
scp root@192.168.1.5:/config/torrents/gluetun/wireguard/wg0.conf \
    root@192.168.55.22:/config/torrents/gluetun/wireguard/wg0.conf

# Verify before starting gluetun:
ssh root@192.168.55.22 ls -la /config/torrents/gluetun/wireguard/

# Clean up staging
rm -rf /tmp/torrent-config/
```

**WireGuard credentials are never committed to git or placed in SOPS.**
To update credentials from the VPN provider: replace `wg0.conf` on the LXC and
restart gluetun from Portainer.

qbittorrent starts with correct settings (categories, save paths) but no active
torrents. `/incoming` is empty and writable — new downloads land there immediately.

---

## Step 5: Deploy compose via Portainer

In Portainer (infra, mgmt_seg), create a new stack named `torrent-stack-lab`
on the `torrent-stack-lab` endpoint.

### Compose file

```yaml
services:

  docker-socket-proxy:
    image: harbor.lab.gibbsgreatly.xyz/proxy/tecnativa/docker-socket-proxy:latest
    container_name: docker-socket-proxy
    environment:
      CONTAINERS: 1
      SERVICES: 1
      TASKS: 1
      NETWORKS: 1
      NODES: 1
      INFO: 1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "2375:2375"
    restart: unless-stopped

  gluetun:
    image: harbor.lab.gibbsgreatly.xyz/proxy/qmcgaw/gluetun:latest
    container_name: gluetun
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun
    environment:
      - VPN_TYPE=wireguard
      - VPN_SERVICE_PROVIDER=custom
      - HEALTH_TARGET_ADDRESS=8.8.8.8
      - HEALTH_VPN_DURATION_INITIAL=10s
      - DOT=off
      - DNS_PLAINTEXT_ADDRESS=1.1.1.1
      - TZ=Pacific/Auckland
    volumes:
      - /config/torrents/gluetun:/gluetun
      - /config/torrents/gluetun/wireguard/wg0.conf:/run/secrets/wg0.conf:ro
    ports:
      - "8080:8888"   # qbittorrent WebUI (published by gluetun, not qbittorrent)
      - "6881:6881"   # torrent port (via VPN)
      - "6881:6881/udp"
    labels:
      # Traefik: qbittorrent WebUI is published on gluetun's network namespace
      - "traefik.enable=true"
      - "traefik.http.routers.qbittorrent.rule=Host(`qbittorrent.lab.gibbsgreatly.xyz`)"
      - "traefik.http.routers.qbittorrent.entrypoints=websecure"
      - "traefik.http.routers.qbittorrent.tls=true"
      - "traefik.http.routers.qbittorrent.middlewares=authentik@file"
      - "traefik.http.services.qbittorrent.loadbalancer.server.port=8080"
    restart: unless-stopped

  qbittorrent:
    image: harbor.lab.gibbsgreatly.xyz/proxy/linuxserver/qbittorrent:latest
    container_name: qbittorrent
    network_mode: "service:gluetun"
    depends_on:
      - gluetun
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Pacific/Auckland
      - WEBUI_PORT=8888
    volumes:
      - /config/torrents/qbittorrent:/config
      - /incoming:/downloads
    restart: unless-stopped
    # Note: no ports or Traefik labels here — qbittorrent shares gluetun's network namespace.
    # Traefik labels for the WebUI are on the gluetun container above.

  prowlarr:
    image: harbor.lab.gibbsgreatly.xyz/proxy/linuxserver/prowlarr:latest
    container_name: prowlarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Pacific/Auckland
    volumes:
      - /config/torrents/prowlarr:/config
    ports:
      - "9696:9696"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.prowlarr.rule=Host(`prowlarr.lab.gibbsgreatly.xyz`)"
      - "traefik.http.routers.prowlarr.entrypoints=websecure"
      - "traefik.http.routers.prowlarr.tls=true"
      - "traefik.http.routers.prowlarr.middlewares=authentik@file"
      - "traefik.http.services.prowlarr.loadbalancer.server.port=9696"
    restart: unless-stopped

  radarr:
    image: harbor.lab.gibbsgreatly.xyz/proxy/linuxserver/radarr:latest
    container_name: radarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Pacific/Auckland
    volumes:
      - /config/torrents/radarr:/config
      - /nas/video/movies:/movies
      - /nas/video/movies:/media/movies
      - /incoming:/downloads
    ports:
      - "7878:7878"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.radarr.rule=Host(`radarr.lab.gibbsgreatly.xyz`)"
      - "traefik.http.routers.radarr.entrypoints=websecure"
      - "traefik.http.routers.radarr.tls=true"
      - "traefik.http.routers.radarr.middlewares=authentik@file"
      - "traefik.http.services.radarr.loadbalancer.server.port=7878"
    restart: unless-stopped

  sonarr:
    image: harbor.lab.gibbsgreatly.xyz/proxy/linuxserver/sonarr:latest
    container_name: sonarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Pacific/Auckland
    volumes:
      - /config/torrents/sonarr:/config
      - /nas/video/tv:/tv
      - /nas/video/tv:/media/tv
      - /incoming:/downloads
    ports:
      - "8989:8989"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.sonarr.rule=Host(`sonarr.lab.gibbsgreatly.xyz`)"
      - "traefik.http.routers.sonarr.entrypoints=websecure"
      - "traefik.http.routers.sonarr.tls=true"
      - "traefik.http.routers.sonarr.middlewares=authentik@file"
      - "traefik.http.services.sonarr.loadbalancer.server.port=8989"
    restart: unless-stopped

  lidarr:
    image: harbor.lab.gibbsgreatly.xyz/proxy/blampe/lidarr:latest
    container_name: lidarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Pacific/Auckland
    volumes:
      - /config/torrents/lidarr:/config
      - /nas/music:/music
      - /nas/music:/media/music
      - /incoming:/downloads
    ports:
      - "8686:8686"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.lidarr.rule=Host(`lidarr.lab.gibbsgreatly.xyz`)"
      - "traefik.http.routers.lidarr.entrypoints=websecure"
      - "traefik.http.routers.lidarr.tls=true"
      - "traefik.http.routers.lidarr.middlewares=authentik@file"
      - "traefik.http.services.lidarr.loadbalancer.server.port=8686"
    restart: unless-stopped

  flaresolverr:
    image: harbor.lab.gibbsgreatly.xyz/proxy/flaresolverr/flaresolverr:latest
    container_name: flaresolverr
    environment:
      - LOG_LEVEL=info
      - TZ=Pacific/Auckland
    ports:
      - "8191:8191"
    # No Traefik labels — internal only, accessed by prowlarr via Docker bridge
    restart: unless-stopped
```

**Notes on the compose:**

- `docker-socket-proxy` must be running for Traefik to discover the other containers
- qbittorrent Traefik labels live on `gluetun` because qbittorrent shares gluetun's
  network namespace and does not have its own published port
- Internal arr-to-arr communication (prowlarr → radarr/sonarr/lidarr, arr → qbittorrent)
  uses Docker bridge hostnames and API keys — not through Traefik
- The `authentik@file` middleware is defined in Traefik's file provider config
  (already exists for other stacks); verify it's present before enabling

**Disable built-in auth in arr apps** once forwardAuth is confirmed working:
In each arr app: Settings → General → Authentication → None (since Authentik handles it).
Leave API key auth in place — intra-stack calls use API keys directly.

---

## Step 6: Validation checklist

Work through in order. Do not proceed to cutover until all pass.

### 6.1 Infrastructure

- [ ] LXC boots, Docker running
- [ ] `/dev/net/tun` exists in LXC: `ssh root@192.168.55.22 ls -la /dev/net/tun`
- [ ] NFS mounts visible: `ssh root@192.168.55.22 ls /nas/video/movies` (should list files)
- [ ] Portainer agent registered in infra Portainer at 192.168.55.22:9001
- [ ] docker-socket-proxy running: `ssh root@192.168.55.22 curl -s http://localhost:2375/containers/json | head -20`

### 6.2 VPN

- [ ] gluetun container started and healthy
- [ ] VPN tunnel established: check gluetun logs for `Wireguard: connected`
- [ ] Confirm download traffic exits via VPN IP (not home IP): trigger a test download
  in qbittorrent, check gluetun logs for connection to non-home IP

### 6.3 Traefik / Authentik

- [ ] Traefik picks up containers from docker-socket-proxy (check Traefik dashboard)
- [ ] `https://radarr.lab.gibbsgreatly.xyz` redirects to Authentik login
- [ ] After Authentik login, radarr loads correctly
- [ ] Same for sonarr, prowlarr, lidarr, qbittorrent

### 6.4 Intra-stack connectivity

- [ ] Prowlarr → radarr: Settings → Apps → radarr shows "Connected"
- [ ] Prowlarr → sonarr: same
- [ ] Prowlarr → lidarr: same
- [ ] Radarr → qbittorrent: Settings → Download Clients → shows "Connected"
- [ ] Sonarr → qbittorrent: same
- [ ] Prowlarr → flaresolverr: Settings → Indexers → FlareSolverr shows "Connected"

### 6.5 End-to-end

- [ ] Search for a movie in radarr → add → grab → appears in qbittorrent
- [ ] Download completes → radarr imports to `/nas/video/movies`
- [ ] Verify imported file visible on NAS

---

## Step 7: Traefik docker-socket-proxy registration

After validation, add `torrent-stack-lab` to Traefik's Docker provider config so
it persists across Traefik restarts. This is a change to the `proxy-stack` Traefik config:

```yaml
# In Traefik Docker provider config (proxy-stack)
# Add new provider entry pointing to the lab LXC socket proxy
providers:
  docker:
    - endpoint: "tcp://192.168.55.22:2375"
      exposedByDefault: false
```

The exact config location depends on how `proxy-stack` manages its Docker provider
entries — check `terraform/lxc/stacks/proxy-stack/` for the current provider list.

---

## Step 8: Cutover

Only proceed after all validation in Step 6 passes.

1. Confirm live stack (`torrent-stack`, 192.168.1.5) is still frozen (containers stopped)
2. Note: `/incoming` on the lab LXC started empty — any downloads started during
   lab validation period are on the lab LXC. The live stack's `/incoming` is frozen.
3. Register `torrent-stack-lab` endpoint with infra Portainer (if not already done)
4. Update any DNS entries / bookmarks pointing to old service IPs to the new Traefik hostnames
5. Remove `192.168.1.5` NFS allowlist entries from ADM (old LXC no longer active)

At this point `torrent-stack-lab` is the live stack. The old LXC at `192.168.1.5`
remains frozen with its snapshot until explicitly decommissioned.

---

## Step 9: Decommission old LXC

After running stably for at least one week on the new stack:

```bash
# Requires prod access
./with-secrets-prod pct destroy <old-vmid>
```

Remove the old endpoint from legacy Portainer (management-stack) if still registered.

---

## Revert procedure

If at any point before cutover the lab stack fails and you need to restore service:

1. Stop all containers on `torrent-stack-lab` (Portainer → stack → Stop)
2. Restore old LXC from snapshot: `./with-secrets-prod pct rollback <vmid> pre-migration-<date>`
3. Start containers on old `torrent-stack` (Portainer → stack → Start)
4. Services resume at `192.168.1.5` — legacy Portainer still manages them
5. Diagnose lab failure before retrying

The revert does not require any DNS or Traefik changes since the old stack was
frozen, not cut over.

---

## Known gaps / decisions deferred to implementation

- **lidarr image**: live stack uses `blampe/lidarr`; old code used `lscr.io/linuxserver/lidarr`.
  Confirm which is current and whether they're compatible before migrating config.
- **NAS export path**: the exact NFS export name from ADM is not yet confirmed.
  `/nas/video/movies` is the LXC-local mount path; the NAS-side export path may differ.
- **configure-tun.yml**: to be created before this sprint. Model on `configure-keyctl.yml`.
  Command: `pct set {{ vmid }} -features nesting=1,tun=1`
- **Authentik forwardAuth middleware name**: assumed `authentik@file` — verify against
  existing Traefik config in `proxy-stack`.
- **qbittorrent built-in auth**: after forwardAuth is working, disable qbittorrent's
  own web UI auth to avoid double-login. Do this via qbittorrent WebUI settings, not IaC.
- **/incoming size**: confirm current size on live stack before migration; if large,
  allow active downloads to complete or cancel before freezing.
