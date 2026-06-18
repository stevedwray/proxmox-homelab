# Sprint 03: gaming-stack-lab

Deploy gaming stack (Dockge + Minecraft/ARK servers) into `game_seg` (VLAN 60).
Dockge UI behind Traefik + Authentik. Game server ports direct via MikroTik.

**Detail level:** Sketch — flesh out before starting this sprint.

---

## Current state

**Live stack:** `gaming-stack` at `192.168.1.7`, Portainer endpoint `tcp://192.168.1.7:9001`

| Container | State | Data |
|---|---|---|
| dockge | running (port 5001) | `/opt/dockge/`, `/ark/` |
| portainer-agent | running (port 9001) | — |
| newworld-minecraft | exited | — |
| various ARK servers | exited | `/ark/` (game world data) |

**ARK server images:** currently referenced by SHA256 digest, not tags. Identifying
the correct image tags is a pre-condition for Harbor mirroring.

**Storage:** All game world data is in `/ark/` on the LXC filesystem (no NFS). This
directory must be preserved. It is potentially large.

---

## Target architecture

- `gaming-stack-lab` at `192.168.60.10/24`, gateway `192.168.60.1`
- Zone: `game_seg`, VLAN 60
- Dockge UI: `dockge.lab.gibbsgreatly.xyz` → Traefik + Authentik forwardAuth
- Minecraft: tcp+udp/25565 — direct LAN access (no Traefik)
- ARK: udp/7777, 7778, 27015 per server — direct LAN access (no Traefik)
- No internet exposure for game ports (LAN-only; ARK WAN port-forward deferred)

---

## Pre-conditions (to flesh out)

- [ ] `game_seg` (VLAN 60) defined and applied
- [ ] MikroTik rules: `LAN → game_seg tcp+udp/25565`, `LAN → game_seg udp/7777,7778,27015`
- [ ] `edge_seg → game_seg tcp/5001,2375` and `mgmt_seg → game_seg tcp/9001`
- [ ] Harbor images mirrored: `louislam/dockge:1`, `itzg/minecraft-server:stable-java21`
- [ ] ARK image SHA256 digests identified and tagged — check live LXC `docker images`
- [ ] `/ark/` size estimated — this is a large copy, plan for downtime or sequential copy

---

## Key considerations

- **`/ark/` migration**: game world data is LXC-local, no NFS. Options:
  - Rsync `/ark/` from live LXC to lab LXC while servers are stopped (safe)
  - Or: provision new LXC alongside, rsync, then freeze live and do final rsync
- **Dockge**: manages ARK stacks via compose files in `/opt/stacks/`. The compose files
  reference ARK image digests — update to Harbor-mirrored images with proper tags
- **ARK port ranges**: multiple ARK servers need separate port assignments; map current
  port usage from the live stack before migrating
- **Minecraft servers**: most are exited on the live stack; confirm which worlds are
  active before migration
- Traefik is not involved in game server ports; only Dockge UI goes through Traefik

---

## Steps (to be detailed)

1. Inventory ARK image digests and map to tags (`docker inspect` on live LXC)
2. Identify active Minecraft worlds
3. Size `/ark/` directory
4. Freeze live stack, snapshot LXC
5. Rsync `/opt/dockge/` and `/ark/` to staging
6. Provision `gaming-stack-lab` LXC in `game_seg`
7. Transfer data, deploy Dockge via Portainer
8. Verify game server configs, update image references to Harbor
9. Start one server at a time, test connectivity from LAN
10. Cutover and decommission
