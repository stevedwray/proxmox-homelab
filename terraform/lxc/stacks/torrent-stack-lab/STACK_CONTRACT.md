# torrent-stack-lab — Stack Contract

## Purpose

Replaces legacy `torrent-stack` (VMID 100, flat LAN, unauthenticated)
via a fresh config install — no arr database, quality profile, or
qBittorrent setting is carried over, since the live stack's
indexer/VPN config has been unreliable and isn't worth migrating.
Directly reuses legacy's real NAS library content (the same
`/nas-media/...` export `media-stack-lab` already mounts) and its own
local `/incoming` staging filesystem, rather than migrating either —
there's nothing to copy, since legacy's downloads already land in that
same real NAS content. Adds Jellyseerr for request integration with
Jellyfin/Radarr/Sonarr, the one addition that makes this "integrated"
with `media-stack-lab` rather than a bolt-on. Standing up alongside
legacy, additive not destructive, same framing as `media-stack-lab`'s
own relationship to legacy `media-stack`. See
`docs/torrent-stack-modernization/plan.md` for the full design,
research, and step-by-step build history.

## Network

| Field        | Value                          |
|--------------|--------------------------------|
| Zone         | `media_seg` (VLAN 80)          |
| IP           | `192.168.80.11/24`             |
| Gateway      | `192.168.80.1`                 |
| VMID         | 80011                          |

Firewall (see `torrent-lab-08-network-policy` in `plan.md`):
`edge_seg → media_seg tcp/9696,7878,8989,8686,8080,5055` (Traefik to
prowlarr/radarr/sonarr/lidarr/qbittorrent-via-gluetun/jellyseerr — a
new rule, added alongside the existing Jellyfin/Immich one rather than
widening it), `media_seg → internet udp/51820` (gluetun's WireGuard
tunnel — a new rule, the same real gap the superseded
`docs/application-migration/01-torrent-stack-lab.md` plan identified
for its abandoned `dl_seg` zone). All of `media_seg`'s existing rules
(`→ 192.168.1.3 tcp+udp/2049` NAS NFS, `→ mgmt_seg tcp/9443`,
`→ 192.168.20.14 tcp/514` Graylog, `→ 192.168.20.11 tcp/443` step-ca)
apply to this stack too, unmodified.

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `LAB_DOMAIN` | `.env` | Already exists — used for all six Traefik route hostnames. |
| `LAB_IP_TORRENT_STACK_LAB` | `.env` | `192.168.80.11`, added by `torrent-lab-01-env-ip`. |

No SOPS secrets. WireGuard credentials are placed manually on the LXC
(`/opt/stacks/torrent-stack-lab/gluetun/wireguard/wg0.conf`), never
committed or SOPS'd — same rule legacy torrent-stack already follows.
None of the six web services template any Authentik/OIDC credential —
five use `forwardAuth` (auth happens entirely at the Traefik/Authentik
edge, invisible to the container), and Jellyseerr uses `auth.mode:
none` with its own built-in "Sign in with Jellyfin" login instead.

## Provides

| Service     | Port | Protocol | Notes |
|-------------|------|----------|-------|
| qbittorrent | 8080 | tcp      | WebUI, published by `gluetun` (shares its network namespace). |
| prowlarr    | 9696 | tcp      | Indexer manager. |
| radarr      | 7878 | tcp      | Movie library automation. |
| sonarr      | 8989 | tcp      | TV library automation. |
| lidarr      | 8686 | tcp      | Music library automation. |
| jellyseerr  | 5055 | tcp      | Request portal — household-facing, not admin-only. |

`flaresolverr` is internal-only (no published route — reached by
prowlarr at `http://flaresolverr:8191` over the Compose bridge
network), matching the legacy stack's own convention.

## Dependencies

None at the platform level (`depends_on: []` in `stack.yaml`). Real
runtime dependencies:

- The same NAS NFS export `media-stack-lab` already mounts
  (`192.168.1.3`, flat LAN — not a zone), via the shared `/mnt/nas-media`
  Proxmox host bind mount (`mp0`). Not owned by this stack.
- Legacy torrent-stack's own local `/incoming` staging filesystem
  (`/storage/ct-100/incoming` on the `pve` host, confirmed live
  2026-09-12 to be a real bind mount, not a Proxmox-managed volume),
  shared via `mp1` — reused, not owned, and shared *concurrently* with
  legacy's own still-running qBittorrent (see What Must Not Be Edited
  Casually).
- Authentik, for `forwardAuth`, on five of the six routes
  (qbittorrent, prowlarr, radarr, sonarr, lidarr) once `edge.yaml` is
  live. Jellyseerr has no Authentik dependency at all — it gates
  itself.

## Persistent State

| Path | Storage | Contents |
|------|---------|----------|
| `gluetun-config` | Docker named volume | gluetun's own state |
| `qbittorrent-config` | Docker named volume | qBittorrent settings (categories, save paths, limits) |
| `prowlarr-config` | Docker named volume | Indexer configs, tracker API keys |
| `radarr-config` | Docker named volume | Movie library DB, quality profiles |
| `sonarr-config` | Docker named volume | TV library DB, quality profiles |
| `lidarr-config` | Docker named volume | Music library DB |
| `jellyseerr-config` | Docker named volume | Jellyseerr's own users/requests DB |
| `/nas-media/video/movies`, `/nas-media/video/tv`, `/nas-media/music` | NFS (NAS `192.168.1.3`), shared not owned | Media library — shared with `media-stack-lab`'s Jellyfin, same real content legacy torrent-stack already deposits into |
| `/incoming` | Local disk (`pve` host, `/storage/ct-100/incoming`), shared not owned | In-progress and completed torrent staging — shared with legacy torrent-stack's own qBittorrent |

The 7 named Docker volumes above are the only state this stack
actually owns.

## What May Depend on This Stack

Nothing yet. A leaf stack.

## What Must Not Be Edited Casually

- The `/nas-media` path must keep matching `media-stack-lab`'s own
  mount so both stacks read/write the same library.
- `/incoming` is shared, concurrently, with legacy torrent-stack's own
  still-running qBittorrent — accepted by the operator as a temporary
  state (2026-09-12), not a long-term design. Real risk: duplicate
  downloads of the same torrent, category-folder collisions, or one
  instance's cleanup removing a file the other still references.
  Revisit (give this stack its own directory) once legacy is
  decommissioned or the overlap proves actively troublesome.
- WireGuard credentials at
  `/opt/stacks/torrent-stack-lab/gluetun/wireguard/wg0.conf` are never
  committed or SOPS'd.
- Legacy torrent-stack (VMID 100) is never stopped, restarted, or has
  its own config/database written to by anything in this stack's
  deploy path — sharing `/incoming`'s files is the one deliberate
  exception to "never touch legacy."
- Jellyseerr's `auth.mode: none` in `edge.yaml` is deliberate, not an
  oversight — do not "fix" it to `forwardAuth` to match the other five
  routes; that would block any household member without a full
  Authentik lab account from reaching Jellyseerr's own login at all.
- qBittorrent's WebUI Host-header allowlist needs
  `qbittorrent.${LAB_DOMAIN}` added (WebUI → Options → Web UI) or it
  will reject proxied requests — easy to mistake for a broken
  forwardAuth setup.

## Playbook

`deploy-torrent-stack-lab`

Docker Compose workload (`lxc_base` + `docker_base` + `portainer_agent`
roles), one compose file, 7 services. Jellyseerr's Jellyfin/Radarr/
Sonarr connections (API keys) and each app's own auth configuration
are one-time UI steps done after first boot — not templated into the
compose file or this playbook.
