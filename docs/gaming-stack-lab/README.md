# gaming-stack-lab (planning workspace)

Status: **research phase done, one step authored, not yet executed.**
Triggered by wanting to add ARK: Survival Ascended alongside the existing
Minecraft (`foreverworld`) service on `gaming-stack-lab`, given the two
can't run concurrently under current memory constraints, and wanting a
simpler start/stop control surface than driving Portainer's UI by hand.
Landed on adopting Pterodactyl (Panel + Wings) as that control surface,
which also opens the door to adding AzerothCore later without repeating
this design work.

## Quick facts

| | |
|---|---|
| Trigger | Operator wants ARK: Survival Ascended alongside Minecraft on `gaming-stack-lab`; can't run both at once (memory); wants simpler on/off control than Portainer's UI |
| ARK feasibility | **Confirmed live 2026-09-19** — runs under Proton inside `gaming-stack-lab`'s Docker-in-LXC nesting, with two fixes (see below). No fundamental nesting/bubblewrap wall. |
| Control-plane choice | Pterodactyl (Panel + Wings), chosen over continuing with bare Portainer, specifically because the operator wants proper per-game start/stop/console UX and is already planning a third game (AzerothCore) |
| Topology | Panel: new LXC, `game_seg`. Wings: **must** run on `gaming-stack-lab` itself (same host as the Docker daemon it manages — Wings doesn't support a remote Docker daemon out of the box) |
| Migration model | Existing `foreverworld` Minecraft data (world, mods, config, whitelist/ops) gets copied into Wings' managed volume, not lost — this is a file copy, not a conversion. Old compose-managed instance runs in parallel until verified, then retired. |
| AzerothCore | Not researched yet. Out of scope for this plan's steps — noted as a future addition once Panel/Wings exist. |

## ARK: Survival Ascended smoketest — findings (2026-09-19)

Run manually on `gaming-stack-lab` against a throwaway
`/srv/docker/_scratch/ark-smoketest/` checkout of
[azixus/ARK_Ascended_Docker](https://github.com/azixus/ARK_Ascended_Docker)
(GE-Proton + SteamCMD, `azixus/ark-ascended-docker` image). Torn down after
the test — nothing left in the tree from this. Full session transcript has
the blow-by-blow; this is the durable summary.

**Result: server reaches `"Server has completed startup and is now
advertising for join."`** Two real, fixable blockers were found and
resolved along the way — neither is a fundamental nesting problem:

1. **Crashpad needs `ptrace`.** Docker's default seccomp profile blocks
   it, so ARK's crash-handler init died silently (no dump, no dmesg trace,
   no log line — the container itself stayed "Up" because `tini` kept
   running even after the game process died). Fix: add
   `cap_add: [SYS_PTRACE]` to the compose service. Narrowly-scoped
   capability, not `--privileged`.
2. **No native Linux Steam client to bridge to.** `lsteamclient.dll`
   (Proton's Windows→Linux Steamworks API shim) tries to hand off to a
   native `steamclient.so`, which doesn't exist in this
   SteamCMD-only container — `assert(!status)` fails,
   process aborts (Wine exit code 21). This is a known, documented issue
   in the image's own tracker (issue #44, "Steam Subsystem initialized:
   FAILED"). Fix: add `-nosteam` to the server's launch flags — a
   dedicated server doesn't need Steamworks API init.
3. Root-caused via `WINEDEBUG=+winhttp,+loaddll,+seh` tracing after two
   dead ends: an apparent SteamCMD "Missing configuration" error (a
   well-known, benign first-run cache-warming quirk, resolved by simply
   retrying `docker compose up`) and an apparent stall on the Sentry
   telemetry HTTPS call (a red herring — that call actually succeeded;
   Wine's debug trace showed the real crash happened later, at
   `SteamAPI_Init`).

**Resource observations** (idle, no players connected): `10.41GB Mem`,
`Number of cores 16` reported at startup. Consistent with the ~16GB-minimum
guidance found separately (server binary alone can eat 6-10GB before any
player connects; 24GB+ recommended once players/mods are involved). Disk:
current ASA install is ~90-120GB, not the older ~70GB figure — budget
accordingly against `gaming-stack-lab`'s 500GB shared `/srv/docker` mount.

**These two fixes (`cap_add: SYS_PTRACE`, `-nosteam`) are concrete inputs
for whatever ARK egg/compose config gets written later — bake them in from
the start, don't rediscover them.**

## Step status

Updated by whoever executes a step — the actual edit made and actual gate
results, not a chat summary. Read this before authoring or approving the
next step.

- `gaming-lab-01-panel-stack-request`: **done 2026-09-20.** Created
  `terraform/lxc/stacks/pterodactyl-lab/stack-request.yaml` with exactly
  the content from the step's `change:` block. All 4 gates pass.
  One real gate bug found and fixed while running them: the plan's
  original `image-tags-pinned` gate (`grep -qE ':latest'` over the whole
  file) false-positived on the file's own prose explaining *why*
  `:latest` is forbidden (`compose_requirements`/`compose_forbidden`
  both mention the string literally) — not a real unpinned tag. Fixed to
  check only `image:` lines; `plan.md`'s gate updated to match, all 3
  real `image:` lines (`mariadb:11`, `redis:alpine`,
  `ghcr.io/pterodactyl/panel:v1.15.1`) confirmed to hold a real tag.
  **Worth flagging, not silently decided**: `mariadb:11` and
  `redis:alpine` are major-version/rolling pins (exactly matching
  Pterodactyl's own official reference), not exact-patch or digest pins
  like `media-stack-lab`'s Immich postgres/redis services use — looser
  than this repo's tightest precedent, but not a bare `:latest` either.
  Left as-is (matches upstream's own reference, and Panel's DB/cache
  aren't in this plan's high-scrutiny path the way user photo data is) —
  revisit if that judgment call should be tightened before real deploy.
  Not yet scaffolded (`scaffold-stack.sh pterodactyl-lab`) — that's a
  separate, not-yet-authored operator step.

## Operator step: gaming-lab-02-scaffold

Not a step block — `scaffold-stack.sh` is itself marked **DEPRECATED** in
its own header (`opencode` is a deprecated path in this lab, per operator
directive) — same situation `media-lab-02-scaffold` hit. Done the same
way: wrote all 5 files by hand instead of driving the script's opencode
agents, then ran the same real validators it would have.

**Done 2026-09-20.** Wrote `stack.yaml` (literal transcription of
`stack-request.yaml`'s `stack_yaml` block, including the `network: zone:
game_seg` field this session already knew to check for — that field's
omission was a real, costly bug caught late in `media-stack-lab`'s own
scaffold step; not repeated here), `docker-compose.yml` (from
`compose_requirements`, same content already gate-checked in
`gaming-lab-01`), `STACK_CONTRACT.md` (modeled on `apt-cacher-stack`'s
section shape, per `contract_facts`), `terragrunt.hcl` (boilerplate,
byte-identical to `gaming-stack-lab`'s own — this file never varies
between stacks), and
`terraform/lxc/ansible/playbooks/deploy-pterodactyl-lab.yml` (modeled on
`minecraft-stack`'s single-compose-project pattern for the deploy tasks
themselves, plus `media-stack-lab`'s Harbor-FQDN/syslog `daemon.json` task
and its two-play Portainer-registration shape — proactively included both
this time rather than waiting to rediscover them as bugs, since both are
now known, documented gaps in this repo's `docker_base` role defaults).

Validators run, all pass:
- `./terraform/lxc/validate-compose.sh --stack pterodactyl-lab` — passes.
- `ansible-playbook --syntax-check playbooks/deploy-pterodactyl-lab.yml`
  — passes, but **only when run from `terraform/lxc/ansible/` itself**
  (relative `roles_path = roles` in that directory's `ansible.cfg`); run
  from the repo root it fails with a spurious "role 'lxc_base' was not
  found" — not a real defect in the playbook, a working-directory
  requirement worth remembering for the next stack's syntax-check too.
- `## Provides`/`## Dependencies` contract sections — both present,
  checked directly.
- `validate-stack-metadata.sh` — passes, but (same pre-existing gap
  `media-stack-lab` found) doesn't actually cover this stack; its
  `ACTIVE_STACKS` list is fixed and has no `--stack` override.

Not yet applied — `terragrunt apply` and `provision.sh --stack
pterodactyl-lab` are real infrastructure steps, stay manual/operator-run.

**Secrets: `PTERODACTYL_LAB_DB_PASSWORD` / `PTERODACTYL_LAB_DB_ROOT_PASSWORD`
added 2026-09-20** — operator generated both via `openssl rand -base64 24`
and added to `terraform/secrets.common.enc.yaml` directly (SOPS edit, not
run through this session). Confirmed present via
`./with-secrets env | grep PTERODACTYL`. `PTERODACTYL_LAB_API_KEY` still
cannot be added — it's generated inside Panel's own admin UI, which
doesn't exist until Panel is actually deployed (circular, same as
`JELLYFIN_API_KEY`/`IMMICH_API_KEY` were in `media-stack-lab`'s work).

## Step: gaming-lab-03-wings-install

**Done 2026-09-20.** Researched Wings↔Panel pairing directly from
`pterodactyl/panel` and `pterodactyl/wings`'s own source rather than
assuming it was UI-only (the same trap `media-lab-06` fell into and
corrected) — confirmed real, scriptable Application API endpoints for
Location/Node/Allocation creation, and that Wings' own `configure`
subcommand (real flags: `--panel-url`, `--token`, `--node`, `--override`)
does the actual config.yml fetch-and-write, so nothing needed
hand-serializing the API's JSON response.

A second real judgment call surfaced along the way and was **not**
decided silently: `gaming-stack-lab`'s own README documents Minecraft as
deliberately hand-curated, not Ansible/`provision.sh`-driven — raising
whether Wings installation should follow that same manual pattern.
Operator confirmed 2026-09-20: Wings is infrastructure, treat it like any
other stack's deploy playbook (idempotent, via `provision.sh`); the
per-game hand-curation stays exactly as it was for Minecraft's content,
this doesn't change that.

Edited `terraform/lxc/stacks/gaming-stack-lab/stack.yaml` (`ansible_playbook`
now `deploy-gaming-stack-lab`, added `pterodactyl-lab` to `depends_on`) and
created `terraform/lxc/ansible/playbooks/deploy-gaming-stack-lab.yml`
(carries forward `deploy-portainer-agent.yml`'s existing plays unchanged,
plus the new idempotent Location/Node/Allocation/Wings-pairing play). All
3 gates pass, including an explicit `foreverworld-untouched` gate
(`git diff --name-only` confirmed clean) — added specifically because the
operator asked mid-session to make certain nothing in this work risked
`foreverworld`'s world/modpack data. Nothing in this step reads, writes,
or otherwise touches that directory.

## Deployment status (real infrastructure, beyond the plan's steps)

**pterodactyl-lab: LIVE 2026-09-20, verified.** `terragrunt apply`
(6 added, 0 changed, 0 destroyed — LXC `60020`, `192.168.60.20/24`,
`game_seg`/`tvgames`, confirmed via output) then
`provision.sh --stack pterodactyl-lab` (Docker/Portainer-agent base,
Panel+MariaDB+Redis compose, Portainer registration as endpoint ID 15) —
both run by the operator directly under the production approval flow
after the harness blocked my own attempt at the `terragrunt apply`
("blind apply", correctly — a plan was shown first instead).

**Real bug hit and fixed live, not caught by any gate in this plan**:
first `provision.sh` run failed at the Portainer Agent step —
`context deadline exceeded` pulling through `harbor.lab.gibbsgreatly.xyz`.
Root-caused via a live, read-only MikroTik firewall-rule query
(`mikrotik_client.py`'s `get_firewall_rules()`, same tool
`media-stack-lab` used for its own network discovery): `game_seg` has
two separate Harbor-access rules — one correctly zone-wide
(`192.168.60.0/24` → `192.168.40.0/24`, direct HTTP-only Harbor), and one
for the actual FQDN/Traefik path (`→ 192.168.30.10:443`) that was scoped
to `192.168.60.10` only (`gaming-stack-lab`'s own IP) instead of the
whole zone — almost certainly because it was written when
`gaming-stack-lab` was the only host in `game_seg` and nobody anticipated
a second one joining. `pterodactyl-lab` at `.20` fell outside it.
Fixed by the operator directly via RouterOS CLI (the API's automation
credential turned out to lack write permission on the firewall resource
— separate, smaller gap, not yet fixed, flagged for later) — widened
`src-address` to `192.168.60.0/24`, confirmed live via a rule `print`,
then `provision.sh` re-run cleanly, `failed=0`.

**Verified live, not just "the playbook said ok"**: `curl http://192.168.60.20/`
returns `HTTP 200`.

**`gaming-lab-03-wings-install`: LIVE 2026-09-20, verified end-to-end.**
Wings installed and paired with `pterodactyl-lab`'s Panel — confirmed via
Wings' own local API (`401`, alive and enforcing its own token auth, not
broken) and Panel's Node record (`id: 1, name: "gaming-stack-lab"`).
Real bugs found and fixed along the way, none caught by any gate written
in advance:

1. **`ansible.builtin.uri` needs `return_content: true`.** Without it,
   neither `.content` nor `.json` populate on the registered result at
   all — two separate failures (first assuming `.json` would work, then
   `.content` without the flag) before finding the actual cause. Fixed
   in `deploy-gaming-stack-lab.yml`; this is a good, transcribable lesson
   for any future Pterodactyl-API automation task in this repo.
2. **API calls must go direct, not through the public FQDN.** The
   playbook originally pointed `pterodactyl_panel_url` at
   `https://pterodactyl.${LAB_DOMAIN}` — but that route now sits behind
   Authentik's `forwardAuth` gate (added earlier this session), which
   intercepted the unauthenticated Bearer-token API calls and redirected
   to an HTML login page. Showed up as a confusing "invalid JSON" error,
   not an auth error, since the redirect target was 200 not 401/302 by
   the time the client followed it. Fixed by pointing Ansible's (and
   Wings' own `configure`) API calls at the direct internal address
   (`http://${LAB_IP_PTERODACTYL_LAB}`) instead — same `game_seg` zone,
   no need to route through the public gate for server-to-server calls.
3. **Wings' own Docker network default collided with an existing one.**
   `wings configure` defaults its `pterodactyl0` bridge network to
   `172.18.0.0/16` unconditionally, without checking the host's existing
   Docker networks — `gaming-stack-lab` already had
   `portainer_portainer-agent` on that exact subnet, so Wings
   crash-looped on startup (`Pool overlaps with other one on this
   address space`). Fixed by live-patching `/etc/pterodactyl/config.yml`
   to `172.20.0.0/16` (confirmed clear of `172.17.0.0/16` bridge,
   `172.18.0.0/16` portainer-agent, `172.31.250.0/24` portainer_default)
   and restarting — came up clean. **Live-only fix, not yet reflected in
   the playbook** — if `config.yml` is ever deleted and Wings
   re-`configure`d fresh, this would recur; worth adding a post-configure
   patch task to `deploy-gaming-stack-lab.yml` in a future pass rather
   than leaving it as a one-off.

**Separate, deliberately unresolved gap found getting here**: `gaming-stack-lab`'s
own Terraform state doesn't resolve from this working directory
(`terragrunt state list` returns "no state file was found" despite a real
`.tfstate` existing on disk under `environments/pve/gaming-stack-lab/`) —
almost certainly a workspace-selection mismatch, not genuinely empty
state. Rather than risk `terragrunt apply` against a live, data-bearing
container under an unclear state condition, the `ansible_playbook` field
change was applied by hand-editing the generated (gitignored)
`inventory.yml` directly instead — zero Terraform risk, but this fix will
be silently lost if `terragrunt apply` for this stack ever succeeds again
before the underlying state problem is diagnosed. **Flagging, not
fixing** — worth its own investigation before any future Terraform
operation against `gaming-stack-lab`.

**Update, superseded by later work this same session**: Panel's admin
user was created, `edge.yaml`/Traefik/Authentik/DNS hookup was done (see
its own section above), `TRUSTED_PROXIES` was fixed, and
`PTERODACTYL_LAB_API_KEY` is in SOPS — all of which unblocked
`gaming-lab-03`, now live and verified (see above).

**Correction 2026-09-20, found while researching the ARK egg itself (see
plan.md's Open questions): the allocation ports this step created were
wrong.** Hardcoded `7790`/`32330` from the smoketest's own `azixus`
image defaults, but the actual Wings egg to use
(`pelican-eggs/eggs`' official ARK egg) has different real defaults —
`7777`/`7778`/`27015`/`37015`. Fixed directly in
`deploy-gaming-stack-lab.yml`. Also surfaced a real, unresolved risk in
the same research pass: Wings hardcodes `ReadonlyRootfs: true` and a
fixed `CapDrop` list with no `CapAdd` support at all (confirmed from
Wings' own `container.go`), meaning there's no supported way to grant
`SYS_PTRACE` — the exact fix the smoketest needed. A real community
report shows the official egg working fine under Wings with no such fix,
but that report predates ARK's Sentry crash-reporter integration by
roughly two years, so it may not actually still hold today. Flagged as
genuinely unresolved, not something more research can settle — needs an
actual live test once Wings is running for real.

Not yet runnable for real: `PTERODACTYL_LAB_API_KEY` doesn't exist yet —
requires the Panel to actually be deployed first (`gaming-lab-02`'s
`terragrunt apply`/`provision.sh` are still manual/operator-run), then a
one-time manual bootstrap of Panel's first admin user and an Application
API key (circular — cannot itself be API-driven, same class of
unavoidable manual step as `media-lab-06`'s `JELLYFIN_API_KEY`).

See `plan.md` for the full plan, research, and open decisions.
