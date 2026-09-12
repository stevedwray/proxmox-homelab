# torrent-stack-modernization — checkpoint (2026-09-12)

Written before a context compression, so this needs to stand on its
own. Full detail lives in `plan.md` (step-by-step build record, every
gate, every bug) and `README.md` (research, decisions, findings) — this
file is the fast-resume summary.

**Branch**: `task/torrent-stack-modernization-plan`
**Latest commit**: `d905cb8e` (as of this update) — clean working tree,
nothing uncommitted.
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
| Auth | **Confirmed LIVE, 2026-09-12.** All 6 routes reachable through the real edge with real HTTPS requests: qbittorrent/prowlarr/radarr/sonarr/lidarr (`forwardAuth`) each return `302` to Authentik's login/authorize flow; jellyseerr (`auth.mode: none`) returns `307` to its own `/setup`, no Authentik redirect. (This was NOT true earlier in the day — the routes were never reconciled into Authentik/Traefik by the initial deploy; see item 0 below for the fix.) |

## What's NOT done yet — in order

Item 0 is a new finding from this session (not in the original
`plan.md` Operator-only list); the rest are `plan.md`'s Operator-only
actions #7–13, all requiring you directly (production mutations,
manual UI steps, or judgment calls):

0. ~~Wire the 5 forwardAuth routes into Authentik + push Traefik
   config~~ — **DONE and independently verified, 2026-09-12.**
   `reconcile-edge.py --apply` scoped to just
   `terraform/lxc/stacks/torrent-stack-lab/edge.yaml` created the 5
   Authentik proxy-provider + application objects (confirmed via a
   fresh dry-run afterward: `classification_counts` went from
   `missing: 5` to `missing: 0, matching: 6`). `deploy-proxy-stack.yml`
   with `traefik_generated_source_dir` pointed at
   `terraform/lxc/environments/pve/.generated/traefik` pushed the
   rendered config to the live Traefik container (`changed=6`,
   `failed=0`). Verified with real HTTPS requests through the actual
   edge (`--resolve ...:443:${LAB_IP_PROXY}`, not just trusting the
   tools' own self-report): qbittorrent/prowlarr/radarr/sonarr/lidarr
   all return `302` to Authentik's `/application/o/authorize/` flow;
   jellyseerr returns `307` to its own `/setup`, no Authentik redirect
   — exactly the intended split.
0a. ~~DNS records for the 6 new hostnames were never pushed to the
    live Technitium server~~ — **found and fixed, 2026-09-12.** Same
    two-step shape as item 0: `reconcile-edge.py` only renders DNS
    records into a local file
    (`terraform/lxc/environments/pve/.generated/technitium/zone-records.json`);
    the live push only happens when `technitium-stack` itself is
    (re)provisioned. Found via operator report ("qbittorrent...has no
    DNS") + confirmed with a direct `dig` against Technitium
    (192.168.20.15) returning authoritative NXDOMAIN. Fixed by running
    `./with-secrets-prod scripts/provision.sh --stack
    technitium-stack` (`ok=120, changed=5, failed=0`, smoke test
    passed). Verified after: all 6 hostnames
    (qbittorrent/prowlarr/radarr/sonarr/lidarr/jellyseerr) now resolve
    to `192.168.30.10`; existing records (jellyfin, immich, etc.)
    unaffected — no regression. Real HTTPS requests through the actual
    hostnames (no `--resolve` override needed anymore) confirm the
    full DNS→Traefik→Authentik path end-to-end.
0b. ~~qBittorrent had no way for radarr/sonarr/lidarr to reach it
    without a shared password~~ — **DONE, 2026-09-12, but not the way
    first attempted.** Tried a zero-password design first (qBittorrent's
    `WebUI\AuthSubnetWhitelist` trusting the compose network's own
    subnet, same idea as Radarr's "Disabled for Local Addresses") and
    moved it into `deploy-torrent-stack-lab.yml` properly (Ansible
    `lineinfile`, not hand-run `sed`) rather than leave it a one-off. Real
    bugs found and fixed getting there:
    - `sed`'s `a` one-liner text-escaping silently dropped the required
      backslash AND matched almost every line instead of just the one
      after `[Preferences]`, leaving ~40 garbage duplicate lines with no
      working bypass. Fixed by moving to `lineinfile` (YAML's quoting
      rules, not three shell-escaping layers) plus a one-time cleanup
      pass for the leftover garbage.
    - The trusted subnet was whatever Docker's IPAM pool happened to
      auto-assign, not a fixed value — pinned it in `docker-compose.yml`
      (`172.30.80.0/24`).
    - `community.docker.docker_network`'s `force:true` recreate failed
      outright against the already-running stack (`network is
      unreachable` on reconnect, likely gluetun's own WireGuard routing
      state getting confused by a live network detach/reattach). Fixed
      by checking the live subnet+label first and only ever recreating
      via a full `docker compose down` + `up -d`.
    - That first failed force:true attempt had already deleted and
      recreated the network via the raw Docker API before erroring, so
      it ended up with the *correct* subnet but missing Compose's own
      ownership label — `docker compose down` silently skipped removing
      it, `up -d` then refused to attach at all. Fixed by checking
      subnet OR ownership label, not subnet alone, and explicitly
      removing the network directly when either is wrong.
    - Two more real, repo-wide latent bugs found in
      `portainer_stacks[].env[]` (Portainer deploys this stack via its
      own API using *only* the env vars listed here — a separate code
      path from the Ansible-driven `docker compose up -d` deploy):
      `LAB_DOMAIN` used Terraform's `$${...}` escape convention, copied
      from `media-stack-lab`, but this field is never touched by
      Terraform (confirmed absent from every `.tf` file) — it's read by
      `provision.sh`'s own Python `resolve_placeholders()`, which only
      understands single-dollar `${...}` and left a stray leading `$`
      in the output (`$lab.gibbsgreatly.xyz`). And `REGISTRY_HOST` was
      simply never declared there at all, so every image reference
      resolved blank under Portainer's own deploy (same failure mode as
      the original REGISTRY_HOST bug, different code path). Both fixed
      in `stack.yaml`. **`media-stack-lab` has both latent bugs too**
      (jellyfin's entry is missing `REGISTRY_HOST` entirely; immich's
      has it but with the same `$${...}` bug) — never triggered because
      its Portainer stacks already exist and this deploy path only runs
      for a stack not yet registered. Flagged, not fixed — separate
      stack, someone else's call.
    - Given all that, ended up asking the operator for the real
      qBittorrent password anyway after the subnet-bypass mechanism
      still returned 401/403 despite matching the verified qBittorrent
      source behavior and correct network connectivity — a real,
      unresolved mystery (possibly how qBittorrent sees the source IP
      sharing gluetun's network namespace) not worth further blind
      debugging. The bypass config is left in place (harmless either
      way); the download clients use real credentials instead.
1. ~~Confirm NAS NFS allowlist covers `192.168.80.11`~~ — **DONE,
   confirmed by operator 2026-09-12**: `192.168.80.11` added to the
   NAS's media share allowlist directly on the NAS (ADM), not via any
   file in this repo. Independently verified live (`pct exec 80011 --
   ls /nas-media`, read-only): real content visible —
   `video/movies`, `video/tv`, `music`, etc. — matching the exact
   subpaths `docker-compose.yml` mounts into radarr/sonarr/lidarr.
   `/incoming` also confirmed populated with legacy's real in-flight
   torrent data. Both bind mounts are genuinely working, not just
   configured.
2. **Real end-to-end validation**: search → grab → download → import →
   visible on the NAS. **Blocked by a new real finding, 2026-09-12**:
   Radarr/Sonarr/Lidarr (all non-root, uid 1000 by design) cannot write
   to `/nas-media` at all — every file there is owned by `65534:65534`
   ("nobody", NFS's anonymous-squash mapping) at `755`, confirmed with a
   direct `touch` failing "Permission denied" inside the radarr
   container, and confirmed via `POST /api/v3/rootfolder` failing
   "Folder '/movies' is not writable by user 'abc'" for all three apps.
   Compared directly against legacy `torrent-stack`'s own separate NAS
   mount (`/mnt/nas-media-ct100`): its files are owned `1000:1000` and
   a live write test there succeeds. So the two NFS exports/shares are
   configured differently at the NAS (ADM) level -- legacy's preserves
   or maps the client UID, the new shared `/mnt/nas-media` export
   squashes everyone to an anonymous UID. This is why `media-stack-lab`
   never hit it: Jellyfin only reads, and Immich (which does write, into
   `immich-photos`) almost certainly runs as root in its own container,
   which bypasses Unix permission bits entirely -- not evidence the
   export itself is fine. **Needs an operator NAS-side fix** (adjust the
   export's squash/UID-mapping settings to match legacy's, or grant
   uid 1000 write access some other way on the NAS itself) before any
   import can ever succeed -- not fixable from this repo or from inside
   the container.
   Root folders (`/movies`, `/tv`, `/music`) and Prowlarr's own
   indexer(s) are also still unconfigured (checked live, both empty) --
   the indexer add is yours to do (real tracker credentials); root
   folders can be set the moment the NAS permission fix lands (blocked
   by the same issue -- Radarr's own writability check rejects the
   folder before it'll even save it as a root folder).
3. **Jellyseerr's setup wizard** — also where its real auth gets
   configured ("Sign in with Jellyfin"), since it has no edge-level
   gate.
4. ~~qBittorrent Host-header allowlist~~ — **found already satisfied,
   2026-09-12**: `WebUI\ServerDomains` was already `*` (wildcard) in the
   live config, no change needed. **Radarr/Sonarr/Lidarr → qBittorrent
   download-client wiring** — **DONE, 2026-09-12**, via each app's own
   REST API (`POST /api/v3/downloadclient` for Radarr/Sonarr,
   `/api/v1/downloadclient` for Lidarr — confirmed these differ before
   assuming), host `gluetun` port `8888` (qBittorrent shares gluetun's
   network namespace, has no hostname of its own), real qBittorrent
   admin credentials (operator-provided). Independently verified via a
   fresh GET on all three afterward — each shows `id: 1`, the correct
   host/port/username, and its own category (`radarr`/`tv-sonarr`/
   `lidarr`). **Still open**: disabling each arr app's own built-in
   auth (Settings → General → Authentication) now that forwardAuth is
   confirmed working — not done yet, do this once you're comfortable
   forwardAuth is reliable day-to-day. Does NOT apply to jellyseerr
   (its own auth is the only gate it has).
5. **Watch `/incoming` sharing** with legacy's own qBittorrent for real
   collisions (accepted temporary risk, not a long-term design).
6. **Each arr app's own "import existing library" pass** — fresh
   install means empty databases; point root folders at `/movies`,
   `/tv`, `/music` and let each app rediscover what's already there.
7. **Cutover/decommission of legacy `torrent-stack`** — explicitly a
   separate, later, operator-initiated decision. Not scheduled here.

## Noted for future — operator confirmed 2026-09-12, not in scope now

- **Wazuh agent should be added to torrent-stack-lab.** Not wired
  today — the `wazuh_agent` role is opt-in per playbook (currently only
  `proxy-stack`, `harbor-stack`, `apt-cacher-stack`, `technitium-stack`,
  `authentik-stack`, `wazuh-stack` itself include it), and
  `deploy-torrent-stack-lab.yml` doesn't. `media-stack-lab` has the
  identical gap, so this isn't unique to this stack.
- **GVM/Greenbone vulnerability scanning should be extended to cover
  `media_seg`.** Operator's read: this is primarily a config change
  against GVM itself (new zone Target(s) + Task(s)), not new IaC/Ansible
  wiring on the torrent-stack-lab side. Real gap confirmed by checking
  `docs/greenbone-stack/network-scan-rollout-plan.md`: its 6-zone
  rollout covers `build_seg`, `mgmt_seg`, `edge_seg`, `infra_seg`,
  `ai_seg`, `game_seg`, plus the flat LAN — `media_seg` (VLAN 80,
  192.168.80.0/24) is absent from that list entirely. Nothing in
  `media_seg` is scanned today, so this also covers `media-stack-lab`,
  not just `torrent-stack-lab`.

Both are real, deliberately deferred to a separate future task — not
part of this modernization effort's scope, and not blocking anything
in the "What's NOT done yet" list above.

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
