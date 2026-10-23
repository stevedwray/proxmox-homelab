# alerting

Status: **planned 2026-10-24; Phase 0 groundwork partly live, nothing else
started.** Supersedes `docs/catch-up/07-baseline-alerting.md` (Discord-only).
Steps: [plan.md](plan.md). This file holds the decisions, the design rules and
the hand-back log.

## Why

Nothing in the lab tells the operator when something breaks. Verified
2026-10-24:

- pve-tiny's NVMe has been failing since at least 2026-10-16 (media errors
  308, then 974; 47 kernel errors in one day on 10-23). The errors were in
  Graylog and in VictoriaMetrics the whole time. A nightly PBS backup failed
  every night. Nobody was told.
- Seven stacks' node_exporter has been dead since 2026-10-21 (portainer since
  10-23): the cert-renewal timer sends SIGHUP and node_exporter exits. The
  fix is on stable (`scripts/node-exporter-renew-fix.sh`) but was never run.
- Grafana has no contact point, no alert rule, no Alertmanager.

The goal is the things that **fail silently or semi-silently**: hardware
faults, temperatures, new critical vulnerabilities, backups, and the monitoring
itself going quiet.

## Scope: now, and future state

**Now (operator decision 2026-10-24: step back and keep it simple):**

- Everything that matters goes to **Discord**, in four channels.
- The few alerts that need a human **now** also go to **Telegram**, through Grafana's
  own Telegram contact point: no custom service. The "page set" is: critical hardware
  faults, OpenBao sealed or snapshot problems, a production node unreachable, a local
  disk above 95%, and the **honeypot tripwire**.
- Silencing is done in Grafana (Alerting, Silences), which is time-boxed and works as a
  snooze. Telegram has no buttons.

**Future state, deliberately deferred** (all designed, none deployed):

- The OCI alert relay with Ack and Snooze buttons (built and tested, parked in
  `~/git/oci`, not deployed; whether to keep it or use off-the-shelf software is
  undecided).
- A dead man's switch on the OCI box, reached over mutual TLS on a dedicated port
  (not 443), firewalled to the home IP.
- blackbox_exporter service checks of the alert chain, then Icinga.

## Decisions (operator, 2026-10-24)

| Question | Decision |
|---|---|
| Routine channel | **Discord**, four channels: `#alerts-critical` (a copy of every Telegram page), `#alerts-warning`, `#security` (Wazuh, GVM, Graylog, Harbor findings), `#events` (Proxmox, PBS, Harbor, informational) |
| Emergency channel | **Telegram**, a private chat with the bot, through **Grafana's built-in Telegram contact point**. No Ack/Snooze buttons for now (that is the deferred relay); snooze with a Grafana silence. Do Not Disturb is respected (no bypass) |
| Ack / snooze | Now: a time-boxed Grafana silence. Future: Ack and Snooze buttons in Telegram via the relay, which also covers the dead man's switch |
| Service checks | **blackbox_exporter**, Nagios-style active checks, limited to the services the alert and notification chain depends on (7 probes, see plan Phase 4b). Not a general service monitor; additions only on the operator's request. **Icinga later**, if dependencies and escalations prove necessary |
| Paging (Telegram) | Critical hardware faults (NVMe media errors rising, NVMe critical warning, spare low, SMART health failed, SATA pending or uncorrectable sectors, NVMe 80 C, SATA 65 C, CPU 95 C); OpenBao sealed, snapshot stale or failed; a production node (`pve`, `pve-tiny`) unreachable; a local disk above 95%; the honeypot tripwire. Everything else is Discord only |
| Honeypot tripwire | Telegram **and** Discord `#security` when any host not on the allowlist opens a connection to a T-Pot service port. Greenbone (`192.168.70.11`) and the known hosts are the allowlist. Read from Suricata flow records, because the honeypot sensors lose the real source address (see below) |
| Hosting | **Self-hosted only, no SaaS** (Healthchecks.io is dropped). Nothing new runs on `framework`: its memory and load must stay low |
| Dead man's switch | **Future state.** A small service on the OCI box receiving per-node heartbeats; the lab watches it in return. Until then nothing watches Grafana, VictoriaMetrics, Graylog or the monitoring host |
| Routing | Proxmox and Harbor send to Discord directly. Anything that can be critical goes through Grafana or Graylog, then the OCI relay. Services with their own Discord/Telegram support are evaluated case by case (list below) |
| Log alerts | Come from **Graylog**, on exact message patterns, never on log level |
| Hardware | Faults, temperatures and firmware-update-available are in scope for every device, including workstation, MikroTik, Omada switches, NAS and Pis |
| Workstation logs | Warning and above only |
| Email | Not an alert channel. Weekly digest only, Monday 07:00 `Pacific/Auckland`, undecided until Phase 6 |
| Fire drill | Monthly, documented (Phase 6) |
| `pentest_seg` | GVM scans it **only on request for a pentest**, as a dedicated GVM user, and those results stay **out of lab findings and alerts**. Its logs live in their own Graylog stream. Not yet implemented for the scan program (see `docs/gvm-scan-redesign/README.md`) |
| T-Pot Pi | **No relabel.** Its source name is already the generic `raspberrypi` (deliberate; the DHCP notes call it an unlabeled fingerprint) and its own logs contain no "tpot" |
| Workstation forwarder | A small systemd service following the journal (`journal_to_graylog.py`), because Garuda's repos only offer `rsyslog` from chaotic-aur and its journal input module can't be verified. **Default chosen by the planner; the operator may switch it to chaotic-aur rsyslog** |
| UPS | None, so no power alerts yet |

## Design rules (each learned from real data)

1. **Alert on exact text, never on log level.** Docker sends container stderr
   as level 3. Authentik alone produced 1.28M "errors" in a week.
2. **Hardware rules must select `job="node_exporter_hw"`.** Every LXC's
   node_exporter also exposes the *host's* NVMe sensors, so 17 targets repeat
   the same drives. An unfiltered rule would page 17 times for one disk.
3. **Alert on error *increase*, not on the overall health flag.** The failing
   pve-tiny drive showed `smartmon_device_smart_healthy = 1`, but only because
   `smartctl` cannot read that drive at all (`smartmon_device_smart_available
   = 0`), so the flag was a default, not a verdict. The NVMe collector did read
   it, and its `nvme_media_errors_total` was climbing. Use
   `increase(nvme_media_errors_total[1h]) > 0`, and watch for SMART becoming
   unreadable.
4. **Exclude what is off or isolated on purpose.** `pve-test` (laptop, off
   while the heatsinks are reseated), the Foreverworld exporters, and
   everything from `pentest_seg`.
5. **Ack is not resolve; snooze re-arms.** A snoozed alert that is still
   firing when the timer ends must come back.
6. **Keep the critical list short** (fewer than one a week), or it gets
   ignored. Start list: dead man's switch; OpenBao sealed or snapshot
   failed/stale; a production node down (`pve`, `pve-tiny`, `framework`);
   local disk at 95%; hardware faults (NVMe media errors rising, NVMe critical
   warning, spare below threshold, SMART unhealthy, NVMe 80 C, CPU 95 C,
   kernel hardware-error log patterns).
7. **Sender identity comes from `relay_src_ip`, not `source`.** `source` is
   whatever hostname the sender claims.

## Architecture

```
Grafana (metrics, vulns) ──┐
Graylog (log patterns) ────┼──► alert relay (OCI box) ──► Discord channels
Lab heartbeats ────────────┘      state: ack / snooze      Telegram bot (buttons)
                                       │
Proxmox, PBS, Harbor ─────────────────►│──────────────────► Discord #events (direct)
                                       ▼
                        the lab watches the relay (VictoriaMetrics scrapes it;
                        Grafana alerts if it is down)
```

Relay contract (Phase 3 writes the steps; this is the agreed shape):

- `POST /v1/alerts`: Grafana webhook and Graylog HTTP notification, bearer
  token. Alerts are keyed by fingerprint, so repeats update one record.
- `POST /v1/heartbeat/<name>`: lab watchdog. A missing heartbeat becomes a
  synthetic critical "lab silent" alert.
- Telegram long polling (no inbound port). Only the operator's chat id is
  accepted. Buttons: Ack, Snooze 1h/4h/24h. Commands: `/status`, `/snoozed`.
- State in SQLite: status, first seen, last sent, ack/snooze until, count.
- Critical re-sends every 30 min until acked or resolved; warning every 4 h.
- Secrets live in the OCI repo's untracked, mode-0600 `.env` (the pangolin
  role's existing pattern), not OpenBao. The lab side gets only the ingest
  token, via OpenBao.

Watching the watchers (no SaaS):

- `pve` and `pve-tiny` each run a systemd timer every 5 minutes. It checks
  Grafana (`/api/health`), VictoriaMetrics (`/health`) and Graylog
  (`/api/system/lbstatus`), then POSTs a heartbeat named after the node to the
  relay, including the per-component results. A failed component alerts at
  once; silence for about 12 minutes alerts as "node silent". Because the
  heartbeat is per node, this also detects a production node dying without
  Grafana's help. The pinger is deliberately not on `framework`.
- The relay serves `/metrics`; VictoriaMetrics scrapes it, so the ordinary
  target-down rule tells Discord if the OCI service stops.
- **Residual risk, accepted by the no-SaaS decision:** if the lab and the OCI
  box both fail at the same moment, or both Telegram and Discord are
  unreachable, nothing notices.

## Honeypot findings (2026-10-24)

- T-Pot is a **LAN tripwire**, not internet-facing. Over 30 days the only
  non-allowlisted source touching its service ports was your Kali test host on
  2026-10-15 (81 flows). In the last 7 days: none.
- **The honeypot sensors lose the real source address.** Cowrie, Dionaea and
  Honeytrap record Docker-internal addresses (`192.168.112.1`, `172.29.0.1`,
  `172.24.0.2`) for LAN-originated connections, so every Greenbone sweep looks
  like a stranger in those events. **Suricata sees the wire and records the real
  source**, so the alert reads Suricata `flow` records instead.
- A flow only counts as inbound when it has a service destination port
  (`<= 32767`) and an ephemeral source port (`>= 1024`). The opposite shape
  (source port 443 or 53) is the Pi's own outbound traffic, seen mid-stream,
  and caused most of the apparent noise.
- The existing dashboard panels "Sensor events from UNEXPECTED sources" and
  "Distinct unexpected sources" are therefore misleading (they count Docker
  addresses). Worth rebuilding on the Suricata-flow query; not done yet.
- Latency: the central OpenSearch copy is synced by a timer; it was hourly and is
  now every 10 minutes (worst case about 12 minutes from a probe to a page).

## What exists today (verified 2026-10-24)

| Piece | State |
|---|---|
| Graylog relay stamps `relay_src_ip`; "Pentest Segment" stream | **Live** (branch `work/graylog-sender-ip-pentest-stream`, commit `e8b0b4ef`, not PR'd) |
| MikroTik pentest_seg rules narrowed (514 to Graylog only, 443 to step-ca only) | **Live** |
| NVMe/SMART metrics (`nvme_*`, `smartmon_*`) for pve, pve-tiny, argon-01/02 | Live, scraped |
| Temperature metrics (`node_hwmon_temp_celsius`) | Live. NVMe composite on pve reads 67.85 C, CPU Tctl 69 C |
| Omada metrics (`omada_device_need_upgrade` etc.) | Exporter works; **no `omada_*` in VictoriaMetrics**: monitoring-stack was redeployed without the scrape job (it is on stable) |
| MikroTik health | Only `cpu-temperature` exists; RouterOS 7.24.2 (7.24.5 out), RouterBOARD firmware 7.19.6 (7.24.2 pending). No exporter yet |
| NAS (Asustor Drivestor) | Sends 45 messages a month, only System/Connection categories. Hardware events unknown |
| Workstation `garuda`, argon-01/02 | **Not in Graylog** |
| `pve-test` laptop | Off on purpose |

## Open items for the operator

1. **Framework `llamacpp :8080` scrape is down.** Intentional (model idle) or
   a fault? If intentional it needs excluding from the target-down rule.
2. **NAS (Asustor Drivestor):** which log categories ADM sends to syslog, and
   whether SNMP is available. Needed before Phase 0 can close the NAS.
3. **Telegram bot:** created. Run `scripts/telegram_setup.py` to connect it
   (see [telegram-setup.md](telegram-setup.md)). The OCI box is sized for the
   relay: aarch64, 8 GB RAM (about 6.9 GB free), 2 CPUs, load 0.03.
4. **Two disks have no SMART health data at all:** pve `sdg` (an NVMe behind
   a USB bridge; `smartctl` cannot read it) and pve-tiny's NVMe via the generic
   collector (covered instead by the NVMe collector). `sdg` is a blind spot
   until a newer `smartmontools` or a different `-d` type reads it.
5. Whether pve nvme composite readings of 67-70 C are acceptable. The
   warning threshold is 70 C, so they sit right at the line.

## Native integrations to evaluate case by case (Phase 6)

PBS and Proxmox notification targets (Discord webhook, severity-routed),
Harbor webhooks, Authentik notification transports, Omada controller alerts,
Wazuh (only if Graylog doesn't already cover it), T-Pot, Nextcloud. GVM can
only send email, so its findings go through OpenSearch and Grafana instead.

## Hand-backs

(One entry per completed step, newest last. The local model appends here;
the planner verifies and fills gaps.)

- 2026-10-24: Phase 0 groundwork (sender IP stamping, Pentest Segment stream,
  MikroTik narrowing) built and verified live by the planner. See commit
  `e8b0b4ef`.
