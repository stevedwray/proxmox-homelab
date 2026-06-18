# Sprint 02: media-stack-lab

Deploy Jellyfin into `media_seg` (VLAN 50) as `media-stack-lab`, with Traefik routing
and Authentik OIDC integration. Reuse config and library metadata from the live stack.

**Detail level:** Sketch — flesh out before starting this sprint.

---

## Current state

**Live stack:** `media-stack` at `192.168.1.6`, Portainer endpoint `tcp://192.168.1.6:9001`

| Container | Image | Ports |
|---|---|---|
| jellyfin | lscr.io/linuxserver/jellyfin:latest | 1900, 7359, 8096, 8920 |

**Config and data:**
- `/config/jellyfin` — library DB, metadata, user accounts (local to LXC)
- `/nas-media/video/movies`, `/nas-media/video/tv`, `/nas-media/music` — NFS from NAS

---

## Target architecture

- `media-stack-lab` at `192.168.50.21/24`, gateway `192.168.50.1`
- Zone: `media_seg`, VLAN 50
- Auth: Authentik **OIDC** (not forwardAuth) — Jellyfin has native OIDC support
  - Users authenticate via Authentik; Jellyfin maps Authentik users to local accounts
  - Per-user library permissions managed in Jellyfin
- Traefik route: `jellyfin.lab.gibbsgreatly.xyz → 192.168.50.21:8096`
- No DLNA needed (confirmed — no clients use DLNA discovery)

---

## Pre-conditions (to flesh out)

- [ ] `media_seg` (VLAN 50) defined and applied
- [ ] MikroTik rules: `media_seg → 192.168.1.3:2049`, `edge_seg → media_seg:8096,2375`, `mgmt_seg → media_seg:9001`
- [ ] Harbor: `lscr.io/linuxserver/jellyfin` mirrored
- [ ] GPU passthrough status confirmed (check pve LXC config — requires prod access)
  - If Jellyfin uses hardware transcoding, the new LXC needs the same device passthrough
- [ ] Authentik OIDC provider created for Jellyfin application
- [ ] NAS export path for `/nas-media/` confirmed from ADM

---

## Key differences from sprint 01

- Auth is OIDC not forwardAuth — requires Authentik application + OIDC provider setup,
  and Jellyfin config: Dashboard → Authentication → OIDC
- `/config/jellyfin` rsync includes the library DB and metadata cache — can be large
- Hardware transcoding (if in use): LXC needs device passthrough, confirm current config
- No intra-stack service mesh — Jellyfin is a single container

---

## Steps (to be detailed)

1. Freeze live stack, snapshot LXC
2. Rsync `/config/jellyfin` to staging
3. Provision `media-stack-lab` LXC in `media_seg`
4. Transfer config, mount NFS, verify library visible
5. Configure Authentik OIDC provider for Jellyfin
6. Deploy compose via Portainer with Traefik labels
7. Validate: Jellyfin loads, Authentik SSO works, library scans, playback works
8. Cutover and decommission

---

## Open questions

- GPU/hardware transcoding passthrough: does the live LXC have device passthrough configured?
  Check with `./with-secrets-prod pvesh get /nodes/pve/lxc/<vmid>/config`
- `/config/jellyfin` size estimate — metadata cache can be many GB
- Jellyfin version pinning: the live stack runs `:latest` — confirm version before migrating
  config, since DB migrations can be one-way
