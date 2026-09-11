# torrent-stack-modernization — checkpoint (2026-09-12)

Written before a context compression, so this needs to stand on its
own. Full detail lives in `plan.md` (step-by-step build record, every
gate, every bug) and `README.md` (research, decisions, findings) — this
file is the fast-resume summary.

**Branch**: `task/torrent-stack-modernization-plan`
**Latest commit**: `ffea8dfd` — clean working tree, nothing uncommitted.
**Execution mode**: this session drives steps directly (operator
decision — no local-model handoff for this stack).

## What's actually live right now

`torrent-stack-lab` is deployed and running on `pve`:

| Fact | Value |
|---|---|
| VMID | `80011` |
| IP | `192.168.80.11/24` |
| Zone | `media_seg` (VLAN 80) |
| Mount points | `mp0` = Terraform's docker-storage volume (20G, **never** touch with `pct set`) · `mp1` = `/mnt/nas-media` (bind, shared with `media-stack-lab`) · `mp2` = `/storage/ct-100/incoming` (bind, shared with legacy `torrent-stack`) |
| Containers | All 8 up: `gluetun` (healthy), `qbittorrent`, `prowlarr`, `radarr`, `sonarr`, `lidarr`, `flaresolverr`, `jellyseerr`, plus `portainer-agent` |
| VPN | ProtonVPN via `gluetun`, WireGuard config is `at39.conf` — **a borrowed spare from legacy torrent-stack's own config pool, not a peer dedicated to this stack** (see Open decisions below) |
| MikroTik | `media_seg → internet udp/51820` egress rule is live, independently verified (rule `*8E`, correctly ordered before the `*8A` default-deny) |
| Auth | 5 routes (qbittorrent/prowlarr/radarr/sonarr/lidarr) declared `forwardAuth` in `edge.yaml`; jellyseerr declared `auth.mode: none` (household-facing, gates itself). **Not yet confirmed these routes are actually live via Traefik/DNS** — that's part of the still-open end-to-end validation below. |

## What's NOT done yet — in order

These are `plan.md`'s Operator-only actions #7–13, all requiring you
directly (production mutations, manual UI steps, or judgment calls):

1. **Confirm NAS NFS allowlist** covers `192.168.80.11` (may already be
   covered via the shared `/mnt/nas-media` mount — check, don't assume).
2. **Real end-to-end validation**: search → grab → download → import →
   visible on the NAS. This also implicitly tests whether the
   `edge.yaml` routes are actually reachable via Traefik.
3. **Jellyseerr's setup wizard** — also where its real auth gets
   configured ("Sign in with Jellyfin"), since it has no edge-level
   gate.
4. **Disable each arr app's + qBittorrent's built-in auth** once
   forwardAuth is confirmed working, plus qBittorrent's Host-header
   allowlist (WebUI → Options → Web UI, add `qbittorrent.${LAB_DOMAIN}`
   or it'll reject proxied requests looking like a broken forwardAuth
   setup).
5. **Watch `/incoming` sharing** with legacy's own qBittorrent for real
   collisions (accepted temporary risk, not a long-term design).
6. **Each arr app's own "import existing library" pass** — fresh
   install means empty databases; point root folders at `/movies`,
   `/tv`, `/music` and let each app rediscover what's already there.
7. **Cutover/decommission of legacy `torrent-stack`** — explicitly a
   separate, later, operator-initiated decision. Not scheduled here.

## Open decisions — not blocking, but unresolved

- **WireGuard peer**: keep `at39.conf` (borrowed from legacy's spare
  pool) or generate a dedicated ProtonVPN peer for `torrent-stack-lab`
  specifically? Your call.
- **`media-stack-lab` drift** (found unrelated, during validation of
  this stack's network policy change): `terragrunt plan` shows
  `2 to add, 0 to change, 1 to destroy` — `portainer_server_ip`
  resolving where it was previously blank, plus a `stack_cleanup`
  recreate. Confirmed pre-existing and unrelated to this work (isolated
  by reverting this stack's changes entirely and reproducing the
  identical result). Not fixed, not this task's job — worth your own
  look separately.
- **`media-stack-lab`'s jellyfin deploy task has the same missing
  `REGISTRY_HOST` bug** this stack had (fixed here, not there) — latent,
  not currently biting anything since jellyfin hasn't needed a
  from-scratch pull since gaining that compose reference. Flagged, not
  fixed — not this task's stack.

## The five real bugs found getting here (full detail in plan.md)

1. `pct set -mp0 ...` for the first bind mount overwrote Terraform's
   own docker-storage mount point (provider auto-assigns it index 0).
   Fixed by destroy + recreate, re-mounted starting at `mp1`.
2. `REGISTRY_HOST` never written into the compose project's `.env` —
   every image reference resolved blank. Fixed in
   `deploy-torrent-stack-lab.yml`.
3. `gluetun` needs `/dev/net/tun`; an existing-but-never-wired-in role
   (`lxc_tun_device`) handles this but had its own bug (missing
   `delegate_to` on a wait task) — found and fixed on first real use.
4. Docker silently creates an empty directory for a bind-mounted file
   that doesn't exist yet — bit `gluetun`'s WireGuard config mount;
   required removing and recreating the container (not just
   restarting) once the real file was placed.
5. First WireGuard config tried (a ~1-year-old spare) connected but
   failed gluetun's healthcheck; a more recently dated spare worked
   immediately — likely a stale/revoked peer, not a network issue.

**Corrected claim, for the record**: an earlier draft of this session's
notes wrongly implied new-stack cold-starts are unusually risky in this
repo generally. They're not — `media-stack-lab`, Wazuh, and Greenbone
are all real, recent, successful cold-starts. What's actually true is
narrower: this is the first stack needing `/dev/net/tun`, so that one
piece of automation had never been exercised before, regardless of how
correct it looked on paper.

## Where to resume

Read this file, then jump straight to `plan.md`'s "Operator-only
actions" section (items 7–13) for the exact next commands/steps. No
need to re-read the full build history unless something above doesn't
match what you find live.
