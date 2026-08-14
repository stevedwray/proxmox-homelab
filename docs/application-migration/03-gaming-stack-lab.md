# Sprint 03: gaming-stack-lab

Deploy the replacement gaming stack into `game_seg` (VLAN 60). The first
service is Minecraft; future AzerothCore and DayZ services are intentionally
out of scope.
Dockge UI behind Traefik + Authentik. Game server ports direct via MikroTik.

**Detail level:** Sketch — flesh out before starting this sprint.

---

## Current state

**Legacy stack:** `gaming-stack-legacy` (CT 103) at `192.168.1.7`, Portainer
endpoint `tcp://192.168.1.7:9001`

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
- Minecraft: TCP/25565 — direct LAN access (no Traefik)
- No internet exposure for game ports (LAN-only)

---

## Pre-conditions (to flesh out)

- [ ] `game_seg` (VLAN 60) defined and applied
- [ ] MikroTik rules: `LAN → game_seg tcp/25565` and `mgmt_seg → game_seg tcp/9001`
- [ ] Lab Portainer is reachable from `game_seg` for agent registration
- [ ] Minecraft tarball inspected and its NeoForge/Java/runtime requirements recorded

---

## Key considerations

- **Dedicated storage**: `/srv/docker` is a backup-included, grow-only ZFS
  mount from `gaming-containers`, separate from Docker engine state.
- **Compose layout**: Minecraft projects live in
  `/srv/docker/minecraft/<server-name>/`; future game types use their own
  top-level directories but are not implemented now.
- **Legacy handover**: copy `ops.json` and `whitelist.json` from
  `/minecraft/foreverworld`; do not migrate the legacy world unless explicitly
  requested.
- Traefik is not involved in game server ports, and Dockge is not part of the
  replacement architecture.

---

## Steps (to be detailed)

1. Validate `game_seg` end-to-end on pve-test-vm.
2. Provision `gaming-stack-lab` alongside the legacy LXC with its dedicated
   `gaming-containers` volume.
3. Register its agent with lab Portainer.
4. Inspect the supplied Wildworks Minecraft tarball and write the NeoForge
   Foreverworld compose project under `/srv/docker/minecraft/foreverworld/`.
5. Carry forward ops and whitelist settings, then test TCP/25565 from the LAN.
6. Retain the legacy LXC as the rollback target; do not decommission it in
   this phase.
