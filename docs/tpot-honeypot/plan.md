# T-Pot honeypot — management plan

## Management boundary (operator-confirmed 2026-09-30)

**This repo's automation never touches `~/tpotce/` or runs its
`install.sh`/`update.sh`/`deploy.sh`/`uninstall.sh`.** T-Pot's own
Docker Compose stack (honeypots, ELK, nginx, the whole application
layer) was hand-installed from the upstream `tpotce` project and stays
exactly that way — the operator's stated concern is that it's fragile
enough that a "redeploy" risks losing hand-tuned config, and there's no
reason to take that risk: nothing this plan needs (patch cadence, SSH
access for the sync job, persistent logging) requires touching the
honeypot application at all.

Everything in this plan operates one layer down, on the **Debian 13
host underneath** — same boundary this repo already draws for the
Framework Desktop (`docs/framework-ubuntu/`): a bare-metal,
non-Proxmox host, managed by a plain Ansible inventory group
(`ansible/inventory/inventory.yml`) and standalone playbooks under
`ansible/00-initial-setup/`, entirely separate from
`terraform/lxc/ansible/`'s Proxmox-guest-only conventions. Host-layer
changes (package updates, SSH keys, journald config) can't touch or
require restarting T-Pot's own containers.

Consequence for Phase 2: **dropped** the web-UI htpasswd password
rotation from scope — it isn't needed for anything this plan actually
does (the ingestion sync job only ever needs SSH access, never the web
UI), and rotating it means editing `~/tpotce/.env` and restarting
`nginx`, which is exactly the app-layer risk this boundary exists to
avoid. The SSH access needed for the sync job is now purely **additive**
(a brand-new, dedicated keypair appended to `authorized_keys`) rather
than a rotation of the operator's own existing interactive key.

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
2. ~~**Host is undocumented/unlabeled at the network level.**~~
   **FIXED (Phase 1)**: MikroTik DHCP lease labeled, `tpot` inventory
   group added.
3. ~~**Credentials live entirely outside OpenBao.**~~ **FIXED for the
   sync job's own access (Phase 2)** — a dedicated key is now OpenBao-
   tracked. The *interactive* `steve` login key and the web-UI htpasswd
   passwords remain outside OpenBao by deliberate choice (see
   "Management boundary" — rotating them means touching `~/tpotce/`,
   which this plan avoids), not because it was missed.
4. ~~**No patch cadence.**~~ **FIXED (Phase 1.5)**: security-only
   `unattended-upgrades` installed, 63-package backlog cleared to 3.
5. **No ES retention policy.** Indices accumulate indefinitely
   (`logstash-YYYY.MM.DD`, one per day, unbounded). At ~35MB/day this is
   not urgent (years before it matters on a 459G disk) but there's no
   ILM policy defining an intended retention window, so it's an
   unbounded-by-accident state, not a decided one. **Still open.**
6. ~~**Stale SSH alias.**~~ **FIXED (Phase 1)**: `tpot-lxc` removed from
   `~/.ssh/config`.

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
- [x] Added a `tpot` group to `ansible/inventory/inventory.yml`, mirroring
  `framework`'s bare-metal, non-Proxmox pattern exactly (see "Management
  boundary" above) — this is what makes the host itself Ansible-managed
  for the first time, independent of anything else in this plan.

### Phase 1.5 — host baseline (done, 2026-09-30): `ansible/00-initial-setup/tpot-host-baseline.yml`
Codifies, as an idempotent playbook, what was previously done by hand
directly over SSH — and nothing more. Reuses the existing
`unattended_upgrades` role unmodified (via `ANSIBLE_ROLES_PATH`, same
technique `framework-desktop-bootstrap.yml` uses for `node_exporter`/
`rsyslog_forward`), so the T-Pot host now gets the same security-only
patch policy as every Proxmox-guest stack, without needing its own copy
of that role's logic:

- `unattended_upgrades` role (security-only policy, apt-daily
  unmask/enable) — same role, same template, as the rest of the fleet.
- One-time catch-up `apt-get upgrade` for the 63 packages found pending
  during the initial health check.
- Persistent `journald` storage (`/var/log/journal`) — codifies the
  manual fix already applied live 2026-09-30, so it survives an OS
  reinstall rather than existing only as an undocumented one-off change.
- A dedicated, purpose-built SSH keypair for the future ingestion sync
  job, **appended** to `authorized_keys` (not replacing the operator's
  own interactive key) — the only access change here, and purely
  additive.

None of this touches `~/tpotce/`, restarts any T-Pot container, or runs
any of T-Pot's own install/update/deploy scripts.

**Applied live and verified 2026-09-30** (dry-run via `--check --diff`
first, then a real run after explicit operator confirmation):
apt-upgradable count dropped from 63 to 3; `authorized_keys` grew from 1
to 2 lines (additive only); the new keypair's public fingerprint
confirmed (`tpot_findings_ingest@secpipe-stack`); `/var/log/journal`
confirmed present with correct ownership. All 29+ T-Pot containers
confirmed still running throughout — none were restarted, `~/tpotce/`
was never touched. (Container count read 30 post-run vs. 29 at the
initial health check; not caused by this playbook — nothing here runs
`docker` — likely T-Pot's own internal automation; not investigated
further as it's outside this plan's scope.)

### Phase 2 — sync-job credentials: additive SSH key + OpenBao entry (done, 2026-09-30)
Corrected twice before execution: first after checking
`docs/reference/secrets-management.md` properly (this needs neither a
`hosts/tpot` entry nor a new AppRole — `kv/hosts/<node>` is specifically
for a *Proxmox* node's own API tokens; this belongs with everything else
whose identity comes from a service, i.e. `kv/services/tpot`, and
`kv/services/*` is already broadly readable by every environment's
existing `deploy-<node>` identity, so `secpipe-stack`'s own
`deploy-pve-tiny` credentials already cover it, no new AppRole to
create). Second, after the "Management boundary" decision above:
**web-UI password rotation dropped from scope entirely** — the sync job
never uses the web UI, so rotating those passwords would be app-layer
risk for no benefit.

- [x] Dedicated SSH keypair generated and its public half appended to
  `authorized_keys` (Phase 1.5) — purely additive, the operator's own
  interactive key untouched.
- [x] `kv/services/tpot` entry added to `secrets/manifest.json`'s
  `entries` (field: `TPOT_SSH_PRIVATE_KEY`) and to `secpipe-stack`'s
  profile — operator-run, since `secrets/` is outside this session's
  read/edit permissions.
- [x] Private key value written into OpenBao via
  `scripts/openbao_write.py` after explicit human OIDC login —
  operator-run. **Base64-encoded before writing** (not raw PEM text):
  `openbao_write.py` reads exactly one line per field when stdin isn't a
  TTY, so a real multi-line private key piped straight in would silently
  truncate to just its first line — found while drafting the runbook,
  fixed before it was ever run. The role `b64decode`s it back out before
  it touches disk.

### Phase 4 — findings ingestion: deployed live 2026-09-30, two real bugs found and fixed, one MikroTik fix pending operator run
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
  `tpot_findings_ingest_enabled` — same pattern as `cve_enrichment_sync`.
  Flipped to `true` in `terraform/lxc/stacks/secpipe-stack/stack.yaml`
  once Phase 2 was done.

**Real bug #1, found and fixed live**: the first deploy attempt showed
*every* `tpot_findings_ingest` task as `skipping`, even with the flag set
`true`. Root cause: `scripts/provision.sh`'s `render_stack_ansible_extra_vars()`
only forwards an explicit, hardcoded allowlist of keys from each stack's
`stack.yaml` into Ansible extra-vars — `tpot_findings_ingest_enabled`
wasn't in it (sibling flags like `wazuh_findings_ingest_enabled` were).
Fixed by adding a `TPOT_FINDINGS_INGEST_KEYS` entry to that allowlist,
identical in shape to its siblings. Re-run after the fix: role installed
cleanly, 0 failed.

**Real bug #2, found and fixed live**: the first manual trigger of
`tpot-findings-ingest.service` failed with `Connection timed out`
opening the SSH tunnel from `secpipe-stack` (`192.168.50.12`, `ai_seg`)
to T-Pot (`192.168.1.28`, flat client LAN, port 64295). Confirmed by
reading the live MikroTik ruleset directly: `ai_seg` had rules to/from
several VLAN zones and a narrow internet allowlist, but **nothing at all
reaching the flat LAN** — the same class of gap as the Wazuh
port-55000 issue found earlier in this same overall rollout
(`docs/lxc-scan-and-monitoring-rollout/`), not a flaw in the new role.
Fix written: `ansible/00-initial-setup/mikrotik-firewall-secpipe-to-tpot.yml`,
one narrowly-scoped forward-chain rule (secpipe-stack's own IP → T-Pot's
own IP, port 64295 only). First apply attempt hit a second, smaller bug —
used `PUT` on MikroTik's `/ip/firewall/filter/add` REST endpoint, which
needs `POST` (`PUT` targets an existing resource by ID, which `/add`
doesn't have) — fixed to match every other `mikrotik-firewall-*.yml`
playbook in this repo. **Blocked from self-apply** by the
"Protected-Scope IaC Apply" classifier (same as every other MikroTik
change this session) — operator ran the corrected playbook; rule
confirmed present and correctly ordered (immediately before `ai_seg`'s
deny-all anchor).

**Real, unresolved problem #3 — SYN-ACK never returns, cause not yet
found.** After the MikroTik fix, the tunnel still times out. Full
diagnostic trail (2026-09-30):
- MikroTik's own connection tracking confirms the SYN leaves the router
  toward T-Pot (`tcp-state: syn-sent`) but `seen-reply: false` — no reply
  packet is ever recorded arriving back.
- T-Pot's own host firewall is not the cause: `iptables`/`nftables`
  explicitly `ACCEPT` tcp/64295 from any source, `sshd` listens on
  `0.0.0.0:64295`, no `ipset`/`fail2ban` ban exists for
  `192.168.50.12`, and Suricata runs in passive `af-packet` capture mode
  (not inline/NFQUEUE), so it isn't dropping anything either.
- **Conclusive finding**: `/proc/net/tcp` on the T-Pot host, read during
  a live connection attempt, shows a real entry for
  `192.168.1.28:64295` ↔ `192.168.50.12:<ephemeral>` in `SYN_RECV`
  state (code `03`) — T-Pot's kernel genuinely received the SYN and
  answered with its own SYN-ACK. The honeypot side is doing everything
  right.
- A general `connection-state: established,related` accept rule already
  sits early in MikroTik's forward chain (`*69`, no src/dst restriction)
  and should cover the reply regardless of the new rule's position, so
  this isn't a second ordering problem.
- Conclusion: the SYN-ACK is being lost somewhere in the router's own
  L2/hardware-switching path between the `vlan50-ai` and `bridgeLocal`
  interfaces — something the REST API's `/ip/firewall` and `/ip/route`
  views can't surface (e.g. bridge hardware offloading, switch-chip VLAN
  table). **This needs direct RouterOS console access** (`/interface
  bridge host print`, `/interface ethernet switch` settings) to diagnose
  further — beyond what this session's REST-API-only access can reach.

- Retention/ILM for the destination `tpot-events-*` indices is still not
  defined (see "Still open" below) — deliberately out of scope for this
  pass; the sync script only writes.
- Retention for the *source* `logstash-*` indices on the T-Pot host
  itself (Gap 5) is a separate, still-open decision.
- **Not yet confirmed**: a real end-to-end run (tunnel connects, events
  actually land in `tpot-events-*`) — blocked on problem #3 above.

### Phase 5 — visibility
- Extend the existing `Threat & Vulnerability Overview (UVM)` Grafana
  dashboard (or add a small "Honeypot Activity" panel) once Phase 4 data
  is flowing — reuses infrastructure that already exists rather than
  standing up Kibana access for the operator.
- Decide whether the AI daily-report feature from `tpotce-analysis`
  (`tpot_ai_reporter.py`) is worth porting too, or whether the Grafana
  panel supersedes it.

## Still open

- **Immediate blocker (Real problem #3, above)**: the MikroTik firewall
  fix is applied and confirmed correct, but the SSH tunnel still times
  out — a SYN-ACK from T-Pot never makes it back through the router to
  `ai_seg`, despite T-Pot's own kernel confirmed answering correctly
  (`SYN_RECV` seen live in `/proc/net/tcp`). This needs direct RouterOS
  console access to diagnose (bridge hardware offloading / switch-chip
  VLAN table between `vlan50-ai` and `bridgeLocal`) — beyond what this
  session's REST-API-only MikroTik access can reach. Once resolved, a
  manual trigger of `tpot-findings-ingest.service` on `secpipe-stack`
  gets verified end-to-end (real events actually landing in
  `tpot-events-*` on `opensearch-stack`, not just a clean tunnel).
- **Retention window (Gap 5)**: how long should raw T-Pot `logstash-*`
  indices be kept before ILM rolls them off? Not urgent given current
  growth rate (~35MB/day), but worth deciding once instead of leaving it
  implicit.
- **Destination retention**: same open question for the new
  `tpot-events-*` indices this phase creates — no ILM policy defined yet.
- **AI daily-report port** (Phase 5): worth reviving, or does the
  Grafana panel make it redundant?
- **Phase 5 (visibility)**: not started — Grafana dashboard panel work
  comes after the ingestion pipeline is confirmed flowing end-to-end.
