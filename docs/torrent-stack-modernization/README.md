# torrent-stack-modernization (planning workspace)

Status: **`torrent-stack-lab` is deployed and running.** VMID 80011 on
`pve`, all 8 containers up, `gluetun` healthy and routing through
ProtonVPN, `qbittorrent` WebUI responding. Getting here took a real
destroy/recreate cycle and five distinct live bugs found and fixed
along the way (not five attempts at the same bug — five genuinely
different root causes): a mount-index collision that silently
corrupted Docker's storage volume, a missing `REGISTRY_HOST` env var,
an unwired/never-tested `/dev/net/tun` device role that itself had a
bug once actually run, Docker's file-vs-directory bind-mount behavior
biting the WireGuard config mount, and a stale ProtonVPN peer config.
See "Real findings" below for the full, honest account of each —
deliberately not smoothed over, since the point of this record is that
the *next* stack needing any of these same things (bind mounts +
docker storage, a TUN device, a file-specific bind mount) won't hit
them again.

Operator-only actions #1–6 are now done (see below and `plan.md`).
Remaining: #7–13 — NAS NFS allowlist, end-to-end validation (search →
grab → download → import), Jellyseerr's setup wizard, disabling each
app's built-in auth, watching the `/incoming`-sharing risk, and the
arr apps' own "import existing library" pass. Also flagged, not yet
decided: `at39.conf` (the WireGuard config currently in use) is a
borrowed spare from legacy's own pool, not a dedicated peer for this
stack — worth a decision, not resolved here. Separately, real
pre-existing drift was found on `media-stack-lab` during validation
(unrelated to this stack, not fixed here, operator's to look at
separately) — see below.

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
- **A real bug in `torrent-lab-09`'s MikroTik playbook, caught before
  it was ever run for real.** Confirmed this session has genuine
  read-only API access to the MikroTik and used it: a GET against
  `/ip/firewall/filter` showed media_seg's actual containment anchor
  (rule `*8A`, "media_seg default-deny to LAN and other zones")
  matches on `src-address=192.168.80.0/24` — not
  `in-interface=vlan80-media`, which the first playbook draft had
  guessed (the interface name itself was real and correct, confirmed
  live too — it's just used by a different, unrelated accept rule,
  `*85`). Under the original logic this would have found no anchor,
  taken an "append without `place-before`" fallback, and landed the
  new accept rule *after* the deny in evaluation order — permanently
  dead. Fixed to match the confirmed real field, fallback path removed
  entirely, and the fix was validated offline against the real fetched
  JSON (not just `--syntax-check`, which can't catch this class of
  bug) before being trusted. A final order-check assertion was also
  added, since rule *presence* was never actually the risk here — rule
  *order* was.
- **`pve-test-vm` is not actually used for routine validation.**
  `plan.md`'s Operator-only action #2 originally said to validate the
  network policy change on `pve-test-vm`, following the Validation
  Tiers table's literal wording for network/SDN changes. It's
  unreachable (confirmed by 100% ping loss, not a fluke) — operator
  clarified it's deliberately powered down, kept only for specific
  high-risk structural tests, and real work happens on `pve` directly.
  Validated there instead: `terragrunt plan` for `torrent-stack-lab`
  came back clean (`6 to add, 0 to change, 0 to destroy`). The
  adjacent-zone regression check (`media-stack-lab`) did NOT come back
  clean on the first try — `2 to add, 0 to change, 1 to destroy`.
  Investigated before trusting either conclusion: reverted `pve.yaml`
  and removed the `torrent-stack-lab` directory entirely, re-ran the
  identical plan, got the identical result — proving this drift
  (`portainer_server_ip` resolving where it was previously blank, plus
  a `stack_cleanup` recreate) predates this work entirely and isn't
  caused by it. Real, separate finding worth flagging to the operator
  on its own — not something this task should fix or that blocks it.

- **Five distinct real bugs found deploying for real, none of them
  IaC/gate-catchable** — full blow-by-blow in `plan.md`'s Operator-only
  actions #4–6, summarized here:
  1. `pct set -mp0 ...` for the first bind mount silently overwrote
     Terraform's own docker-storage `mount_point` (the provider assigns
     it index 0 automatically — confirmed against `media-stack-lab`'s
     live config, where `mp0` is its docker-storage volume and its own
     bind mounts start at `mp1`). Docker's storage ran on the plain 8G
     rootfs instead of its own 20G volume; the next pull died partway
     through, almost certainly disk exhaustion. Fixed by destroying and
     recreating the container clean (nothing of value existed on it)
     and re-mounting starting at `mp1`. The destroy itself needed a
     deliberate production safety gate overridden
     (`network_sdn_allow_destroy` defaults `false` except for
     `pve-test`) — verified first that the underlying playbook
     independently checks for other LXCs on the shared bridge before
     ever touching a VNet/zone, so overriding it was safe here.
  2. `REGISTRY_HOST` was never written into the compose project's
     `.env` — every `${REGISTRY_HOST}/...` image reference resolved
     blank. Not a new mistake so much as an inherited one:
     `media-stack-lab`'s own jellyfin deploy task has the identical
     gap right now, live, un-triggered only because it hasn't needed a
     from-scratch pull since gaining that compose reference.
  3. `gluetun` needs `/dev/net/tun`, which doesn't exist in a fresh LXC
     by default. A role for exactly this (`lxc_tun_device`) already
     existed in this repo but had never been wired into any playbook —
     and once actually run for the first time, had its own bug (a
     `wait_for` task with no `delegate_to`, trying to run on the host
     it had just stopped). Both fixed.
  4. Docker's bind-mount behavior for a *missing file* (not directory)
     source: it silently creates an empty directory there instead.
     `gluetun`'s WireGuard config bind-mount hit exactly this — placing
     the real file afterward wasn't enough, since the mount was already
     resolved to a directory at container-create time; the two
     containers sharing it had to be removed (not just restarted) and
     recreated.
  5. The first real WireGuard config tried (a spare from legacy's own
     pool, ~1 year old) connected at the WireGuard layer but failed
     gluetun's healthcheck in a tight retry loop; a much more recently
     dated spare worked immediately — strongly suggesting the older
     peer had simply gone stale on ProtonVPN's side, not a network
     issue. **Not yet resolved**: the working config is a borrowed
     spare, not a peer dedicated to this stack — a real decision for
     the operator, not made here.

  None of these are evidence that new-stack bring-up is unusually
  fragile in this repo generally — `media-stack-lab`, Wazuh, and
  Greenbone are all real, recent, successful cold-starts (an earlier
  draft of this note wrongly implied otherwise, and was corrected).
  What's actually true: this is the first stack needing raw LXC device
  passthrough (`/dev/net/tun`), so `lxc_tun_device` had literally never
  been exercised before regardless of how it looked on paper; the other
  four were combinations of one real authoring mistake (the mount
  index) and runtime specifics (Docker's own bind-mount semantics, a
  VPN peer going stale) that no static gate in this repo could have
  caught before an actual deploy attempt.

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

All 9 file-authoring steps and Operator-only actions #1–6 are done —
`torrent-stack-lab` is deployed and running. Remaining, in
`plan.md`'s Operator-only actions:

- #7: add `192.168.80.11` to the NAS's NFS allowlist (may already be
  covered via the shared `/mnt/nas-media` mount — confirm, don't
  assume)
- #8: real end-to-end validation (search → grab → download → import →
  visible on the NAS)
- #9: Jellyseerr's setup wizard (also where its own auth — its "Sign
  in with Jellyfin" — actually gets configured, since it has no
  edge-level gate)
- #10: disable each arr app's and qBittorrent's built-in auth once
  forwardAuth is confirmed working, plus qBittorrent's Host-header
  allowlist
- #11: watch for the accepted `/incoming`-sharing risk with legacy's
  own qBittorrent
- #12: each arr app's own "import existing library" pass
- #13: cutover/decommission of legacy — explicitly a separate, later,
  operator-initiated decision

Also unresolved, not blocking: whether `at39.conf` (borrowed from
legacy's spare pool) should stay as-is or be replaced with a peer
dedicated to this stack. Separately, real pre-existing drift on
`media-stack-lab` (found during action #2) is worth the operator's own
attention at some point — unrelated to this stack, not fixed here.
