# media-stack-lab — Stack Contract

## Purpose

Combined Jellyfin + Immich media stack, standing up alongside legacy
`media-stack` (VMID 102) rather than replacing it. Brings Jellyfin's
existing users and watch history across from the legacy stack
(`media-lab-07`) and adds Immich as a new photo/video service. Legacy
`media-stack` keeps running, untouched, for as long as the operator
wants — retiring it is a separate, future, operator-initiated decision
this stack does not assume or schedule.

See `docs/media-stack-lab/plan.md` for the full design, research, and
step-by-step build history.

## Network

| Field        | Value                          |
|--------------|--------------------------------|
| Zone         | `media_seg` (VLAN 80)          |
| IP           | `192.168.80.10/24`             |
| Gateway      | `192.168.80.1`                 |
| VMID         | 80010                          |

Firewall: `edge_seg → media_seg tcp/8096,2283` (Traefik to Jellyfin and
Immich web UIs), `media_seg → mgmt_seg tcp/9443` (Authentik OIDC),
`media_seg → 192.168.1.3 tcp+udp/2049` (NAS NFS exports — flat LAN host,
not a zone).

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `MEDIA_STACK_LAB_DB_PASSWORD` | SOPS `terraform/secrets.common.enc.yaml` | Added 2026-09-04 via `sops --set` (random 48-char hex). Immich's Postgres password. |
| `IMMICH_OAUTH_CLIENT_ID` / `IMMICH_OAUTH_CLIENT_SECRET` | SOPS | Added by `media-lab-04`, consumed by `media-lab-05`'s `immich-config.json.j2` template. Not present yet. |
| `JELLYFIN_OAUTH_CLIENT_ID` / `JELLYFIN_OAUTH_CLIENT_SECRET` | SOPS | Added by `media-lab-04`, typed into Jellyfin's Authentik SSO plugin manually in `media-lab-06`. Not present yet. |
| `LAB_DOMAIN` | `.env` | Already exists — used for Jellyfin's `JELLYFIN_PublishedServerUrl` and both Traefik routes. |
| `IMMICH_VERSION` | `.env` (optional) | Defaults to `release` (Immich's own rolling-stable tag) if unset. |
| NFS: `/nas-media/video/movies`, `/nas-media/video/tv`, `/nas-media/music`, `/nas-media/immich-photos` | NAS `192.168.1.3` | Manual, not IaC-managed — same gap as legacy `media-stack`'s own NFS mounts. Must already be mounted on the LXC before first `docker compose up`. |
| apt-cacher | `apt_cacher_host:3142` | apt proxy during provisioning |

## Provides

| Service   | Port | Protocol | Notes |
|-----------|------|----------|-------|
| jellyfin  | 8096 | tcp      | Web UI / API. Also exposes 8920 (HTTPS), 7359/udp (auto-discovery), 1900/udp (DLNA) — not registered as separate `provides` entries, matching legacy's own convention. |
| immich    | 2283 | tcp      | Web UI / API (immich-server). |

Nothing else depends on this stack.

## Dependencies

None at the platform level (`depends_on: []` in `stack.yaml`). Runtime
dependency on the NAS's NFS exports (`192.168.1.3`, flat LAN — see
Inputs) and, once `media-lab-04`/`05`/`06` land, on Authentik for OIDC.

## Persistent State

| Path                        | Storage                        | Contents |
|------------------------------|--------------------------------|----------|
| `jellyfin-config` volume      | Docker named volume            | Jellyfin library DB, metadata, user accounts — seeded from legacy's `/config/jellyfin` in `media-lab-07`, not empty at first real login |
| `immich-db-data` volume       | Docker named volume            | Immich's Postgres data |
| `model-cache` volume          | Docker named volume            | Immich ML model cache |
| `/nas-media/video/movies`, `/nas-media/video/tv`, `/nas-media/music` | NFS (NAS `192.168.1.3`) | Shared with legacy `media-stack` — read the same library, not a copy |
| `/nas-media/immich-photos`    | NFS (NAS `192.168.1.3`)        | Immich's own photo/video library, separate from Jellyfin's paths |

## What May Depend on This Stack

Nothing yet. A leaf stack.

## What Must Not Be Edited Casually

- The three Jellyfin NFS mount paths (`/nas-media/video/movies`,
  `/nas-media/video/tv`, `/nas-media/music`) must keep matching legacy
  `media-stack`'s own paths — both stacks read the same library.
- `jellyfin-config` is meant to be seeded from legacy's real
  `/config/jellyfin` bind mount (`media-lab-07`) — starting this stack
  fresh before that copy runs means an empty library with no users.
- `MEDIA_STACK_LAB_DB_PASSWORD` must never be written literally into
  `docker-compose.yml`, `stack.yaml`, or this file — SOPS only.
- Legacy `media-stack` (VMID 102) is never stopped, restarted, or
  written to by anything in this stack's deploy path.

## Playbook

`deploy-media-stack-lab`

Docker Compose workload (`lxc_base` + `docker_base` roles), five
services in one compose file. OAuth/SSO wiring (`media-lab-04/05/06`)
and the legacy config copy (`media-lab-07`) are separate, later steps —
not part of first boot.
