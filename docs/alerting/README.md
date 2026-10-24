# alerting

Status as of **2026-10-24**: the alerting is **built, tested and committed, but not deployed.**
Only the Phase 0 groundwork (Graylog sender-IP stamping, the pentest stream, two MikroTik rules)
and the Discord channels and webhooks are live. The next move is the operator checklist in
[plan.md](plan.md) under *Phase 1c*. This file is the current-state summary: what it does, what
was decided, what was found, where things live. The plan holds the steps and its own status table.

Supersedes `docs/catch-up/07-baseline-alerting.md` (Discord only).

## Why

Nothing in the lab told the operator when something broke. Verified 2026-10-24:

- **pve-tiny's NVMe is failing** (media errors 308, then 974; 47 kernel errors in one day on 10-23).
  The errors were in Graylog and in VictoriaMetrics the whole time, and a nightly PBS backup failed
  every night. Nobody was told. (An RMA is in progress.)
- **Seven stacks have had no host metrics** since 2026-10-21 (portainer since 10-23): the cert-renewal
  timer sends SIGHUP and node_exporter exits. The fix, `scripts/node-exporter-renew-fix.sh`, is on
  `stable` and was never run.
- **Live Grafana has only the default email receiver:** no contact point, no alert rule.

The target is what **fails silently or semi-silently**: hardware faults, temperatures, new
critical vulnerabilities, backups, and the monitoring going quiet.

## Scope: now, and future state

**Now (operator decision 2026-10-24: step back and keep it simple):**

- Everything that matters goes to **Discord**, in four channels.
- The few alerts that need a human **now** also go to **Telegram**, through **Grafana's own Telegram
  contact point**. No custom service.
- Silencing is a time-boxed **Grafana silence** (Alerting, Silences). Telegram has no buttons.

**Future state, deliberately deferred** (designed; none deployed):

- The **OCI alert relay** with Ack and Snooze buttons. Built and tested (39 tests), parked in
  `~/git/oci`. Whether to keep it or use off-the-shelf software (Uptime Kuma for the heartbeat) is undecided.
- A **dead man's switch** on the OCI box, reached over **mutual TLS on a dedicated port** (not 443),
  firewalled to the home IP.
- **blackbox_exporter** checks of the alert chain, then Icinga.

Until the dead man's switch exists, **nothing watches Grafana, VictoriaMetrics, Graylog or the
monitoring host themselves.**

## What pages Telegram, and what does not

A rule pages when it carries the label `page: "true"` (or `tripwire: honeypot`). Nothing else does.

| Goes to | Alerts |
|---|---|
| **Telegram + Discord `#alerts-critical`** | the 8 critical hardware rules (NVMe media errors rising, NVMe critical warning, spare capacity low, SMART health failed, SATA pending or uncorrectable sectors, NVMe 80 C, SATA 65 C, CPU 95 C); OpenBao sealed, snapshot stale, snapshot failed; a production node (`pve`, `pve-tiny`) unreachable; a local disk above 95% |
| **Telegram + Discord `#security`** | the **honeypot tripwire** |
| Discord `#alerts-critical` only | other critical alerts, e.g. any scrape target down |
| Discord `#alerts-warning` | warnings: disk 85%, NAS 90%, error counters rising, CRC errors, wear, SMART unreadable or stale, temperatures |
| also Discord `#security` | anything labelled `category: security` |

Pages repeat every 30 minutes until resolved or silenced; the tripwire once per 12 hours.
`#events` is for Proxmox, PBS and Harbor, which send there directly (not built yet).

## Decisions (operator, 2026-10-24)

| Question | Decision |
|---|---|
| Routine channel | **Discord**: `#alerts-critical` (a copy of every page), `#alerts-warning`, `#security`, `#events` |
| Emergency channel | **Telegram**, a private chat with the bot, via Grafana's built-in contact point. Do Not Disturb is respected (no bypass) |
| Ack / snooze | Now: a Grafana silence. Future: buttons in Telegram via the relay |
| Hosting | **Self-hosted only, no SaaS** (Healthchecks.io dropped). Nothing new on `framework`: its memory and load must stay low |
| Wariness of bespoke code | The operator is wary of a custom service on a critical path. Prefer maintained software; the relay is a last resort and outside the safety path |
| Service checks | blackbox_exporter, limited to the services the alert chain depends on (7 probes, plan Phase 4b); additions only when the operator asks. Icinga later |
| Log alerts | From **Graylog**, on exact message patterns, never on log level |
| Hardware | Faults, temperatures and firmware-update-available for every device, including workstation, MikroTik, Omada switches, NAS and Pis |
| Workstation logs | Warning and above only |
| Email | Not an alert channel; at most a weekly digest, Monday 07:00 `Pacific/Auckland` (Phase 6, undecided) |
| `pentest_seg` | GVM scans it **only on request for a pentest**, as a dedicated GVM user, results kept **out of lab findings and alerts**; its logs have their own Graylog stream. Not yet implemented for the scan program (`docs/gvm-scan-redesign/README.md`) |
| T-Pot Pi | **No relabel**: its source name is already the generic `raspberrypi` (deliberate) and its own logs never say "tpot" |
| Workstation forwarder | A small systemd service following the journal (chaotic-aur's `rsyslog` could not be verified). Planner default; the operator may switch to rsyslog |
| UPS | None, so no power alerts |

## Design rules (each learned from real data)

1. **Alert on exact text, never on log level.** Docker sends container stderr as level 3; Authentik alone produced 1.28M "errors" in a week.
2. **Hardware rules must select `job="node_exporter_hw"`.** Every LXC's node_exporter also exposes the *host's* NVMe sensors, so 17 targets repeat the same drives; an unfiltered rule pages 17 times for one disk.
3. **Alert on error *increase*, not the overall health flag.** pve-tiny's failing drive showed `smartmon_device_smart_healthy = 1` only because `smartctl` cannot read it at all (`smartmon_device_smart_available = 0`): the flag was a default, not a verdict. The NVMe collector read it, and `nvme_media_errors_total` was climbing.
4. **Exclude what is off or isolated on purpose:** `pve-test` (laptop, heatsinks being reseated), `garuda` (the workstation), the Foreverworld exporters, everything from `pentest_seg`.
5. **Keep the page list short** (fewer than one a week) or it gets ignored.
6. **Sender identity is `relay_src_ip`, not `source`.** `source` is whatever hostname the sender claims. (Live in Graylog.)
7. **Make "no data" mean something on purpose.** `openbao_sealed` treats no data as firing, so its metric must exist before the rule is deployed.
8. **Validate generated config structurally.** Literal blocks in a step are 2 spaces deeper than in the file, and `syntax-check` cannot see inside `content: |` strings. `scripts/check_grafana_provisioning.py` parses the inline Grafana files and walks every rule through the routing.

## How it works now

```text
metrics ──► VictoriaMetrics ──► Grafana rules ──┐
T-Pot ES ──► (10-min sync) ──► OpenSearch ──► Grafana tripwire rule ──┤
                                                                      ▼
                                          Grafana notification policy (tripwire / security / page / critical / default)
                                                   │                                  │
                                       Discord (4 channels)              Telegram (pages + tripwire only)

Logs ──► Graylog (relay stamps relay_src_ip; pentest_seg has its own stream)   [Graylog log alerts: Phase 2]
```

## The honeypot tripwire

- T-Pot is a **LAN tripwire**, not internet-facing. Over 30 days the only non-allowlisted source to touch
  its service ports was the Kali test host on 2026-10-15 (81 flows). In the last 7 days: none.
- **The honeypot sensors lose the real source address.** Cowrie, Dionaea and Honeytrap record
  Docker-internal addresses (`192.168.112.1`, `172.29.0.1`, `172.24.0.2`) for LAN connections, so every
  Greenbone sweep looks like a stranger there. **Suricata sees the wire**, so the rule reads Suricata `flow`
  records into the Pi.
- A flow counts as inbound only when it has a service destination port (`<= 32767`) and an ephemeral source
  port (`>= 1024`). The opposite shape (source port 443 or 53) is the Pi's own outbound traffic seen
  mid-stream, which caused most of the apparent noise.
- The allowlist is the dashboard's "expected sources" and includes Greenbone (`192.168.70.11`).
- Verified through Grafana's own evaluator on live data: silent over the last 2 hours; fires for `192.168.1.114`
  over 30 days.
- The dashboard's "Sensor events from UNEXPECTED sources" and "Distinct unexpected sources" panels are
  misleading for the same reason (they count Docker addresses). Not yet rebuilt.
- Latency: the OpenSearch copy was synced hourly; it is now every 10 minutes (worst case about 12 minutes
  from a probe to a page).

## What exists today (verified 2026-10-24)

| Piece | State |
|---|---|
| Graylog stamps `relay_src_ip`; "Pentest Segment" stream (14-day index) | **Live** (commit `e8b0b4ef`) |
| MikroTik: pentest_seg may reach only Graylog (514) and step-ca (443) | **Live** |
| Discord server, four channels, four webhooks, OpenBao `services/grafana` v2, manifest | **Live**; bot token still to be reset in the Developer Portal |
| Telegram bot | Created and connected; credentials are in `~/git/oci/.env`, **not yet in OpenBao** |
| Grafana: `T-Pot Events` OpenSearch datasource and plugin | **Live** |
| Grafana alerting (27 rules, 5 contact points, policy) | **In the repo, not deployed** |
| OpenBao | Unsealed; nightly snapshot succeeds at 03:30; **no seal metric yet** (built, not deployed) |
| NVMe/SMART metrics for pve, pve-tiny, argon-01/02 | Live. `smartctl` cannot read pve `sdg` (NVMe in a USB bridge) or pve-tiny's NVMe |
| Temperatures | Live; pve NVMe composites read about 67 C against a 70 C warning |
| node_exporter on authentik, step-ca, harbor, apt-cacher, netbox, ci-runner, portainer | **Dead** (SIGHUP bug); repair script never run |
| Omada metrics in VictoriaMetrics | **Missing**: the running monitoring-stack lacks the scrape job that is on `stable` |
| MikroTik hardware | Only `cpu-temperature`; RouterOS 7.24.2 (7.24.5 out), RouterBOARD firmware 7.19.6 (7.24.2 pending); no exporter yet |
| NAS (Asustor Drivestor) | 45 log messages a month, System and Connection only; hardware events unknown |
| Workstation `garuda`, argon-01/02 | **Not in Graylog** (steps written, not executed) |
| `pve-test` laptop | Off on purpose |
| OCI box | aarch64, 8 GB RAM (about 6.9 GB free), 2 CPUs, load 0.03; Pangolin, Traefik and Gerbil use under 700 MB |

## Where things live

| What | Where |
|---|---|
| Alert rules | `terraform/lxc/stacks/monitoring-stack/alerting/homelab-{baseline,hardware,honeypot}.yml` |
| Wiring (datasource, copy, contact points, policy, Telegram vars, restart) | `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` |
| Routing and config check | `scripts/check_grafana_provisioning.py` |
| Discord setup | `scripts/discord_bootstrap.py` (17 tests), [discord-setup.md](discord-setup.md) |
| Telegram setup | `scripts/telegram_setup.py` (12 tests), [telegram-setup.md](telegram-setup.md) |
| OpenBao seal metric | `terraform/lxc/ansible/files/openbao/openbao_health.py` (5 tests) + `deploy-openbao.yml` |
| T-Pot sync cadence | `terraform/lxc/ansible/roles/tpot_findings_ingest/` (defaults, timer) |
| Graylog sender IP and pentest stream | `roles/rsyslog_forward/templates/graylog_inbound.conf.j2`, `playbooks/configure-graylog-pentest-seg.yml` |
| MikroTik narrowing | `ansible/00-initial-setup/mikrotik-firewall-pentest-seg-narrow.yml`, `terraform/lxc/network/pve.yaml` |
| Workstation and Pi enrolment (written, not run) | plan steps `alerting-00` to `02` |
| **Parked relay** | `~/git/oci/roles/alert_relay/` (not in any git repo I can see: the Pangolin source was copied into this repo's `oci/` on `task/oci-security-prs-integration`, unmerged, and `~/git/oci` stays the operational source until that cutover; when the import merges, carry `roles/alert_relay/` into `oci/roles/`). `site.yml` has the role commented out. Superseded runbook: [relay-deploy.md](relay-deploy.md) |

## Open items for the operator

1. **Run the Phase 1c checklist** ([plan.md](plan.md)): fleet repair, OpenBao metric, Telegram credentials into OpenBao, deploys, drills.
2. **Reset the Discord bot token** in the Developer Portal.
3. **Framework `llamacpp :8080` scrape is down.** Intentional (model idle) or a fault? If intentional, exclude it.
4. **NAS (Asustor Drivestor):** which log categories ADM sends to syslog, and whether SNMP is available.
5. **Silence the NVMe media-errors alert for pve-tiny** until the RMA drive is in.
6. **Commit the `oci` working tree changes** (the parked relay, `.env.template`); my sandbox cannot.
7. **Decide the future state:** keep the relay, or Grafana plus Uptime Kuma (A keep the relay with a backstop, B off the shelf only, C B now and buttons later). Also the dedicated port (9443 proposed) and who terminates mTLS.
8. **Unverified until deployed:** Grafana 13's Telegram provisioning keys (`bottoken`, `chatid`, `parse_mode`), and whether the dotted label `src_ip.keyword` survives the notification stage.

## Future-state design notes (parked)

- **Relay contract:** `POST /v1/alerts`, `POST /v1/heartbeat/<name>`, `/healthz`, `/metrics`; Telegram long polling,
  Ack and Snooze 1h/4h/24h buttons, `/status`, `/snoozed`; SQLite state; only the operator's chat id is obeyed.
  Ack is quiet-until-resolved; snooze re-arms when it ends. Built and tested; see the plan's Phase 3.
- **Dead man's switch:** `pve` and `pve-tiny` (never `framework`) push a heartbeat with component health every
  5 minutes; silence for about 12 minutes pages "node silent"; the lab scrapes the relay in return. Accepted
  residual risk: the lab and the OCI box failing together, or Telegram and Discord both unreachable.
- **Reaching the OCI box:** the operator ruled out port 443 (Nextcloud and Pangolin use it from their phone).
  Wanted: a **dedicated port** (9443 proposed), allowed only from the home IP `121.99.143.217` at the **OCI
  network rule** (Docker-published ports bypass `ufw`), with **mutual TLS** (client certificates from step-ca),
  TLS terminated by the relay itself or a small proxy. Open: Grafana's webhook client-certificate support,
  step-ca certificate lifetimes (default 24h), and getting the server certificate to the OCI box.
- **DNS:** the MikroTik has static entries sending `pangolin` and `oci.gibbsgreatly.xyz` straight to the OCI IP
  (`192.9.191.163`), bypassing Cloudflare; Technitium returns NXDOMAIN for names it lacks. Callers use the MikroTik.

## Native integrations to evaluate case by case (Phase 6)

PBS and Proxmox notification targets (Discord webhook, severity-routed), Harbor webhooks, Authentik notification
transports, Omada controller alerts, Wazuh (only if Graylog does not already cover it), T-Pot, Nextcloud. GVM can
only send email, so its findings go through OpenSearch and Grafana instead.

## History

All 2026-10-24, on branch `work/graylog-sender-ip-pentest-stream` (not pushed; it is based on the unrelated,
unmerged commit `2fd7175d`, so see the plan's status note before opening a PR):

- `e8b0b4ef` Graylog sender IP, `pentest_seg` stream, MikroTik narrowing (the only live change; operator ran it, verified).
- `b52209b3`..`5c60e214` Discord bootstrap script, runbook and fixes; the operator ran it (channels and webhooks live).
- `dff30d4c` Discord fields in the manifest.
- `927f6d28`, `8f9c1e49` rule files, routing, SATA and SMART-blindness rules, the config checker.
- `7a59e2f3` Telegram setup script; the operator connected the bot.
- `683f8a90`..`e0be1478` relay runbook, then marked superseded.
- `bbf1dc74` Telegram paging through Grafana, the honeypot tripwire, 10-minute T-Pot sync.
- `15c4ca89` OpenBao seal-status metric.

Bugs found by testing before they could matter: a resolve during a snooze lost the all-clear message; a relay
restart would have paged on stale heartbeats; a mis-indented datasource and baseline rules (twice) that
`syntax-check` and `grep` could not see; an apostrophe that broke generated YAML; a fake test token that the
repo's secret scanner rightly rejected; a rule that lost its `page` label without any check noticing.
