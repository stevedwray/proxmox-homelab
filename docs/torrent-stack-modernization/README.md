# torrent-stack-modernization (planning workspace)

Status: **all 9 plan steps executed and committed
(`task/torrent-stack-modernization-plan`, `7c876590`).**
`torrent-stack-lab`'s five IaC files (`stack.yaml`, `docker-compose.yml`,
`STACK_CONTRACT.md`, `terragrunt.hcl`, `edge.yaml`) plus its Ansible
playbook and a new MikroTik firewall playbook all exist and pass every
gate on a clean re-run. **Nothing is deployed** — no `terragrunt
apply`, no `provision.sh`, no MikroTik rule actually applied against
the live router. Research and operator decisions were made across
several passes 2026-09-12 (network/scope/migration/image/client/auth
decisions — see the table below); execution then found and fixed
several more real gaps that only showed up when the plan's own gates
were actually run, not just read — see "Real findings" below for the
full list. Next step is entirely the operator's: work through
`plan.md`'s 13-item Operator-only actions list, starting with
confirming media_seg's real MikroTik anchor rule.

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
| Jellyseerr auth | **`auth.mode: none`** at the edge, not `forwardAuth` | Caught while re-reviewing the plan before execution: Jellyseerr is the one household-facing piece of this stack, not an admin tool. forwardAuth would require every household member to hold a full Authentik lab account just to see Jellyseerr's own login screen — its own "Sign in with Jellyfin" becomes the real gate instead, same posture `media-stack-lab/edge.yaml` already gives Jellyfin/Immich themselves |
| VPN provider | **Still ProtonVPN**, gluetun env vars unchanged from legacy | Operator confirmed 2026-09-12 — no compose change needed |
| Image tag pinning | Pin to whatever the **current** stable version is **at execution time**, not the 2026-09-12 research snapshot | Operator: don't carry forward legacy's floating-tag habit, but also don't trust a plan-time snapshot that'll already be stale by the time it's actually run (this is exactly what happened to the Jellyseerr tag found during research) |

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
  mount is a Proxmox **bind** mount (a plain host directory), not a
  **volume** mount (a dedicated Proxmox-managed disk) — double-mounting
  a volume onto a second container risks the same kind of corruption as
  mounting one block device in two places.
- **Confirmed facts (2026-09-12, `torrent-lab-01a`, run for real
  against `pve`)**: legacy torrent-stack's `/incoming` is
  `mp2: "/storage/ct-100/incoming,mp=/incoming,backup=1,size=1T"` — a
  real **BIND mount** (plain host directory), safe to share. Contrast
  its own `mp0`
  (`"apps-containers:subvol-100-disk-1,mp=/var/lib/docker,size=20G"`),
  which IS a storage-pool-backed volume — the case this check existed
  to catch, and didn't hit here. `stack.yaml` and the operator-only
  `pct set` command in `plan.md` now use the real path directly. Also
  found along the way: legacy's own NAS mount is
  `mp1: "/mnt/nas-media-ct100,mp=/nas,backup=0"` — a differently-named
  host directory than media-stack-lab's `/mnt/nas-media`, which doesn't
  change this plan (it already reuses media-stack-lab's mount, not
  legacy's). This also corrected an earlier finding in this file: the
  planning session itself had no route to `pve-test-vm` (which
  `./with-secrets` defaults to) when first drafted, which is not the
  same thing as the operator's workstation lacking a route to `pve` —
  it doesn't; this check ran from there successfully.
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
  qbittorrent/prowlarr/radarr/sonarr/lidarr have native SSO, so those
  five get `forwardAuth` routes in `edge.yaml`. **Jellyseerr is the
  deliberate exception** — `auth.mode: none`, caught on a pre-execution
  re-review (see the decisions table): it's the one household-facing
  piece of this stack, and forwardAuth would gate it behind a full
  Authentik lab account before anyone could even see its own login
  screen, defeating the point of adding it. `flaresolverr` gets no
  route at all (internal-only, called by prowlarr over the Docker
  bridge), matching the old plan's one correct call here. One
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

### Real findings from execution (not just planning), 2026-09-12

Running the plan's own gates for real, not just reading them, found
several more real gaps — all fixed in `plan.md` and this workspace, not
silently worked around:

- **`validate-stack-metadata.sh` (and `--check-contract-sections`)
  only check a small hardcoded `ACTIVE_STACKS` list inside
  `validate-stack-metadata.py` itself** — there's no flag to validate
  an arbitrary stack. Checked before trusting a clean run: none of the
  last several "-lab"/app-tier stacks (`media-stack-lab`,
  `gaming-stack-lab`, `greenbone-stack`, `pentagi-stack`, ...) are in
  that list either, so running it against `torrent-stack-lab` would
  have silently validated nothing while still printing "passed."
  Following that same precedent, `torrent-stack-lab` wasn't added to
  the list — replaced with real YAML-syntax and section-presence checks
  in both `torrent-lab-02` and `torrent-lab-04`.
- **`.env.template` does not mirror every `LAB_IP_*` var** — the
  original `torrent-lab-01` step assumed it did, modeled on
  `LAB_IP_MEDIA_STACK_LAB`. Checked directly: none of
  `media-stack-lab`/`pentagi-stack`/`greenbone-stack`/
  `mcp-utility-stack`/`secpipe-stack` have their IP there either, only
  in `.env`. Fixed before touching any file.
- **`ansible-playbook --syntax-check` for a playbook using `roles:`
  must run from `terraform/lxc/ansible/`** (its own `ansible.cfg` sets
  `roles_path=roles`) — running from the repo root fails with `role
  'lxc_base' was not found`. Confirmed by testing against
  `deploy-media-stack-lab.yml` too, not just the new playbook.
- **`validate-edge-manifests.py` resolves `${LAB_DOMAIN}` etc. from the
  real environment, not as a literal string** — needs `.env` sourced
  first, or every host fails `must end with .lab.gibbsgreatly.xyz`.
  Confirmed general (not specific to this file) by running
  `media-stack-lab`'s own `edge.yaml` through it unsourced and getting
  the identical failure.
- **Fresh tag lookup at execution time (as instructed) caught two more
  real things a plan-time snapshot missed**: `prowlarr:2.6.3`, the tag
  found during research, was never actually promoted to stable —
  pulling the raw registry tag list directly shows only
  `2.6.3-develop` exists at that version; `2.5.2` is the real latest
  stable. And Jellyseerr's GitHub releases page (`v3.4.1`) is ahead of
  what either Docker Hub or GHCR has ever published as a container
  image — the raw tag list for both stops at `2.7.3`, confirmed by
  listing every tag, not a filtered guess. Pinned to what's actually
  pullable.

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

All 9 file-authoring steps are done and committed. Everything left is
in `plan.md`'s Operator-only actions list (13 items) — start with #1
(confirm media_seg's real MikroTik anchor rule), then work through
`terragrunt apply`, the MikroTik rule, `provision.sh`, and the manual
post-deploy steps (WireGuard credentials, disabling built-in auth,
Jellyseerr's setup wizard) in order.
