# T-Pot honeypot — management plan

## Why this exists

T-Pot has been running on a Raspberry Pi 5 (`raspberrypi` /
`tpot.gibbsgreatly.xyz`, `192.168.1.28`) for a while, producing real data
(steady ~223k events/day since at least 2026-08-31), but it never got
brought into this repo's documentation/governance:

- It's not a Proxmox guest, so it was never touched by the
  `terraform/lxc/` conventions, `PRODUCTION_NODES` controls, or
  `docs/threat-vuln-platform/`'s Ansible-managed sync pattern.
- `docs/dhcp-refactor/current-state.md` found its DHCP lease only as an
  unlabeled `raspberrypi` fingerprint — nobody had gone back and labeled
  it once identified.
- Two personal repos (`~/git/tpotce-analysis`, `~/git/security-analysis`)
  contain overlapping, incomplete attempts at syncing its findings into
  Elasticsearch, neither deployed anywhere, neither referenced from this
  repo except as a deferred line in `docs/threat-vuln-platform/plan.md`.

This doc reviews how T-Pot actually works, what access exists today, and
proposes a phased plan to fix that.

## How T-Pot (CE, HIVE type) works

T-Pot CE is Telekom Security's multi-honeypot platform: a Docker Compose
stack of ~20 independent honeypot daemons (each emulating a different
service/protocol — SSH, Telnet, SMB, RDP, Elasticsearch, Redis, VNC,
printers, ICS/SCADA via Conpot, etc.) plus a shared observability stack
(Suricata for network-level detection, Logstash for normalization,
Elasticsearch for storage, Kibana for exploration, plus a live "attack
map" console). This instance is `TPOT_TYPE=HIVE` — the standalone,
self-contained mode (as opposed to `SENSOR`, which forwards to a
separate HIVE, or `MOBILE`).

Confirmed live on this host, 2026-09-30:

| Container | Role |
|---|---|
| snare / tanner / tanner_api / tanner_redis / tanner_phpox | Web-app honeypot (SNARE/TANNER) |
| heralding | Credential-harvesting honeypot (multi-protocol) |
| h0neytr4p, honeytrap, ipphoney, miniprint, elasticpot, redishoneypot, wordpot, mailoney, sentrypeer, conpot_kamstrup_382, conpot_guardian_ast | Individual protocol/service honeypots |
| p0f | Passive OS fingerprinting |
| suricata | Network IDS, feeds `logstash-*` alerts |
| spiderfoot | OSINT recon tool (bundled, not honeypot traffic) |
| elasticsearch, kibana, logstash | Internal ELK stack (8.19.x) |
| nginx | Web portal / reverse proxy for the UI |
| map_data, map_web, map_redis | Live attack-map visualization |
| ewsposter | Forwards events to Deutsche Telekom's shared threat-intel feed (opt-in, upstream project default) |
| honeyaml | YAML-config-driven honeypot templates |
| tpotinit | One-shot init/bootstrap container |

Two more honeypots (**Beelzebub**, **Galah** — LLM-backed SSH/web
honeypots) are *configured* in `.env` (pointing at
`http://ollama.local:11434`, which doesn't resolve on this host) but are
**not part of this compose deployment** — they're a documented
non-standard-edition add-on the operator never actually enabled. Not a
bug; just unused config.

**Daily maintenance**: a root cron job (labeled `#Ansible: T-Pot Daily
Reboot` in the crontab, though nothing in this repo manages it) runs at
04:09 local, stops `tpot.service`, prunes Docker containers/images/
volumes, and reboots. This is T-Pot's own documented upstream pattern
for keeping a long-running instance clean, not something we introduced.

**Persistence**: `TPOT_PERSISTENCE=on`, 30 logrotate cycles for the raw
honeypot logs under `~/tpotce/data` (currently 1.2G). This is separate
from Elasticsearch's own retention — there's no ILM policy trimming the
`logstash-*` indices, so they accumulate indefinitely (see Gaps below).

## What access we know about

| Surface | Detail |
|---|---|
| SSH | `~/.ssh/config` alias `tpot` → `tpot.gibbsgreatly.xyz:64295`, user `steve`, key-only auth (1 key in `authorized_keys`), **passwordless full sudo** (`(ALL) NOPASSWD: ALL`). A second alias `tpot-lxc` → `192.168.1.31:64295` exists but is unreachable/dead — looks like a stale entry from an earlier plan to run this as a Proxmox LXC that was never followed through; worth removing once confirmed. |
| Web UI | Nginx portal, LAN-exposed on `:64294` and `:64297` (0.0.0.0). Three htpasswd users configured in `~/tpotce/.env` (`WEB_USER=`, base64-encoded `user:$apr1$...` pairs) — not decoded as part of this review. |
| Internal Elasticsearch | `:64298`, bound to `127.0.0.1` only — SSH-tunnel-only by design. This is what both existing sync scripts use. |
| Internal Kibana | `:64296`, also `127.0.0.1`-only. |
| Sensor ingest | `LS_WEB_USER` (per-sensor Logstash credential) — unset; irrelevant since no `SENSOR`-type satellite exists. |
| Network exposure | Single NIC, `192.168.1.28/24` (client LAN), no MikroTik NAT/port-forward rule found anywhere in this repo pointing at it — confirmed LAN-only, matching `tpot_ai_reporter_config.yaml`'s own stated assumption (`network_type: home_lab_lan_only`, "treat any LAN source as potentially hostile"). |
| DHCP | Static-looking lease but not a MikroTik reservation; identified only as `raspberrypi` (MAC `88:A2:9E:57:E6:24`) in `docs/dhcp-refactor/`, never labeled. |
| Secrets custody | Everything (SSH key, web htpasswd, the two sync repos' `.env`/API-key files) lives outside OpenBao, outside this repo — pure local-file custody on the Pi and on the operator's workstation. |

## Current state (verified live, 2026-09-30)

- `tpot.service` active; 29/29 containers up, most `healthy` or with no
  healthcheck defined; two (`conpot_kamstrup_382`, `conpot_guardian_ast`)
  showed `health: starting` at check time — not a hard fault, first-load
  behavior for those images.
- Internal ES: `status: green`, 98/98 shards active. Daily indices from
  2026-08-31 through 2026-09-29 present and roughly constant in size
  (~223k docs/day, 32-40MB/day) — a real, steady LAN-noise/scan baseline,
  not a broken or idle sensor.
- Resources: 424G/459G disk free, 5.9G/15G RAM free, no CPU throttling
  (`vcgencmd get_throttled` → `0x0`).
- 63 apt packages upgradable — this host isn't on this repo's
  `unattended_upgrades` role (it's outside the Ansible fleet entirely),
  so it isn't on the same patch cadence as everything else in the lab.
- **Fixed live during this review**: `journald` had no persistent
  storage (`Storage=auto` with no `/var/log/journal` directory), so the
  operator's power-cycle earlier today left zero log trail —
  `journalctl --list-boots` showed only the current boot. Created
  `/var/log/journal` and restarted `systemd-journald`; confirmed
  persistent storage is now active. (Root cause of that specific reboot
  is known — the operator power-cycled it manually after losing
  connectivity — so this fix is about *future* incidents, not that one.)

## Gaps found (not yet fixed — decisions or work needed)

1. **No ingestion into this lab's own OpenSearch/threat-vuln-platform.**
   `docs/threat-vuln-platform/plan.md` already reserves a `tpot-events`
   slot in its `*-events` index family and explicitly defers it pending
   "T-Pot ingestion, when it starts." Two independent, personal, both
   half-finished attempts exist outside this repo:
   - `~/git/tpotce-analysis` — a working, previously-run standalone
     script (`tpot_es_sync.py`) with real historical output (daily
     AI-generated reports through 2026-01-02), but self-contained
     (its own `.env`, its own state index, its own external ES target)
     and not Ansible-managed or deployed anywhere persistent.
   - `~/git/security-analysis` — a newer monorepo meant to unify
     Wazuh/Security-Onion/T-Pot sync under one shared framework
     (`SECPIPE_PREFIX` namespacing, shared setup/asset-apply code). Its
     `tpotce` sync/setup were smoke-tested (50-doc dry-run + write
     against `lab1-tpot-raw`) but its `cli.py`/`report.py` are empty
     stubs — no reporting layer, and nothing about it targets this lab's
     `opensearch-stack`/`secpipe-stack`.
   Neither is the shape this repo actually uses for the same problem
   (see `wazuh_findings_ingest`/GVM's `gvm_findings_sync.py` on
   `secpipe-stack` — plain stdlib-only Python synced via a systemd
   timer, landing in OpenSearch, correlated by `cve_enrichment_sync`).
2. **Host is undocumented/unlabeled at the network level.** No MikroTik
   comment, no DHCP reservation, identified only by a DHCP-refactor-era
   forensic fingerprint. Low risk (it's LAN-only and known-location) but
   inconsistent with how every other lab host is tracked.
3. **Credentials live entirely outside OpenBao.** SSH key, web UI
   htpasswd, and both sync repos' external-ES API keys are plain local
   files with no rotation path and no central record of what exists.
   This host will never be a `PRODUCTION_NODES` entry (it's not Proxmox),
   so it doesn't need the full `with-secrets-prod` treatment — but
   "nothing about it is written down anywhere" is a real gap for a box
   whose entire job is being attacker-adjacent.
4. **No patch cadence.** 63 pending apt packages, no unattended-upgrades
   equivalent. The daily reboot/container-prune cron keeps the *honeypot
   images* fresh (they're pulled `always`), but the underlying Debian
   host OS itself isn't covered by that.
5. **No ES retention policy.** Indices accumulate indefinitely
   (`logstash-YYYY.MM.DD`, one per day, unbounded). At ~35MB/day this is
   not urgent (years before it matters on a 459G disk) but there's no
   ILM policy defining an intended retention window, so it's an
   unbounded-by-accident state, not a decided one.
6. **Stale SSH alias.** `tpot-lxc` → `192.168.1.31:64295` doesn't
   resolve to anything live — looks like leftover config from an
   abandoned plan to run this as an LXC.

## Proposed plan

### Phase 0 — done today
- [x] Enable persistent `journald` storage on the host (live fix,
  2026-09-30).
- [x] This documentation workspace.

### Phase 1 — inventory hygiene (done, 2026-09-30)
- [x] Labeled the MikroTik DHCP lease for `192.168.1.28`
  (MAC `88:A2:9E:57:E6:24`) via
  `ansible/00-initial-setup/mikrotik-dhcp-lease-label-tpot-honeypot.yml`
  — comment-only, idempotent, applied live against the router and
  verified by re-read. Closes the loop on the DHCP-refactor doc's
  unlabeled-device finding. (Full static-reservation conversion is still
  owed by the separate, not-yet-executed DHCP→Technitium cutover in
  `docs/dhcp-refactor/bridgelocal-cutover-packet.md` — out of scope
  here.)
- [x] Removed the dead `tpot-lxc` SSH alias from `~/.ssh/config`.
- [x] Cross-linked this workspace from `docs/threat-vuln-platform/plan.md`'s
  `tpot-events` row so it's no longer an orphaned "deferred" mention.

### Phase 2 — credentials custody: full OpenBao migration (operator-confirmed 2026-09-30, corrected 2026-09-30)
Corrected after checking `docs/reference/secrets-management.md` properly:
this needs neither a `hosts/tpot` entry nor a new AppRole. `kv/hosts/<node>`
is specifically for a *Proxmox* node's own API tokens (T-Pot isn't one);
this belongs with everything else whose identity comes from a service
(Harbor, Graylog, ...), i.e. `kv/services/tpot`. And `kv/services/*` is
already broadly readable by every environment's existing `deploy-<node>`
identity — so once the entry is added to the manifest, `secpipe-stack`'s
own existing `deploy-pve-tiny` credentials already cover it. No new
AppRole/policy to create.

- **Generate a new dedicated SSH keypair for the sync job** (not the
  operator's interactive `steve` login key) and install its public half
  on the T-Pot host's `authorized_keys` — this is the one step that can
  happen independent of everything else below, since it's ordinary host
  administration, not a secrets-store write.
- Rotate the three web-UI htpasswd passwords (`admin`/`steve`/
  `recoveryadmin`) on the T-Pot host at the same time, while in there.
- Add a `kv/services/tpot` entry to `secrets/manifest.json`'s `entries`
  (fields: `TPOT_SSH_PRIVATE_KEY`, `TPOT_WEB_ADMIN_PASSWORD`, etc.), and
  to `secpipe-stack`'s profile so the loader actually exports it.
- Write the new values into OpenBao via `scripts/openbao_write.py` after
  an explicit human OIDC login — this step, and the manifest edit above,
  are **operator-only**: agents never get OpenBao write access
  (this repo's own policy), and `secrets/` is outside what this session
  can read or edit regardless.
- Update `~/.ssh/config`'s `tpot` alias to the new key once rotated (the
  dead `tpot-lxc` alias was already removed in Phase 1).

**Execution note (2026-09-30):** the `tpot_findings_ingest` role (Phase 4,
below) already expects exactly this shape — `TPOT_SSH_PRIVATE_KEY` via
`secrets/manifest.json` → OpenBao, materialized to a file on
`secpipe-stack` at deploy time. It was built together with this phase
since neither is useful alone; it fails loudly (mandatory env var) until
this phase's manifest entry and OpenBao write actually exist. The
credential rotation + manifest edit + OpenBao write are still
operator-only steps, not yet done.

### Phase 3 — patch cadence: security-only unattended-upgrades (operator-confirmed 2026-09-30)
- Install the same security-only `unattended-upgrades` policy this
  repo's `unattended_upgrades` Ansible role uses fleet-wide (same
  `50unattended-upgrades` template, same apt-daily timer
  unmask/enable logic) — applied by hand over SSH since this host isn't
  in `terraform/lxc/ansible/`'s inventory, or via a small standalone
  playbook with an inline inventory entry if that's easier to keep
  idempotent across reruns.
- One-time catch-up `apt-get upgrade` for the current 63 pending
  packages first, same as was just done fleet-wide for the Proxmox-side
  Wazuh vulnerability backlog (see `project_lxc_scan_monitoring_rollout_status`
  memory) — the security-only policy alone won't retroactively close an
  existing gap.

### Phase 4 — findings ingestion: built 2026-09-30, not yet deployed (blocked on Phase 2)
A new `tpot_findings_ingest` role was built, following the same shape as
`wazuh_findings_ingest`/`gvm_findings_ingest` rather than resurrecting
either personal repo wholesale:
- `terraform/lxc/ansible/roles/tpot_findings_ingest/files/tpot_findings_sync.py`
  — stdlib-only (no `requests`/`elasticsearch` pip packages, matching
  every other sync script's own convention), deployed to `secpipe-stack`
  as a `tpot-findings-ingest.timer` systemd unit (hourly — this is a real
  incremental event stream, unlike the `*-findings` roles' daily
  current-state pulls).
- Reuses the **tunnel-based fetch logic already proven in
  `tpotce-analysis/tpot_es_sync.py`** (SSH tunnel to `:64298`, scroll
  API, incremental cursor state) — that part of the legacy script was
  correct and tested; rewritten stdlib-only rather than reinvented.
- Lands in a dedicated `tpot-events-YYYY.MM.DD` index (one index per day
  across all honeypots, `honeypot` as a field — not per-honeypot indices
  like the prototype used), matching `docs/threat-vuln-platform/plan.md`'s
  `*-events` table exactly as already written (operator-confirmed
  2026-09-30 — not folded into `unified-cve-exposure`, since T-Pot
  activity is activity-shaped, not CVE-shaped).
- Wired into `deploy-secpipe-stack.yml`, gated behind
  `tpot_findings_ingest_enabled` (default `false`) exactly like
  `cve_enrichment_sync` — inert on every existing `secpipe-stack`
  redeploy until explicitly turned on.
- **Cannot actually run yet**: `tpot_findings_ingest_ssh_private_key` is
  `mandatory()` on `TPOT_SSH_PRIVATE_KEY`, which doesn't exist until
  Phase 2's manifest entry + OpenBao write are done. Deploying now would
  fail loudly and immediately, by design, rather than silently no-op.
- Retention/ILM for the destination `tpot-events-*` indices is still not
  defined (see "Still open" below) — deliberately out of scope for this
  pass; the sync script only writes.
- Retention for the *source* `logstash-*` indices on the T-Pot host
  itself (Gap 5) is a separate, still-open decision.

### Phase 5 — visibility
- Extend the existing `Threat & Vulnerability Overview (UVM)` Grafana
  dashboard (or add a small "Honeypot Activity" panel) once Phase 4 data
  is flowing — reuses infrastructure that already exists rather than
  standing up Kibana access for the operator.
- Decide whether the AI daily-report feature from `tpotce-analysis`
  (`tpot_ai_reporter.py`) is worth porting too, or whether the Grafana
  panel supersedes it.

## Still open

- **Retention window (Gap 5)**: how long should raw T-Pot `logstash-*`
  indices be kept before ILM rolls them off? Not urgent given current
  growth rate (~35MB/day), but worth deciding once instead of leaving it
  implicit — revisit when Phase 4 is actually built.
- **AI daily-report port** (Phase 5): worth reviving, or does the
  Grafana panel make it redundant?
