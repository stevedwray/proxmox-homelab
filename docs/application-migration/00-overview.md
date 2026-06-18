# Application Stack Migration — Overview

Migration of legacy pve LAN-bridge application stacks into SDN VLAN zones,
with Traefik + Authentik integration where applicable.

---

## Zone Map (agreed design)

```
VLAN 50  media_seg    192.168.50.0/24   Jellyfin
VLAN 55  dl_seg       192.168.55.0/24   Torrent stack (gluetun + arr)
VLAN 60  game_seg     192.168.60.0/24   Gaming (Minecraft, ARK, Dockge)
VLAN 40  infra_seg    192.168.40.0/24   Harbor, apt-cacher, NetBox, PBS (existing + additions)

LAN bridge (192.168.1.0/24, permanent)
  NAS 192.168.1.3 — single port, stays on LAN, no VLAN migration
  pve host — permanent
```

---

## Sprint Plan

| Sprint | Stack | Status | Detail level |
|---|---|---|---|
| [01](01-torrent-stack-lab.md) | torrent-stack → dl_seg | planned | Full |
| [02](02-media-stack-lab.md) | media-stack → media_seg | planned | Sketch |
| [03](03-gaming-stack-lab.md) | gaming-stack → game_seg | planned | Sketch |
| [04](04-pbs-migration.md) | PBS → infra_seg | planned | Sketch |
| [05](05-management-decommission.md) | management-stack decommission | planned | Sketch |

Sprint 01 is the template. Later sprints will be fleshed out as each approaches.

---

## Common Principles

### Freeze-first, lab-second

Every migration follows the same pattern:

1. **Freeze** the live stack — stop all containers, take an LXC snapshot
2. **Deploy** `<name>-lab` in the target VLAN alongside the frozen stack
3. **Validate** the lab stack fully before any cutover
4. **Cutover** — start lab stack, confirm, decommission old LXC
5. **Revert path** — old LXC snapshot always available until explicitly destroyed

The live stack is never modified until the lab stack is fully validated. The two
can coexist: the old LXC stays frozen, the lab runs in the new VLAN.

### Naming convention

- Live stack: `torrent-stack` (current hostname)
- Lab stack: `torrent-stack-lab` (new hostname during testing)
- After cutover: lab stack is renamed/re-deployed as `torrent-stack`

### Data reuse

Config directories are rsynced from the live stack to the lab LXC before first boot.
NFS mounts point to the same NAS exports. The lab stack runs against real config data
from day one — no synthetic test data.

WireGuard credentials are placed manually on the lab LXC before starting gluetun.
They are not in SOPS and are not managed by IaC.

### Portainer ownership model

IaC (Terraform + Ansible) owns: LXC lifecycle, OS config, Docker, Portainer agent
registration, directory scaffold, NFS mounts, TUN device feature.

Portainer owns: compose stack deployment, service start/stop, image updates,
stack-level environment config.

Traefik labels live in the compose file managed by Portainer, not in IaC.

### Auth model

| Service type | Auth |
|---|---|
| arr UIs (radarr, sonarr, prowlarr, lidarr) | Authentik forwardAuth |
| qbittorrent WebUI | Authentik forwardAuth |
| Jellyfin | Authentik OIDC (native integration) |
| Dockge | Authentik forwardAuth |
| Game servers | None (direct TCP/UDP) |

### Traefik discovery

Each app LXC runs a `docker-socket-proxy` sidecar. Traefik polls it at
`<lxc-ip>:2375`. Labels in Portainer-managed compose files are auto-discovered.

MikroTik rule required per zone: `edge_seg → <zone>:2375`

---

## Common Pre-conditions (all sprints)

These must exist before any sprint begins:

- [ ] `dl_seg`, `media_seg`, `game_seg` defined in `terraform/lxc/network/pve.yaml`
- [ ] MikroTik VLAN interfaces and inter-zone rules applied
- [ ] Infra Portainer in `mgmt_seg` is reachable and running
- [ ] Harbor image mirroring complete for the target sprint's images
- [ ] `edge_seg → <target-zone>:2375` MikroTik rule in place
- [ ] `mgmt_seg → <target-zone>:9001` MikroTik rule in place

---

## NAS Access (all sprints using NFS)

NAS stays permanently at `192.168.1.3` on the LAN bridge. No VLAN migration.

Two-layer NFS access control:
1. **MikroTik**: allow `<zone> → 192.168.1.3 tcp+udp/2049`
2. **ADM NFS share permissions**: add new LXC IPs to the per-share allowlist in ADM;
   remove old LAN IPs (192.168.1.x) after cutover

NFS export paths to confirm against live stack before each sprint:
- Torrent stack: `/nas/video/movies`, `/nas/video/tv`, `/nas/music` (confirm exact NAS export)
- Media stack: `/nas-media/video/movies`, `/nas-media/video/tv`, `/nas-media/music`
