# torrent-stack-modernization (planning workspace)

Status: **plan written, nothing implemented yet.** Research + operator
decisions complete 2026-09-12 across three passes: initial research and
network/scope/migration/image decisions, then a correction after the
operator clarified the real NAS and `/incoming` mount behavior (this
also caught a real mount-path bug in the first compose draft), then a
qBittorrent-vs-alternatives question answered inline. `plan.md` has
file-authoring steps ready for local-model execution
(`.github/prompts/implement-step.prompt.md`), per
`docs/agent-design/README.md`. No branch cut yet.

## Why this workspace exists

The legacy `torrent-stack` (VMID 100, flat LAN at `192.168.1.5`) runs
gluetun + qbittorrent + prowlarr + radarr + sonarr + lidarr (unofficial
fork) + flaresolverr, unauthenticated, with no Traefik/Authentik front
and config living only as an untracked bind mount. A prior attempt at
modernizing this — `docs/application-migration/01-torrent-stack-lab.md`
— was written **before** this repo's current step-packet planning
process and its `media_seg` precedent existed. It targeted a `dl_seg`/
VLAN 55 zone that was **never actually created** (confirmed absent from
`terraform/lxc/network/pve.yaml` as of this research) and no
`torrent-stack-lab` LXC was ever scaffolded from it — it's a dead,
superseded plan. This workspace supersedes it.

## Operator decisions (2026-09-12)

Asked up front, or given directly by the operator, because the plan's
literal content depends on them — see `docs/agent-design/README.md`
("surface genuine judgment calls to the operator rather than default
them silently"):

| Decision | Choice | Why |
|---|---|---|
| Network zone | **Reuse `media_seg` (VLAN 80)**, not a new dedicated zone | Same zone as `media-stack-lab` (Jellyfin/Immich) — reuses its NAS-NFS, Authentik forwardAuth, Graylog, and step-ca firewall precedent already proven live, and the new stack's `/nas-media` bind mount is literally the same host path `media-stack-lab` already has mounted on `pve` |
| Scope | Add **Jellyseerr** only (not Recyclarr or Bazarr) | The one addition that makes this "integrated" with `media-stack-lab` rather than a bolt-on — a request portal wired to Jellyfin + Radarr/Sonarr |
| Torrent client | **Keep qBittorrent** (operator asked directly whether it's the best fit for Authentik integration) | `forwardAuth` is agnostic to the backend — no BitTorrent client has native Authentik/OIDC support, so this isn't really an Authentik question. qBittorrent wins on other real grounds: TRaSH-Guides' de facto standard, best-documented hardlink-based completed-download handling (matters once it shares `/incoming` with the arr apps), category support, and it's what legacy already runs so `/incoming`'s on-disk state is already in qBittorrent's own format |
| Config migration | **Fresh install** — no arr database, quality profile, or qBittorrent setting carried forward | Operator: the live stack's indexer/VPN config has been unreliable and isn't worth carrying forward |
| Content migration | **None needed** — not a decision so much as a corrected fact | Operator clarified 2026-09-12: legacy torrent-stack already uploads finished downloads directly into the real movies/TV NAS content, not a separate copy. An earlier draft of this plan (and a line in `docs/plan/pve-migration-inventory.md`) treated `/nas-media/...` and `/nas/...` as two different libraries needing a migration step — that was wrong for planning purposes; trust the operator's live knowledge over that doc |
| `/incoming` staging | **Share it** between legacy torrent-stack and torrent-stack-lab, for now | Operator: it's a separate local (non-NAS) filesystem mount on legacy, not something to recreate empty — reuse the same one. Real concurrency risk accepted as a temporary state, not a long-term design (see plan.md's Operator-only actions) |
| lidarr image | Switch to **official `lscr.io/linuxserver/lidarr`** | Live stack's `blampe/lidarr` fork was a stopgap for old official-image lag; no longer needed |

## Real findings from research

- **The NAS library is already shared, continuous storage — no
  content migration needed.** A first draft of this plan read
  `docs/plan/pve-migration-inventory.md`'s line describing
  `/nas-media/...` and `/nas/...` as "different NFS export paths" too
  literally and designed a whole migration script around it. The
  operator corrected this directly: those are each LXC's own
  differently-named local mount points, but legacy torrent-stack's
  downloads already land in the same real movies/TV content. Removed
  the migration step entirely; the new arr suite just needs to point
  at the same `/nas-media/...` export media-stack-lab already reads
  (see below) and everything legacy has ever downloaded is already
  there.
- **Real mount-path bug caught while incorporating the above**: the
  first compose draft mounted the *entire* `/nas-media` tree into each
  arr app's container instead of the specific subdirectory (e.g.
  `/nas-media:/movies` instead of `/nas-media/video/movies:/movies`) —
  media-stack-lab's own Jellyfin compose never does this, always
  mounting the specific subpath. Fixed in `torrent-lab-03-compose`.
- **`/incoming` needs Proxmox-level sharing, not a Docker volume.**
  Legacy torrent-stack's `/incoming` is a separate local-filesystem
  mount point on its own LXC (192.168.1.5) — not NFS, not part of its
  rootfs/docker storage. A Docker named volume can't span two different
  LXCs' separate Docker daemons, so sharing it with `torrent-stack-lab`
  (on a different LXC, 192.168.80.11) has to happen at the Proxmox
  bind-mount level — same mechanism as `/mnt/nas-media`, just for local
  disk instead of NFS. This only works safely if legacy's `/incoming`
  mount is a Proxmox **bind** mount (a plain host directory); if it
  turns out to be a **volume** mount (a dedicated Proxmox-managed disk
  attached to VMID 100), double-mounting it onto a second container
  risks the same kind of corruption as mounting one block device in two
  places — `torrent-lab-01a-confirm-incoming-mount` in `plan.md` checks
  which case it is before anything commits to the shared-mount design,
  and this research session had no live network path to actually check
  it (see below).
- **This planning session has no LAN route to `pve` or `pve-test-vm`
  at all** — confirmed by a failed read-only Proxmox API call during
  planning (`curl` returned "No route to host"), not assumed. Any step
  needing real infrastructure facts (the `/incoming` mount type/path
  being the concrete case here) has to run from an environment with
  actual connectivity — the operator's own machine, or a normal
  `./with-secrets-prod` session — not from this planning sandbox.
- **`media_seg` already has almost everything this stack needs.**
  `pve.yaml`'s existing `media_seg → 192.168.1.3 tcp+udp/2049` NFS rule,
  `media_seg → mgmt_seg tcp/9443`, `media_seg → 192.168.20.14 tcp/514`
  (Graylog), and `media_seg → 192.168.20.11 tcp/443` (step-ca) rules
  all apply to this stack too, unmodified. Only two real network gaps
  exist (see `plan.md` step `torrent-lab-08-network-policy`): new
  ports on the existing `edge_seg → media_seg` Traefik rule (added as a
  **new** policy entry, not an edit to the existing one — keeps this
  additive-tier, not full-teardown-tier, matching the "propose the
  narrower alternative" rule in `CLAUDE.md`), and a new
  `media_seg → internet udp/51820` egress rule for gluetun's WireGuard
  tunnel (this exact gap was correctly identified by the old dead plan
  too, just for the wrong zone).
- **The NAS mount is already there.** `media-stack-lab` has
  `/mnt/nas-media` bind-mounted on the `pve` host itself (Proxmox
  `mp0`, root@pam-only, see its `host_bind_mounts`). Bind-mounting that
  *same already-NFS-mounted host path* into the new LXC needs no new
  NFS setup on `pve` at all — just a new `mp` entry on the new
  container pointing at the same host directory.
- **Harbor already proxies every registry this stack needs** — `lscr`,
  `ghcr`, and `dockerhub` proxy-cache projects all already exist
  (`terraform/lxc/ansible/roles/harbor_postconfigure/defaults/main.yml`).
  No Harbor-side work required, unlike the old plan which flagged
  `lscr.io` proxying as an open question.
- **`auth.mode: forwardAuth`** (not raw Traefik labels + a hand-named
  `authentik@file` middleware, which is what the old dead plan used) is
  this repo's current mechanism for exactly this class of service —
  see `docs/provisioning-refactor/edge-manifest-v1alpha1.md`. None of
  qbittorrent/prowlarr/radarr/sonarr/lidarr/jellyseerr have native SSO,
  so all six get `forwardAuth` routes in `edge.yaml`; `flaresolverr`
  gets no route at all (internal-only, called by prowlarr over the
  Docker bridge), matching the old plan's one correct call here. One
  real qBittorrent-specific gotcha found while answering the operator's
  client-choice question: its WebUI has its own Host-header allowlist
  that will reject requests proxied through `qbittorrent.${LAB_DOMAIN}`
  unless added — looks like a broken forwardAuth setup if not known
  about in advance (see `plan.md`'s Operator-only actions item 10).
- **Image tags**: pin every image to a specific LinuxServer/upstream
  version tag (never `:latest`/`nightly`/`develop`) — this repo's own
  Greenbone incident (`project_greenbone_unpinned_images` memory) is
  the reason this matters, not just style. `plan.md`'s compose step
  gives a snapshot of current stable tags as of 2026-09-12 research,
  but treats the *pin*, not the *exact string*, as the requirement —
  version tags for these images turn over roughly weekly, so the step
  instructs verifying the current tag at execution time rather than
  trusting a hardcoded value that will already be stale.

## What's still genuinely operator-only (not step blocks — see plan.md)

`terragrunt apply` (creates the LXC), `scripts/provision.sh --stack
torrent-stack-lab` (deploys the compose stack — both go through
`./with-secrets-prod` under the normal production approval flow, since
this validates directly against `pve` per the Ansible-task-or-role
tier), applying the new MikroTik firewall rule (via the router's own
Safe Mode console, same as every other live MikroTik change in this
repo's history), placing the WireGuard credentials file (never
committed or SOPS'd), adding `192.168.80.11` to the NAS's NFS
allowlist, disabling each arr app's and qBittorrent's built-in auth
(plus qBittorrent's Host-header allowlist) once forwardAuth is
confirmed working, watching for `/incoming`-sharing collisions between
the two live qBittorrent instances, and each arr app's own "import
existing library" pass so it recognizes what's already on the NAS. See
`plan.md`'s Operator-only actions list (13 items) for the full
sequence.

## Next step

Nothing executed yet. Start at `torrent-lab-01-env-ip` in `plan.md`,
then `torrent-lab-01a-confirm-incoming-mount` (needs an environment
with real network access to `pve` — this planning session doesn't
have one).
