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

## Decisions (operator, 2026-10-24)

| Question | Decision |
|---|---|
| Routine channel | **Discord**, four channels: `#alerts-critical` (a copy of every Telegram page), `#alerts-warning`, `#security` (Wazuh, GVM, Graylog, Harbor findings), `#events` (Proxmox, PBS, Harbor, informational) |
| Emergency channel | **Telegram**, private chat with a bot. **Two-way: Ack and Snooze buttons.** Do Not Disturb is respected (no bypass); repeat-until-ack is the safety net instead |
| Ack / snooze | Every repeating alert has both. Ack = quiet until it resolves. Snooze (1h / 4h / 24h) = quiet for N, then comes back if still firing. Applies to the dead man's switch too |
| Dead man's switch | Lives on the OCI box (`~/git/oci`), outside the lab. Healthchecks.io watches the OCI box |
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
                        Healthchecks.io watches the relay
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
3. **Healthchecks.io account** (Phase 4) and **Telegram bot via @BotFather**
   (Phase 3).
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
