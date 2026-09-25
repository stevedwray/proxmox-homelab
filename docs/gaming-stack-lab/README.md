# gaming-stack-lab (planning workspace)

## CHECKPOINT — 2026-09-26

**Goal**: add ARK: Survival Ascended alongside `gaming-stack-lab`'s
existing Minecraft (`foreverworld`), with a real start/stop/console
control surface (Pterodactyl Panel + Wings) instead of driving Portainer
by hand, and a path to add AzerothCore later without repeating this
design work.

### Work done this session

- Confirmed ARK ASA feasibility via a throwaway raw-Docker smoketest
  (2026-09-19) — two fixes found (`SYS_PTRACE`, `-nosteam`).
- Chose Pterodactyl (Panel + Wings) over continuing with bare Portainer.
- Scaffolded, deployed, and live-verified `pterodactyl-lab` (Panel) —
  `terragrunt apply` + `provision.sh`, fronted by Traefik/Authentik,
  DNS resolving, admin bootstrapped, `PTERODACTYL_LAB_API_KEY` in SOPS.
- Installed and paired Wings on `gaming-stack-lab` — live, verified from
  both sides (Wings' own API, Panel's Node record).
- Proved ARK actually runs under Wings' real constraints (`ReadonlyRootfs`,
  no `CapAdd` at all) via a second live test — the `SYS_PTRACE`
  requirement from the raw smoketest turned out to be specific to that
  setup, not universal.
- Created a real, permanent ARK server (id 2, `TheIsland_WP`, port 7777)
  — live, running, started from Panel's own browser UI.
- Tuned game settings for casual/family play (taming, breeding, harvest,
  engram points, difficulty) and confirmed a working in-game connection
  method (`Ark.UseServerList 0` + search by name).
- **Eight real, live-found bugs fixed** along the way (not caught by any
  gate written in advance): `game_seg`'s Harbor-via-Traefik firewall rule
  scoped to one host instead of the zone; `ansible.builtin.uri` needing
  `return_content: true`; Panel API calls needing to go direct instead of
  through the Authentik-gated public FQDN; Wings' Docker subnet colliding
  with an existing network; DNS egress blocked for install containers;
  install-time file ownership never fixed by the community egg; Wings'
  websocket `allowed_origins` defaulting to `[]` (silently blocked every
  browser control, no error banner); LAN firewall rules never covering
  Wings' console port or ARK's actual game ports. Full blow-by-blow for
  each is in the dated sections below — this list is the durable summary.

### Current state

| | |
|---|---|
| `pterodactyl-lab` (Panel) | Live at `http://192.168.60.20` / `https://pterodactyl.lab.gibbsgreatly.xyz`, Traefik+Authentik-fronted, admin bootstrapped |
| Wings (on `gaming-stack-lab`) | Live, paired with Panel as Node 1 |
| ARK server | Live, real, permanent (id 2) — `gaming-stack-lab` `192.168.60.10:7777`, `TheIsland_WP`, casual-tuned settings |
| `Foreverworld` (Minecraft) | Live under Wings as server 3, with world/mod/RCON and two-direction interlock checks passed. The old Compose source is stopped and the pre-copy snapshot is retained for the confidence period. |
| Migration implementation | Completed production migration with checked-in eggs, shared interlock, additive allocations, full-copy rollback path, and operator in-game verification. |
| Branch | `feat/gaming-stack-lab-ark-mods`; not merged to `stable`/`main` |
| Known, flagged-not-fixed gaps | (1) `gaming-stack-lab`'s own Terraform state doesn't resolve from its working directory (workspace-selection mismatch, not empty) — **do not run `terragrunt apply` against this stack** until diagnosed separately; the `ansible_playbook` field is live-patched directly in the gitignored `inventory.yml` as a workaround. (2) The LAN→`game_seg` UDP rule for ARK's game/peer/query ports (`7777`/`7778`/`27015`), applied live via RouterOS CLI, is **not yet mirrored into `pve.yaml`** — do that before this is considered done. (3) `MIKROTIK_USER`'s SOPS credential lacks RouterOS write permission (API returns "not enough permissions (9)") — every live firewall change this session went through manual operator CLI instead; worth fixing the credential's own permissions separately. |

### Future plans / next steps, in likely priority order

1. **Mirror the LAN→ARK-ports firewall rule into `pve.yaml`** (small, no
   research needed — just hasn't been done yet).
2. **AzerothCore** — implement the interlocked egg fork,
   allocation/firewall reconciliation, and explicit resource/gameplay
   decisions in `plan.md`.
3. **Diagnose `gaming-stack-lab`'s Terraform workspace problem** before
   any future `terragrunt apply` against that stack is attempted for real.
4. **Decide on `stable`/`main` promotion** for this branch — an operator
   call, not something to do unprompted.
5. Optional, explicitly deferred by the operator: port-forwarding +
   hairpin NAT to make ARK's in-game "Join" button work directly from the
   public server-browser listing, instead of the console/Favorites
   workaround already confirmed working.

---

## Quick facts

| | |
|---|---|
| Trigger | Operator wants ARK: Survival Ascended alongside Minecraft on `gaming-stack-lab`; can't run both at once (memory); wants simpler on/off control than Portainer's UI |
| ARK feasibility | **Confirmed live 2026-09-19** — runs under Proton inside `gaming-stack-lab`'s Docker-in-LXC nesting, with two fixes (see below). No fundamental nesting/bubblewrap wall. |
| Control-plane choice | Pterodactyl (Panel + Wings), chosen over continuing with bare Portainer, specifically because the operator wants proper per-game start/stop/console UX and is already planning a third game (AzerothCore) |
| Topology | Panel: new LXC, `game_seg`. Wings: **must** run on `gaming-stack-lab` itself (same host as the Docker daemon it manages — Wings doesn't support a remote Docker daemon out of the box) |
| Migration model | `Foreverworld` was copied into a Wings-managed volume and passed operator in-game verification. The old Compose source remains stopped with a rollback snapshot through the confidence period. |
| AzerothCore Playerbots | Prepared as the next interlocked game: custom rendered egg, Playerbots policy, and LAN-only TCP 3724/8085 RouterOS rule (`*B1`) are complete. Egg import, mount association, server creation, and first boot remain. |

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

## ARK server creation through Wings — live test in progress (2026-09-20)

Testing the one genuinely unresolved risk from the smoketest: does ARK
survive Wings' hardcoded container constraints. Progress so far:

- **Egg import is genuinely UI-only** (confirmed from Panel's own
  `routes/admin.php` vs `routes/api-application.php` — Nest/Egg
  management has zero Application API surface, only session-authenticated
  `/admin/*` routes; deliberate, since install scripts run arbitrary code).
  Server *creation* from an existing egg is API-scriptable
  (`POST /api/application/servers`), confirmed and used.
- Imported the official `pelican-eggs/eggs` ARK egg (`docs/gaming-stack-lab/ark-survival-ascended-egg.json`,
  saved as a durable record), with `docker_images` narrowed to just
  `Proton 8`/`Proton Latest` (Proton 9 reported broken for ARK by the
  community). Real gate hit importing it: Panel's actual `docker_images`
  validation is a strict regex (`^[\w#\.\/\- ]*\|?~?[\w\.\/\-:@ ]*$`,
  from `EggFormRequest.php`) that rejects parentheses/punctuation in
  labels — my first attempt with descriptive labels failed with "docker
  images format is invalid"; fixed by using plain labels.
- Created a real server (`id: 1`, egg 15, node 1, `docker_image:
  ghcr.io/parkervcp/steamcmd:proton_8`, `ARGS_FLAGS=-nosteam` baked in
  from the start) via the Application API. 16GB memory, matching the
  smoketest's known minimum. Confirmed nothing else was running on the
  host at the time (23GB free) so this test doesn't contend with
  anything real.
- **Real bug #1, install trigger delay**: worried install never started
  (no activity for ~1 minute) — false alarm. Panel's server-creation call
  to Wings is synchronous (confirmed from `ServerCreationService.php` --
  a failure there would force-delete the server and return an error,
  which didn't happen), Wings just has an internal debounce before
  actually starting. Not a bug, just slower than expected.
- **Real bug #2, DNS resolution completely broken inside install
  containers**: `curl: (6) Could not resolve host: steamcdn-a.akamaihd.net`
  — install failed in under 20 seconds, twice. Root cause: Wings'
  `docker.network.dns` config defaults to `1.1.1.1`/`1.0.0.1` (public
  resolvers), but `game_seg`'s firewall only permits DNS (port 53) *to
  the router itself* (`192.168.60.1`), not forwarded to arbitrary
  external IPs — confirmed via a live, read-only MikroTik rule query
  before assuming. Fixed by pointing Wings' Docker network DNS at
  `192.168.60.1` instead (the same resolver every container in this zone
  already uses per its own `stack.yaml`) — avoids needing a new firewall
  rule entirely, more consistent than opening egress to a
  Cloudflare-specific IP. Required removing the already-created
  `pterodactyl_nw` Docker network and restarting Wings for the new DNS
  setting to actually apply (Docker doesn't hot-reload a network's DNS
  config). **Live-only fix, not yet folded into the playbook** — same
  class of gap as the Docker-subnet fix already flagged above.
- **Confirmed working after the fix**: SteamCMD is actively downloading
  (reached 63%+ of a ~12GB depot before this note was written) — proves
  the DNS root-cause diagnosis was correct, not a lucky retry.

## RESOLVED: ARK survives Wings' hardcoded constraints (2026-09-20)

**Install completed** (`Success! App '2430930' fully installed`, 9.8GB on
disk — a single-map install is much smaller than the ~100GB "all maps"
figure quoted in earlier research). Starting the server surfaced one more
real bug, then a conclusive result:

- **Real bug #3, install produced root-owned files, server runs as a
  different uid.** `mkdir: cannot create directory
  '/home/container/.steam/steam': Permission denied` on first start,
  cascading into Proton's own prefix-lock setup failing
  (`FileNotFoundError`). Root cause: the imported community egg's install
  script (unlike some other Pterodactyl eggs) never `chown`s the files it
  installs, and Wings didn't fix ownership afterward either — the whole
  volume ended up `root:root` while the container runs as `uid=999
  gid=991` (confirmed correct in `config.yml`'s `system.user`, so not a
  Wings misconfiguration, a gap in this specific egg). Fixed live via
  `chown -R 999:991` on the volume; a real production egg should add a
  `chown` step at the end of its own install script rather than rely on
  this being done for it.
- **The actual question this whole plan exists to answer**: does ARK
  survive Wings' hardcoded `ReadonlyRootfs: true` and fixed `CapDrop`
  list (confirmed from `container.go` — no `CapAdd` support at all,
  meaning `SYS_PTRACE` can never be granted to a Wings-managed server)?
  **Yes.** Crashpad initialized successfully (`started crashpad client
  handler`) with zero capability grant, `Steam Subsystem initialized:
  FAILED` occurred exactly as expected (harmless, `-nosteam` already
  baked into `ARGS_FLAGS`), and the server reached
  `Server: "gaming-stack-lab ARK smoketest" has successfully started!`,
  `Full Startup: 21.15 seconds`. **Confirmed operational, not just
  "logs looked fine"**: RCON connected live
  (`docker exec ... rcon -a 127.0.0.1:37015 ...` returned an interactive
  prompt, not "connection refused").
- **This means the original `SYS_PTRACE` requirement found in the raw
  smoketest was specific to that setup** (the `azixus/ARK_Ascended_Docker`
  image and/or its particular Proton build), not a universal ARK/Proton
  requirement — the official `pelican-eggs` egg on `steamcmd:proton_8`
  needs no such capability. Good news for the whole plan: no Wings fork,
  no capability workaround needed at all.

**Test server cleanup**: this was a throwaway validation server
(`ark-smoketest`, id 1) — deleted once this finding was recorded, not
kept running long-term or treated as `gaming-stack-lab`'s real ARK
instance.

## A real, permanent ARK server — live 2026-09-20

Created a second, real server (`ARK Survival Ascended`, id 2) with proper
settings and a freshly generated admin password (not the throwaway
smoketest one). Hit the exact same SteamCMD cold-cache "Missing
configuration" quirk found earlier in this session on the very first
install attempt — resolved the same way, by retrying. Also pre-applied
the known ownership fix (`chown -R 999:991`) before ever trying to start
it, avoiding re-discovering that bug a second time.

**Real bug #4, found getting this server actually startable from the
browser**: Panel's UI showed either "we're having trouble connecting to
your server" or (after a first partial fix) a permanently disabled Start
button, with no error banner. Root cause, found only in Wings' own
systemd journal, not anywhere in Panel's UI: `websocket: request origin
not allowed by Upgrader.CheckOrigin` (HTTP 403). The server console and
power controls connect via a **websocket straight from the browser to
Wings** (`ws://<node>:8080/...`), not proxied through Panel, and Wings
validates the request's `Origin` header against `config.yml`'s
`allowed_origins`, which defaults to `[]` — rejecting every browser,
always, with no visible error anywhere in Panel itself. Fixed by setting
`allowed_origins` to both addresses the operator might view Panel from
(`http://192.168.60.20`, `https://pterodactyl.lab.gibbsgreatly.xyz`) and
restarting Wings.

**This fix (and the two earlier live-only Wings config fixes — Docker
subnet collision, DNS egress) are now folded into
`deploy-gaming-stack-lab.yml` itself**, applied unconditionally so they
self-heal even against an already-existing `config.yml`, not just
left as live-only fixes for future re-reads of this doc to rediscover.
Verified the regex logic against the original pre-fix config content
(not the already-fixed live host, to avoid disrupting the real running
server) — produces the exact intended result.

**Confirmed working end-to-end after the origin fix**: server started
from Panel's own UI (not a raw `docker start`), independently verified
via `docker ps` (`Up`) and the game's own log
(`Server: "gaming-stack-lab ARK" has successfully started!`,
`Full Startup: 18.69 seconds`). This is now a real, permanent,
browser-controllable ARK server — the actual point of this whole plan.

### Connecting to the server — confirmed working methods

ARK: Survival Ascended has no Steam server-browser support at all (moved
to Epic Online Services) and the in-game "Unofficial" browser only shows
servers that successfully announce themselves to ARK's public master
server over the internet — a LAN-only server with nothing port-forwarded
(deliberately, for a private family server) structurally won't appear
there, confirmed live 2026-09-20 (checked the "Unofficial" list directly
with "Show Player Servers" on — not present, as expected). Steam's own
external Favorites ("Add server by IP") also doesn't work for ASA
specifically — its "Did not find any servers" check relies on the same
legacy Steam query protocol ASA no longer responds to, confirmed live.

**What actually works, confirmed live**:
1. Console direct-connect, always reliable: press `~`, `open 192.168.60.10:7777`.
2. `Ark.UseServerList 0` (console, from the main menu) then search the
   exact session name (`gaming-stack-lab ARK`) in the UNOFFICIAL tab's
   search box — **confirmed working 2026-09-20**, a genuinely different
   mechanism from the passive browser list (client-side search behavior,
   not server announcement), despite the server never registering
   publicly.

Deliberately did not pursue port-forwarding + NAT loopback to get the
server into the public "Unofficial" list for real, despite it being
offered as advice from elsewhere — that trades a private family server's
LAN-only footprint for public internet exposure to solve a menu
convenience problem that already has a working, no-exposure answer.

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
