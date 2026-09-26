# gaming-stack-lab plan

Written following `docs/agent-design/step-packet-schema.md`'s shape.
Triggered by wanting ARK: Survival Ascended alongside Minecraft
(`foreverworld`) on `gaming-stack-lab`, and wanting a simpler start/stop
surface than Portainer's UI for switching between the two (can't run both
at once — memory). See `README.md` for the full ARK smoketest findings;
summarized here only as much as the decisions below need.

**Current state (2026-09-26):** Panel, Wings, ARK, and the migrated
`Foreverworld` Minecraft server are live. Minecraft has passed world/mod/RCON
checks and the game-slot interlock has passed both directions: each game is
blocked with exit 75 while the other holds the slot. The old Compose source
and pre-copy ZFS snapshot remain as rollback assets. AzerothCore Playerbots is
also live under Wings; its first real LAN login and deliberate `addclass` bot
creation have passed. Party behaviour remains the final operator gameplay
check.

## Research this plan is based on

- **ARK: Survival Ascended is genuinely feasible** on `gaming-stack-lab`'s
  Docker-in-LXC nesting — confirmed live via a manual smoketest
  (2026-09-19), not assumed. Full detail in `README.md`. Two concrete
  fixes come out of it, needed wherever the ARK egg/compose eventually
  gets written: `cap_add: [SYS_PTRACE]` and a `-nosteam` launch flag.
- **Pterodactyl topology**: Panel (Laravel/MySQL/Redis/nginx — the web
  UI/API/DB) is location-agnostic; Wings (the daemon that actually
  starts/stops game containers) must run on the same host as the Docker
  daemon it controls — it has no remote-Docker support. So Panel gets its
  own LXC; Wings runs on `gaming-stack-lab` itself, replacing (not
  alongside) Portainer's role in managing the game containers there, to
  avoid the two fighting over the same containers.
- **Migration, not replacement**: Wings expects to own the servers it
  manages (its own directory convention, `/var/lib/pterodactyl/...`,
  driven by egg definitions) — `foreverworld`'s existing world/mods/config
  aren't lost, but do need to be copied into Wings' managed volume after
  creating the server via a Forge/NeoForge egg, matching the reviewed
  loader jar version rather than whatever Wings would install fresh.
- **Panel zone: `game_seg`** — confirmed with the operator 2026-09-20,
  over the mgmt_seg alternative (which would need a new cross-zone
  firewall rule for Panel→Wings traffic; `game_seg` keeps that same-zone).
  `game_seg`'s own zone description already reads "Minecraft and future
  dedicated game servers."
- **Official Pterodactyl Panel docker-compose reference** — fetched
  directly from `pterodactyl/panel`'s own repo
  (`docker-compose.example.yml`, 2026-09-20) rather than reconstructed
  from memory: `ghcr.io/pterodactyl/panel` + `mariadb:11` + `redis:alpine`,
  Redis-backed cache/session/queue drivers, `DB_PASSWORD` threaded via a
  YAML anchor. Latest real release tag confirmed via the repo's GitHub
  Releases API: `v1.15.1` (not `:latest`, matching this repo's
  no-unpinned-tag convention elsewhere).

## Decisions resolved

- Panel is a new stack, own LXC, `game_seg` zone (operator-confirmed
  2026-09-20).
- Wings runs on `gaming-stack-lab` (no choice — Wings requires local
  Docker access).
- Panel is fronted by Traefik/Authentik the same way every other admin
  panel in this repo is — `auth.mode: forwardAuth` in `edge.yaml`, not
  native OIDC (Pterodactyl has no built-in OIDC support; this is an
  access gate in front of Panel's own login, same tradeoff already
  accepted for other tools in this repo without native SSO support).
- Additive, not destructive: `foreverworld`'s existing compose-managed
  Minecraft instance stays running and untouched until the Wings-managed
  replacement is verified working (world loads, mods intact, players can
  connect) — mirrors `media-stack-lab`'s own legacy-preservation pattern.
- ARK gets added as a Wings-managed server from the start (not
  compose-managed like Minecraft is today), carrying forward the two
  fixes found in the smoketest.

## Open questions — not yet resolved, do not default silently

- ~~**Panel IP/VMID**~~ — **resolved 2026-09-20**, confirmed live via a
  read-only production API check against `pve`
  (`GET /cluster/resources?type=vm`, operator-approved in chat,
  `TASK_APPROVAL=gaming-stack-lab-panel-ip-vmid-check`). VMID `60020` is
  not in use by any LXC/QEMU guest on `pve` — the only VMID in the
  `60xxx` range at all is `60010` (`gaming-stack-lab` itself). `game_seg`
  (VLAN 60) has exactly one member in both the live resource list and
  `pve.yaml`, so `192.168.60.20` is unused too. `gaming-lab-01` is no
  longer blocked on this.
- ~~**Panel DB secrets**~~ — **resolved 2026-09-20.**
  `PTERODACTYL_LAB_DB_PASSWORD` / `PTERODACTYL_LAB_DB_ROOT_PASSWORD`
  generated (`openssl rand -base64 24`) and added to
  `terraform/secrets.common.enc.yaml` by the operator, confirmed present
  via `./with-secrets env | grep PTERODACTYL`. `PTERODACTYL_LAB_API_KEY`
  still open — can't be created until Panel itself is deployed and
  bootstrapped (see the Wings↔Panel pairing entry below).
- ~~**Wings↔Panel pairing**~~ — **resolved 2026-09-20.** Mostly
  API-scriptable, not UI-only — same lesson `media-lab-06` learned the
  hard way (initially assumed UI-only, turned out to have a real API
  path). Confirmed directly from `pterodactyl/panel`'s own source (routes,
  `StoreNodeRequest`/`StoreAllocationRequest`/`StoreLocationRequest`,
  `NodeConfigurationController`) and `pterodactyl/wings`'
  `cmd/configure.go`: real endpoints exist for Location/Node/Allocation
  creation and node-configuration lookup, and Wings' own `configure`
  subcommand (`--panel-url`/`--token`/`--node`/`--override`, all real
  flags) does the actual config.yml fetch-and-write — no need to
  hand-serialize the API's JSON response. The one genuinely manual,
  circular step: bootstrapping the first Panel admin user and an
  Application API key, since nothing can call the API before a key
  exists. Same class of one-off as the Jellyfin/Immich API keys in
  `media-stack-lab`'s own work.
- ~~**Wings install method**~~ — **resolved 2026-09-20, operator-confirmed**:
  idempotent Ansible role via `provision.sh`, not manual/hand-curated like
  Minecraft's own content — Wings itself is infrastructure, the per-game
  content (modpack, ARK egg) stays hand-curated regardless. See
  `gaming-lab-03-wings-install` below.
- ~~**Does ARK survive Wings' hardcoded container constraints at all?**~~
  — **RESOLVED 2026-09-20, live test, not just research.** Yes. Created a
  real ARK server under real Wings (`pelican-eggs` official egg,
  `steamcmd:proton_8`, `-nosteam` baked in) and watched it reach
  `Server: "..." has successfully started!` / `Full Startup: 21.15
  seconds`, confirmed operational via a live RCON connection (not just
  log-watching). Crashpad initialized fine with zero capability grant —
  Wings really does have no `CapAdd` support (confirmed from
  `container.go`), but it turned out not to matter here. The original
  `SYS_PTRACE` requirement from the raw smoketest was specific to that
  setup (the `azixus` image/Proton build), not a universal ARK/Proton
  need. Three more real bugs found and fixed getting here (DNS egress,
  install-time ownership, Panel API routing) — full detail in
  `README.md`'s "RESOLVED: ARK survives Wings' hardcoded constraints"
  section. No Wings fork or capability workaround needed after all.

- **Egg image/version correction, 2026-09-20 (confirmed correct by the
  live test above)**: the official
  `pelican-eggs/eggs` ARK egg (the one to actually use under Wings, not
  the smoketest's standalone `azixus` image) defaults to
  `ghcr.io/parkervcp/steamcmd:proton` — real community reports say
  **Proton 9 doesn't work well for ARK specifically**, use the egg's
  `steamcmd:proton_8` image variant instead. Also corrected this egg's
  real default ports (`7777` game, `7778` peer — auto game+1, not
  separately allocatable, `27015` query, `37015` RCON) — different from
  the smoketest's own `azixus`-image defaults (`7790`/`32330`) that had
  been hardcoded into `gaming-lab-03`'s Wings allocations by mistake;
  fixed in the real playbook, see its hand-back below.
- **Minecraft egg content for `foreverworld`'s modpack**: RESOLVED
  2026-09-26 — see "`foreverworld` migration to Wings" below for the real,
  verified facts (loader/version/host/data path) and the step-by-step plan.
- **AzerothCore**: mentioned as a future addition, not researched at all
  yet. Deliberately out of scope for this plan's steps — worth its own
  research pass (does it need a persistent MySQL/game data volume with
  different backup semantics than a typical game egg? is there a
  maintained community Pterodactyl egg for it, the way there is for ARK
  and Minecraft?) before any step block gets written for it.
- **Existing Portainer registration**: `gaming-stack-lab` currently has
  `portainer_agent: true` and is Portainer-managed. Once Wings takes over
  container lifecycle there, decide whether to flip that to `false`
  (matching automation-only stacks) or leave it for read-only visibility
  — not yet decided, low-stakes either way but should be explicit rather
  than left inconsistent.

---

## Step: gaming-lab-01-panel-stack-request

IP/VMID confirmed free 2026-09-20 (see Open questions above) — this step
is ready to execute.

```yaml
id: gaming-lab-01-panel-stack-request
title: Author stack-request.yaml for the new pterodactyl-lab Panel stack
depends_on: []

change: >
  Create terraform/lxc/stacks/pterodactyl-lab/stack-request.yaml with
  exactly this content. IP/VMID are candidates pending live confirmation
  (see plan.md's open questions) -- do not run scaffold-stack.sh against
  this file until that check has actually been done.

    stack_yaml:
      hostname: pterodactyl-lab
      ip_address: "192.168.60.20/24"
      gateway: "192.168.60.1"
      dns_server: "192.168.60.1"
      network:
        zone: game_seg
      vmid: 60020
      cores: 2
      memory: 4096
      swap: 512
      rootfs_size: 8
      storage_profile: platform-default
      docker_storage_size: "10G"
      template_name: "debian-13.1-2-docker-template.tar.gz"
      tags:
        - docker
        - gaming
        - pterodactyl
        - control-panel
      depends_on: []
      provides:
        - service: pterodactyl-panel
          port: 80
          protocol: tcp
      ansible_playbook: deploy-pterodactyl-lab
      deployment_tier: apps
      portainer_agent: true

    compose_requirements: |
      Three services, container_name prefixed pterodactyl-lab-<service>,
      restart: unless-stopped on all three. Adapted from the real,
      official pterodactyl/panel docker-compose.example.yml (fetched
      2026-09-20), not reconstructed from memory -- only the parts
      genuinely specific to this repo change (secrets via SOPS/env, no
      direct 80/443 host port bind since Traefik fronts this like every
      other stack, image tag pinned instead of :latest).

      database:
        image: mariadb:11
        command: --default-authentication-plugin=mysql_native_password
        volumes:
          - pterodactyl-db:/var/lib/mysql
        environment:
          - MYSQL_DATABASE=panel
          - MYSQL_USER=pterodactyl
          - MYSQL_PASSWORD=${PTERODACTYL_LAB_DB_PASSWORD}
          - MYSQL_ROOT_PASSWORD=${PTERODACTYL_LAB_DB_ROOT_PASSWORD}

      cache:
        image: redis:alpine

      panel:
        image: ghcr.io/pterodactyl/panel:v1.15.1
        volumes:
          - pterodactyl-var:/app/var
          - pterodactyl-nginx:/etc/nginx/http.d
          - pterodactyl-logs:/app/storage/logs
        ports: ["80:80"]
        depends_on: [database, cache]
        environment:
          - APP_URL=https://pterodactyl.${LAB_DOMAIN}
          - APP_TIMEZONE=Pacific/Auckland
          - APP_ENV=production
          - APP_ENVIRONMENT_ONLY=false
          - CACHE_DRIVER=redis
          - SESSION_DRIVER=redis
          - QUEUE_DRIVER=redis
          - REDIS_HOST=cache
          - DB_HOST=database
          - DB_PORT=3306
          - DB_PASSWORD=${PTERODACTYL_LAB_DB_PASSWORD}
          - HASHIDS_LENGTH=8

      top-level volumes: block declaring pterodactyl-db, pterodactyl-var,
      pterodactyl-nginx, pterodactyl-logs as named Docker volumes.

      The official example maps host ports 80 and 443 directly and
      terminates its own TLS -- do not do that here. This stack follows
      every other stack's pattern instead: expose only port 80
      internally, no host TLS cert handling in this container, and let
      Traefik (edge.yaml, forwardAuth mode) do TLS termination and the
      Authentik access gate, matching how every other admin panel in
      this repo (Portainer, NetBox, ...) is fronted.

    compose_forbidden: |
      binding host ports 80/443 directly (Traefik fronts this),
      LE_EMAIL / any in-container Let's-Encrypt handling, :latest or any
      unpinned image tag, a literal database password anywhere in this
      file, removing the Redis cache/session/queue drivers in favor of
      file-based (every other stack in this repo that has a choice uses
      the shared-service backend, not file-local state).

    contract_facts: |
      - Zone: game_seg (VLAN 60) -- confirmed with operator 2026-09-20
      - Nothing depends on this stack yet; Wings on gaming-stack-lab will
        depend on it once paired (not yet a step -- see plan.md's open
        questions on Wings<->Panel pairing)
      - Fronted by Traefik/Authentik forwardAuth, not native OIDC --
        Pterodactyl has no built-in OIDC support
      - IP 192.168.60.20 / VMID 60020 are CANDIDATES ONLY -- confirm free
        via a live read-only Proxmox API check before scaffolding, same
        discipline media-stack-lab's plan required for its own IP/VMID
      - Implementation files: terraform/lxc/stacks/pterodactyl-lab/
        stack.yaml, terragrunt.hcl, docker-compose.yml, STACK_CONTRACT.md
        (all new), plus
        terraform/lxc/ansible/playbooks/deploy-pterodactyl-lab.yml (new)
        -- none of these exist yet.

scope:
  allowed_paths:
    - terraform/lxc/stacks/pterodactyl-lab/stack-request.yaml
  forbidden_actions:
    - "Running scaffold-stack.sh -- separate operator step, and only after the IP/VMID live-check"
    - "Any terragrunt or provision.sh command"
    - "Writing a literal database password into the file"
    - "Guessing whether 192.168.60.20/60020 are actually free -- report the gap, don't assume"

gates:
  - id: stack-request-exists
    cmd: "test -f terraform/lxc/stacks/pterodactyl-lab/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: stack-request-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/pterodactyl-lab/stack-request.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: no-hardcoded-password
    cmd: "! grep -qE 'MYSQL_(ROOT_)?PASSWORD=[^$]' terraform/lxc/stacks/pterodactyl-lab/stack-request.yaml"
    expect: "exit 0 (i.e. no literal password found)"
    critical: true
  - id: image-tags-pinned
    cmd: "! grep -E '^\\s*image:' terraform/lxc/stacks/pterodactyl-lab/stack-request.yaml | grep -qE ':latest\\s*$'"
    expect: >-
      exit 0 (i.e. no image: line ends in :latest). The original form of
      this gate (plain `grep -qE ':latest'` over the whole file) false-
      positived on this file's own prose explaining why :latest is
      forbidden -- found running it for real 2026-09-20, not
      theoretically. Scoped to image: lines only.
    critical: true
```

**Done 2026-09-20 — see `README.md`'s hand-back for this step.** All 4
gates pass; one gate bug found and fixed (`image-tags-pinned` was
matching this file's own prose, not real image tags — see README for the
corrected command, already updated above). `stack-request.yaml` is the
authoritative record now.

## Operator step: gaming-lab-02-scaffold

Not a step block — `scaffold-stack.sh` is itself marked DEPRECATED in its
own header (`opencode` is a deprecated path in this lab, per operator
directive), same situation `media-lab-02-scaffold` hit. Depends on
`gaming-lab-01-panel-stack-request` (the `stack-request.yaml` it needs as
input).

**Done differently 2026-09-20, same reason as `media-lab-02`: no
`opencode`.** Wrote all 5 files by hand instead
(`terraform/lxc/stacks/pterodactyl-lab/{stack.yaml,docker-compose.yml,
STACK_CONTRACT.md,terragrunt.hcl}` and
`terraform/lxc/ansible/playbooks/deploy-pterodactyl-lab.yml`), then ran
the same real validators the script would have — all pass. Full detail
in `README.md`'s hand-back for this step, including a working-directory
gotcha for `ansible-playbook --syntax-check` worth remembering next time
(must run from `terraform/lxc/ansible/`, not the repo root, for the
relative `roles_path` in that directory's `ansible.cfg` to resolve).

## Step: gaming-lab-03-wings-install

```yaml
id: gaming-lab-03-wings-install
title: Install and pair Wings on gaming-stack-lab with pterodactyl-lab's Panel
depends_on: [gaming-lab-02-scaffold]

change: >
  Replace gaming-stack-lab's ansible_playbook (stack.yaml) from the
  shared "deploy-portainer-agent" to a new dedicated
  "deploy-gaming-stack-lab", and create
  terraform/lxc/ansible/playbooks/deploy-gaming-stack-lab.yml carrying
  forward deploy-portainer-agent.yml's existing plays (Docker/Portainer
  base, Portainer registration, unattended upgrades) unchanged, plus a
  new play that idempotently creates a Location/Node/Allocations via
  pterodactyl-lab's Application API (checked-before-create, not blindly
  reposted) and pairs Wings via its own `wings configure` subcommand
  (--panel-url/--token/--node/--override, real flags confirmed from
  pterodactyl/wings' cmd/configure.go), then installs the Wings binary
  and a systemd unit. Only gets Wings itself running and paired -- does
  not create any game server under it.

scope:
  allowed_paths:
    - terraform/lxc/stacks/gaming-stack-lab/stack.yaml
    - terraform/lxc/ansible/playbooks/deploy-gaming-stack-lab.yml
  forbidden_actions:
    - "Touching /srv/docker/minecraft/foreverworld/ in any way -- this step is Wings infrastructure only, no game data"
    - "Any terragrunt or provision.sh command -- file authoring only in this step"
    - "Creating a Minecraft or ARK server under Wings -- separate, reviewed work"

gates:
  - id: playbook-syntax-checks
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check playbooks/deploy-gaming-stack-lab.yml"
    expect: >-
      exit 0. Must run from terraform/lxc/ansible/ itself, not the repo
      root -- that directory's ansible.cfg has a relative roles_path that
      only resolves from there (found for real running gaming-lab-02's
      own syntax-check, not theoretically).
    critical: true
  - id: stack-yaml-still-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/gaming-stack-lab/stack.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: foreverworld-untouched
    cmd: "git diff --name-only | grep -q 'foreverworld' && echo FOUND || echo clean"
    expect: "clean -- any match means this step touched Minecraft data, which must not happen"
    critical: true
```

**Done 2026-09-20 — see `README.md`'s hand-back for this step.** Both
files written, both gates pass (`foreverworld-untouched` confirmed clean
— `git diff --name-only` shows only the two intended files).
The Panel admin bootstrap and both Application/Client API keys are now live
and SOPS-backed; this historical step is complete.

---

## `foreverworld` migration to Wings

Written 2026-09-26, at the operator's request for a clear step-by-step
plan before any execution. Repository implementation is complete; no live
migration phase has run. The authoritative execution and rollback procedure
is `docs/gaming-stack-lab/minecraft-migration.md`.

### Verified facts (read-only checks, not assumptions)

- **Host**: `gaming-stack-lab` (same host Wings/ARK already run on — not
  the legacy `gaming-stack`/CT 103 host `terraform/lxc/stacks/gaming-stack/`
  describes, which the operator confirmed is unused, kept only for
  research).
- **Data path**: `/srv/docker/minecraft/foreverworld` — already on the
  500GB dedicated `gaming-containers` mount (the same one Wings itself
  was migrated onto), not the cramped rootfs.
- **Currently**: Portainer-managed (`docker compose`), not Wings-managed.
  Confirmed stopped as of 2026-09-26 (memory contention with the running
  ARK server — the exact problem this whole project exists to solve).
- **World**: `level.dat` last modified 2026-09-20 09:39, ~6 days before
  this plan was written — real, recently-played data, not abandoned.
- **Base image**: `itzg/minecraft-server:java21` (pulled via Harbor) —
  same image family Pterodactyl's community `itzg`-based eggs are built
  around.
- **Loader/version**: `TYPE=NEOFORGE`, `VERSION=1.21.1`,
  `NEOFORGE_VERSION=21.1.234`. Modpack is "Wildworks" — a pre-built
  NeoForge server release extracted onto disk (own `run.sh`, `mods/`,
  `config/`), not declared via any `CURSEFORGE_*` env var, so there is no
  mod list to transcribe — the mods are the files on disk.
  `OVERRIDE_SERVER_PROPERTIES=false`, so the container just runs what's
  already there.
  Source: `terraform/lxc/ansible/playbooks/deploy-minecraft-wildworks.yml`
  (real, current — `terraform/lxc/stacks/gaming-stack/foreverworld-docker-
  compose.yml`'s `TYPE=FORGE`/`1.20.1` is stale, superseded by this
  playbook per its own git history).
- **Ports**: `25565` game, `25575` RCON. RCON password is the SOPS
  secret `MINECRAFT_FOREVERWORLD_RCON_PASSWORD`.
- **Not carried into this migration**: the `minecraft-monitor` (mc-monitor
  → Prometheus) sidecar from the current compose project. Wings runs one
  container per server, no sidecar model — operator explicitly deprioritized
  this when asked, treated as a separate future follow-up, not blocking.

### Implementation correction and execution status

The maintained Pelican NeoForge egg is not `itzg`-based and does not preserve
this pack's release-native `run.sh` path. The checked-in
`wildworks-neoforge-egg.json` therefore deliberately uses the maintained
Java 21 yolk while starting the already-reviewed Wildworks release directly.
Egg import and shared-mount assignment are manual Panel-admin operations;
server creation remains Application-API-driven.

The node now has a repository-defined, non-blocking `flock` interlock shared
by ARK, Minecraft, and future games. It prevents concurrent starts rather
than relying on an operator convention. The full inventory, allocation,
snapshot, copy-manifest, ownership, checksum, startup, two-direction
exclusion, rollback, and retirement gates are in `minecraft-migration.md`.

## AzerothCore (with Playerbots) — new server under Wings

Written 2026-09-26, at the operator's request. Not yet started. This is a
brand-new server, not a migration — nothing existing is at risk here the
way `foreverworld`'s data is.

### Verified facts

- **The egg**: `Nazgile94/pelican-acore` (`egg-azerothcore-aio.json`) —
  a single container bundling MySQL 8.4, authserver, worldserver, client
  data, and module management. Confirmed by reading the actual egg JSON's
  `variables` array directly, not a README summary.
- **Honest caveat, not hidden**: this repo's own `AI-NOTICE.md` discloses
  it was built with substantial ChatGPT assistance and is a
  single-maintainer community project — a different maturity tier than
  the `pelican-eggs`-org ARK egg already in production here. Worth
  knowing going in, not a reason by itself to avoid it (no
  `pelican-eggs`-org AzerothCore egg exists — checked — this is the real
  option, not one of several).
- **Playerbots, confirmed real and exact**: `USE_PLAYERBOTS=1` switches
  the egg to `mod-playerbots/azerothcore-wotlk` (the correct fork —
  standard AzerothCore will not compile against the Playerbots module,
  confirmed from the module's own install docs) automatically.
  `PLAYERBOTS_MODULE_BRANCH` defaults to `master`. The egg's own
  `MAP_UPDATE_THREADS` variable description explicitly recommends `4`
  when Playerbots is enabled (default `1` otherwise) — apply this, not
  the default.
- **Private party-only bot policy (operator decision, 2026-09-26):** at
  most two humans will use the realm. Do not accept the module's defaults of
  500 roaming random bots. The fork must set
  `AiPlayerbot.RandomBotAutologin=0`, `AiPlayerbot.MinRandomBots=0`, and
  `AiPlayerbot.MaxRandomBots=0`. Bots are to be added deliberately to a
  player's party; the per-party bot cap still needs an operator choice.
- **Client data licensing**: `CLIENT_DATA_AUTO_DOWNLOAD=1` (default)
  pulls DBC/maps/vmaps/mmaps via AzerothCore's own standard `acore.sh
  client-data` tooling — long-established, normal practice in this
  community, not something novel. This is *extracted data*, not
  Blizzard's actual client executable/assets — no WoW client purchase or
  upload needed for the server side. Running any WoW private server
  still sits in the general legal gray area private servers always have
  under Blizzard's EULA — worth the operator's own awareness, not a
  decision this plan makes for them.
- **Disk**: egg's own docs recommend 30GB+ (source compile, client data,
  database). `gaming-stack-lab`'s `/srv/docker` mount has ~480GB free as
  of the last check (2026-09-24) — no capacity concern.
- **Host/allocations**: `gaming-stack-lab`, same Wings node as ARK and
  (once migrated) Minecraft. Needs its own allocations: `WORLD_PORT`
  (default `8085`) and `AUTH_PORT` (default `3724`, standard WoW
  3.3.5a) — confirm neither collides with ARK's or the new Minecraft
  server's allocations before creating it.

### Steps (AzerothCore)

1. **Create a checked-in interlocked egg fork** before import. Narrow its
   `docker_images` field for Panel validation, mount `/game-slot` read-only,
   and take the non-blocking shared `flock` before the bundled database or
   game processes start. `scripts/render-azerothcore-playerbots-egg.sh`
   renders the pinned-upstream import artifact with the agreed Playerbots
   policy. Verify the selected image contains `flock` before import.
2. **Reconcile allocations** for `WORLD_PORT`/`AUTH_PORT` in the managed
   gaming-stack deployment, then import the reviewed egg manually through
   Panel Admin. Egg import is not exposed by the Application API. Associate
   the same `game-slot-lock` mount with the new egg and create the server via
   the Application API only after confirming the allocations are free.
   **Completed 2026-09-26:** imported egg 19 into the `World of Warcraft`
   nest, associated it with mount 1 (`game-slot-lock`), and created unassigned
   node-1 allocations 7 (`192.168.60.10:3724`) and 8
   (`192.168.60.10:8085`).
3. **Set startup variables**: `USE_PLAYERBOTS=1`,
   `MAP_UPDATE_THREADS=4`, `EXPANSION=2` (WotLK), `REALM_ADDRESS=auto`,
   and a two-human player limit. Set the three explicit no-random-bots
   variables above, plus the operator-chosen per-party bot cap and rate
   multipliers (Blizzlike defaults are `1` for every rate — a deliberate
   choice question, not something to default silently given this project's
   ARK experience with rate multipliers). **Completed 2026-09-26:** the live
   server has the agreed values: two human slots, four map-update threads,
   Playerbots enabled, all configured rates at `1`, random-bot
   autologin/minimum/maximum at `0`, a maximum of four deliberately added
   bots, and four offline AddClass accounts for dependable class/faction
   selection. Those prepared characters do not autologin or roam.
4. **First boot**: expect a long first start (core compile + client-data
   download + DB import) — watch the console live (same websocket
   approach used all night), not just poll for "running", since a
   silent early failure here would look identical to "still compiling"
   for a long time.
5. **Verify**: authserver/worldserver both up, realm visible, a test
   login actually works, bots can be spawned/added. **Completed 2026-09-26:**
   both services are listening on `192.168.60.10:3724`/`:8085`; operator
   account `gibbs` logged in as human paladin `Aldred` from the LAN and
   successfully added an on-demand Playerbot. The remaining operator check is
   that the bot joins/follows/assists Aldred's party as desired. Operator
   verification is still required for the "does this actually feel right"
   gameplay parts, same as every other server in this project.
6. **Decide on rate multipliers and player limits** as a real, explicit
   choice once the operator has played with it — not defaulted
   silently, matching the standing lesson from ARK's XP-multiplier saga
   this session.
7. **Completed 2026-09-26 — LAN firewall prerequisite:** the operator added
   RouterOS forward rule `*B1`, allowing only `192.168.1.0/24` to reach
   `gaming-stack-lab` (`192.168.60.10`) on TCP 3724/8085. It is before the
   existing `game_seg` default-deny rule, has no WAN match, and was verified
   afterward through the read-only RouterOS API. The matching declarative
   intent is in `terraform/lxc/network/pve.yaml`.

8. **Before production creation**, set the agreed explicit RAM/CPU/disk limits
   (16 GiB / 4 CPU / 60 GiB). The game-slot interlock prevents concurrent
   games but does not size an AzerothCore build.

## Not covered by this plan

- `terragrunt apply`, `provision.sh --stack pterodactyl-lab`, and
  health-check validation — real infrastructure steps, stay
  manual/operator-run, same as every other plan in this repo.
