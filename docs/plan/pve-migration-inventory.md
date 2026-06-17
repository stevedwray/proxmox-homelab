# pve Container Migration Inventory

**Purpose:** Current-state inventory of all containers/VMs on the production `pve` host
that are not yet managed by this infrastructure stack. Used to plan gradual, safe
migration to the SDN VLAN zones.

**Last updated:** 2026-06-18 (via Portainer API discovery)

**Discovery method:** Portainer API at `management-stack.gibbsgreatly.xyz:9443`
(no SSH required). Proxmox API discovery of the `pve` node requires prod credentials
(`./with-secrets-prod`) and has not been run yet — VMIDs and bridge config for most
containers are unconfirmed.

---

## Summary Table

| Container | Current IP | Zone Target | Status | Data at risk | Priority |
|---|---|---|---|---|---|
| management-stack | 192.168.1.70 | decomm / split | running | NPM config, central-registry blobs | low |
| media-stack | 192.168.1.6 | `app_seg` | running | NFS: `/nas-media/` | medium |
| torrent-stack | 192.168.1.5 | `app_seg` | running | NFS: `/nas/`, VPN config, `/incoming` | medium |
| gaming-stack | 192.168.1.7 | `game_seg` | running (dockge only) | `/ark/` game world data | low |
| elastic-stack | 192.168.1.24 | unknown/decomm | Portainer agent only | unknown | low |
| analysis-stack | 192.168.1.16 | unknown | offline | unknown | low |
| security-stack | 192.168.1.11 | unknown | offline | unknown | low |
| wazuh | unknown | `mgmt_seg`? | unknown | unknown | investigate |
| omada-controller | unknown | `mgmt_seg` | unknown | SDN controller config | investigate |
| cloud-stack | unknown | `app_seg`? | unknown | unknown (nextcloud?) | investigate |
| ai-stack | unknown | unknown | unknown | model weights? | investigate |
| scanning-stack | unknown | `mgmt_seg`? | unknown | unknown | investigate |
| proxmox-backup-server | unknown | `infra_seg` | unknown | backup store | investigate |
| debian13-template-builder | unknown | — | unknown | builder only — no persistent data | ignore |

---

## NFS / External Storage Dependencies

**Critical pre-condition for media and torrent migration: NFS mounts must be accessible
from the new VLAN zones before migration.**

### media-stack mounts (from Jellyfin container)

| LXC mount path | Container path | Purpose |
|---|---|---|
| `/nas-media/video/movies` | `/movies` | Jellyfin movie library |
| `/nas-media/video/tv` | `/tv` | Jellyfin TV library |
| `/nas-media/music` | `/music` | Jellyfin music library |
| `/config/jellyfin` | `/config` | Jellyfin config/metadata (local to LXC) |

### torrent-stack mounts (arr stack containers)

| LXC mount path | Container path | Service | Purpose |
|---|---|---|---|
| `/incoming` | `/downloads` | qbittorrent, radarr, sonarr, lidarr | Download landing zone |
| `/nas/video/movies` | `/movies` + `/media/movies` | radarr | Media library (movies) |
| `/nas/video/tv` | `/tv` + `/media/tv` | sonarr | Media library (TV) |
| `/nas/music` | `/music` + `/media/music` | lidarr | Media library (music) |
| `/config/torrents/<service>` | `/config` | all | Per-service config (local to LXC) |
| `/config/torrents/gluetun/wireguard` | `/gluetun/wireguard` | gluetun | WireGuard VPN credentials |

### NAS identity

The media-stack uses `/nas-media/...` while torrent-stack uses `/nas/...` — these are
different mount points on the same or different NAS. Confirm NAS IP and export paths
before migration. MikroTik firewall rules must allow `app_seg` → NAS IP on port 2049 (NFS).

---

## Container Detail

### management-stack @ 192.168.1.70

**Services running:**

| Container | Image | Ports | Data |
|---|---|---|---|
| portainer | portainer/portainer-ce:latest | 8000, 9000, 9443 | named vol `portainer_data` |
| portainer-agent | portainer/agent:2.21.1 | 9001 | bind `/var/run/docker.sock` |
| nginx-proxy-manager | jc21/nginx-proxy-manager:latest | 80, 81, 443 | bind `/srv/npm/data`, `/srv/npm/letsencrypt` |
| central-registry | registry:2.8.3 | 5000 | named vol `harbor_registry_data` |
| registry-ui | joxit/docker-registry-ui:latest | 5001 | — |
| trivy-scanner | aquasec/trivy:latest | 4954 | named vol `harbor_trivy_cache` |

**Migration plan:**
- **Portainer CE** → already replaced by Portainer in `portainer-stack` on the SDN. Management-stack
  Portainer can be decommissioned after all managed endpoints are re-registered to the new Portainer.
- **Nginx Proxy Manager** → must inventory all active proxy routes before decommissioning.
  Routes should move to Traefik labels in each service's stack. NPM admin port 81 was not
  reachable from the LAN — needs investigation from within the management LXC.
- **central-registry** → data volume `harbor_registry_data` contains cached image blobs from
  before Harbor was set up. Evaluate whether any of these images need migrating to Harbor or
  can be discarded (re-pulled from upstream).
- **registry-ui, trivy-scanner** → decommission; Harbor has built-in Trivy and UI.

**Migration target:** Portainer moves to `portainer-stack` on SDN (already exists). The LXC
itself can be decommissioned once all endpoints are re-homed and NPM routes are inventoried.

---

### media-stack @ 192.168.1.6

**Services running:**

| Container | Image | Ports | Data |
|---|---|---|---|
| jellyfin | lscr.io/linuxserver/jellyfin:latest | 1900, 7359, 8096, 8920 | bind `/config/jellyfin`, NFS `/nas-media/...` |

**Migration plan:**
- Target: new `app_seg` VLAN (see `phase-06-app-stacks.md`)
- Create `terraform/lxc/stacks/media-stack/stack.yaml` with `app_seg` zone
- Snapshot LXC before migration; backup `/config/jellyfin` (metadata, library DB, users)
- New LXC needs NFS access to `/nas-media/video/movies`, `/nas-media/video/tv`, `/nas-media/music`
  → MikroTik must permit `app_seg` → NAS on tcp+udp/2049
- Hardware transcoding: check if Jellyfin is using GPU passthrough (inspect LXC config on pve;
  requires prod access). If yes, LXC config needs device passthrough entries.
- Port 1900 (DLNA/SSDP discovery) — UDP multicast; may not work across VLANs. Document if
  any clients use DLNA discovery.

**Note:** `.hold/media/stack.yaml` has stale IP (192.168.1.80). Actual current IP is 192.168.1.6.

---

### torrent-stack @ 192.168.1.5

**Services running:**

| Container | Image | Ports | Data |
|---|---|---|---|
| gluetun (VPN) | qmcgaw/gluetun | 6881, 8000, 8080, 8388 | bind `/config/torrents/gluetun` |
| qbittorrent | lscr.io/linuxserver/qbittorrent | — (via gluetun) | bind `/config/torrents/qbittorrent`, `/incoming` |
| prowlarr | lscr.io/linuxserver/prowlarr:latest | 9696 | bind `/config/torrents/prowlarr` |
| radarr | lscr.io/linuxserver/radarr:latest | 7878 | bind `/config/torrents/radarr`, NFS `/nas/video/movies` |
| sonarr | lscr.io/linuxserver/sonarr:latest | 8989 | bind `/config/torrents/sonarr`, NFS `/nas/video/tv` |
| lidarr | blampe/lidarr:latest | 8686 | bind `/config/torrents/lidarr`, NFS `/nas/music` |
| flaresolverr | ghcr.io/flaresolverr/flaresolverr:latest | 8191, 8192 | named volume |

**VPN dependency:** gluetun provides a VPN exit for all download traffic. The WireGuard
config is in `/config/torrents/gluetun/wireguard` (contains private key + endpoint).
This must be migrated intact. VPN credentials come from a secret (not in SOPS — stored
directly in the wireguard config file on-disk).

**Migration plan:**
- Target: new `app_seg` VLAN
- Snapshot LXC and backup `/config/torrents/` before migration
- `/incoming` is the in-progress downloads directory — confirm size before migrating
- All `lscr.io/linuxserver` images must be mirrored to Harbor before deployment
- `ghcr.io/flaresolverr/flaresolverr` must be mirrored to Harbor
- `blampe/lidarr` must be mirrored to Harbor
- qmcgaw/gluetun must be mirrored to Harbor
- New LXC needs NFS access: `app_seg` → NAS
- gluetun VPN: the container needs internet egress on port 51820 (WireGuard).
  MikroTik must permit `app_seg` → internet on udp/51820.

**Note:** `.hold/torrent/stack.yaml` has stale IP (192.168.1.72). Actual current IP is 192.168.1.5.

---

### gaming-stack @ 192.168.1.7

**Services running:**

| Container | Image | Ports | State | Data |
|---|---|---|---|---|
| dockge | louislam/dockge:1 | 5001 | running | bind `/opt/dockge`, `/ark` |
| portainer-agent | portainer/agent:2.21.1 | 9001 | running | — |
| newworld-minecraft | itzg/minecraft-server:stable-java21 | — | exited | — |
| various ARK servers | (image hash) | — | exited | in `/ark/` |

**Storage:** All game world data is in `/ark/` on the LXC filesystem (bind-mounted by Dockge
into `/opt/stacks`). No named Docker volumes. The ARK server images are referenced by SHA256
digest (not tags) — these need to be pulled and tagged before Harbor mirroring.

**Migration plan:**
- Target: new `game_seg` VLAN
- Snapshot LXC; backup `/ark/` directory (game world data)
- Game servers need direct port access (not through Traefik):
  - Minecraft: tcp+udp/25565
  - ARK: udp/7777, udp/7778, udp/27015
  MikroTik must expose these ports from `game_seg` to clients
- Dockge on port 5001 manages the game stacks — protect or replace with proper stack.yaml
- ARK and Minecraft images by digest must be identified and mirrored to Harbor

**Note:** `.hold/minecraft/stack.yaml` has stale IP (192.168.1.73). Actual current IP is 192.168.1.7.
  `.hold/minecraft/stack.yaml` also doesn't capture ARK servers. gaming-stack is a superset.

---

### elastic-stack @ 192.168.1.24

**Services running:** Only `portainer/agent:2.21.1` (port 9001). No Elasticsearch or
Kibana containers visible. The elastic services may have been stopped or the image was
never deployed, leaving just the Portainer agent.

**Migration plan:** Confirm whether Elasticsearch is actually in use. If yes, identify
what's sending data to it and plan accordingly. If no, decommission this endpoint.

---

### analysis-stack @ 192.168.1.16

**Status:** Portainer endpoint offline. Cannot inspect via Portainer API.
**Requires:** Prod access (`./with-secrets-prod`) to inspect via Proxmox API or direct
connection.

---

### security-stack @ 192.168.1.11

**Status:** Portainer endpoint offline. Cannot inspect via Portainer API.
**Requires:** Prod access to inspect.

---

## Containers Not in Portainer

These appear in NetBox (discovered by populate.py via Proxmox API on a prior run) but
have no Portainer agent and cannot be inspected without prod access.

| Name | NetBox ID | Notes |
|---|---|---|
| wazuh | 14 | SIEM. Likely a standalone QEMU VM or LXC without Docker. |
| omada-controller | 21 | TP-Link Omada SDN controller. Likely a QEMU VM. Critical — controls VLAN switching on MikroTik/Omada switches. Migrate with extreme care. |
| cloud-stack | 25 | Unknown. May be Nextcloud (a Portainer stack named "nextcloud" was found against a deleted endpoint ep-14). |
| ai-stack | 26 | Unknown. Likely AI/ML services with large model weight data. |
| scanning-stack | 13 | Unknown. Possibly Trivy or Nessus. |
| proxmox-backup-server | 20 | PBS. Manages backups for pve. Not a migration target — keep in place or migrate to new zone carefully. |
| debian13-template-builder | 23 | Template builder VM. No persistent service data. Rebuild on demand. |

---

## Migration Prerequisites

Before any pve container can be migrated to the SDN:

1. **New SDN zones defined** in `terraform/lxc/network/pve.yaml`:
   - `app_seg`: VLAN for media, arr stack (propose VLAN 50, subnet TBD)
   - `game_seg`: VLAN for game servers (propose VLAN 60, subnet TBD)
   - These match the subnets in `phase-06-app-stacks.md`: `10.60.0.0/24` and `10.61.0.0/24`

2. **MikroTik firewall rules** for new zones:
   - `app_seg` → NAS (NFS tcp+udp/2049)
   - `app_seg` → internet udp/51820 (gluetun WireGuard)
   - `game_seg` → internet tcp+udp/25565 (Minecraft), udp/7777-7778, udp/27015 (ARK)
   - `app_seg` → `infra_seg` tcp/80,443,3142 (Harbor, apt-cacher) — already in all_zones policy

3. **Harbor image mirroring** for all images currently from docker.io/lscr.io/ghcr.io:
   - `lscr.io/linuxserver/jellyfin`
   - `lscr.io/linuxserver/qbittorrent`
   - `lscr.io/linuxserver/prowlarr`
   - `lscr.io/linuxserver/radarr`
   - `lscr.io/linuxserver/sonarr`
   - `blampe/lidarr`
   - `ghcr.io/flaresolverr/flaresolverr`
   - `qmcgaw/gluetun`
   - `itzg/minecraft-server`
   - ARK server images (SHA256 digest — need tags identified)

4. **NPM route inventory**: Document all active proxy routes in NPM on management-stack.
   These must move to Traefik labels before NPM is decommissioned. NPM admin UI is at
   `http://192.168.1.70:81` (requires LAN access).

5. **NAS IP confirmation**: What is the NAS IP? Confirm NFS export paths and ensure
   they match what's in container mount paths (`/nas-media/...` and `/nas/...`).

---

## Gaps Requiring Production Access

The following cannot be determined without `./with-secrets-prod` access to the pve API:

- VMID and current bridge assignment for: wazuh, omada-controller, cloud-stack,
  ai-stack, scanning-stack, proxmox-backup-server
- Whether analysis-stack and security-stack are LXCs or QEMU VMs, and what's running
- Whether Jellyfin on media-stack uses GPU/hardware transcoding passthrough
- Whether elastic-stack services are truly stopped or running in a different process

To fill these gaps, run:
```bash
# Preflight: read-only query of pve node
./with-secrets-prod pvesh get /nodes/pve/lxc
./with-secrets-prod pvesh get /nodes/pve/qemu
```

---

## Update Strategy for This Document

Re-run discovery with:
```bash
./with-secrets python3 -c "
import os, sys, json, urllib.request, ssl
sys.path.insert(0, 'terraform/lxc/stacks/netbox-stack/integrations')
portainer_url = 'https://management-stack.gibbsgreatly.xyz:9443'
token = os.environ['PORTAINER_TOKEN']
# ... (see scripts/discover-pve-portainer.py)
"
```

When pve Proxmox credentials are available, use `proxmox_client.py` targeted at
`pve.gibbsgreatly.xyz` with `PVE_READONLY_TOKEN_ID` from prod secrets.
