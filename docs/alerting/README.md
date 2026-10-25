# alerting

Status as of **2026-10-24**: the alerting is **live and proven end to end.** Discord carries everything;
Telegram carries the pages; both were driven by real faults and by drills (see *Proven live* below). What
remains is operator housekeeping and the future-state items. This file is the current-state summary: what it
does, what was decided, what was found, where things live, what went wrong on the way. The plan
([plan.md](plan.md)) holds the steps and its own status table.

Supersedes `docs/catch-up/07-baseline-alerting.md` (Discord only).

## Why

Nothing in the lab told the operator when something broke. Verified 2026-10-24:

- **pve-tiny's NVMe is failing** (media errors 308, then 974; 47 kernel errors in one day on 10-23).
  The errors were in Graylog and in VictoriaMetrics the whole time, and a nightly PBS backup failed
  every night. Nobody was told. (An RMA is in progress.) **Now it pages**: the NVMe media-errors rule fired on it within hours of the deploy.
- **Seven stacks have had no host metrics** since 2026-10-21 (portainer since 10-23): the cert-renewal
  timer sends SIGHUP and node_exporter exits. The fix, `scripts/node-exporter-renew-fix.sh`, was run on 2026-10-24 and all seven report again.
- **Live Grafana had only the default email receiver:** no contact point, no alert rule. It now has 37 rules and five contact points.

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

A rule that **cannot query its datasource** makes Grafana raise its own `DatasourceError` (or `DatasourceNoData`)
alert, which inherits the rule's labels including `page: "true"`. Those are routed to Discord `#alerts-warning`
only and never page (found the hard way: see *Lessons learned*).
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
| Workstation forwarder | **syslog-ng from Arch's official repo** (operator, 2026-10-24: a standard daemon, not a script). rsyslog was the first choice but the only Arch build (chaotic-aur) crashes against glibc 2.44 (stale libfastjson, `Relink ... IFUNC symbol modf`). Journal in, warning and above out, RFC 5424 over TCP with a disk buffer; wire format tested against the real 4.12 binary |
| UPS | None, so no power alerts |
| Message format | One headline, the rule's own `summary`, a silence link. Telegram is **plain text** (`parse_mode: None`): Markdown would drop a page on a stray `_`. Discord gets a title plus a `[silence]` link. Templates: `alerting/templates/homelab-templates.yml` |

## Design rules (each learned from real data)

1. **Alert on exact text, never on log level.** Docker sends container stderr as level 3; Authentik alone produced 1.28M "errors" in a week.
2. **Hardware rules must select `job="node_exporter_hw"`.** Every LXC's node_exporter also exposes the *host's* NVMe sensors, so 17 targets repeat the same drives; an unfiltered rule pages 17 times for one disk.
3. **Alert on error *increase*, not the overall health flag.** pve-tiny's failing drive showed `smartmon_device_smart_healthy = 1` only because `smartctl` cannot read it at all (`smartmon_device_smart_available = 0`): the flag was a default, not a verdict. The NVMe collector read it, and `nvme_media_errors_total` was climbing.
4. **Exclude what is off or isolated on purpose:** `pve-test` (laptop, heatsinks being reseated), `garuda` (the workstation), the Foreverworld exporters, everything from `pentest_seg`.
5. **Keep the page list short** (fewer than one a week) or it gets ignored.
6. **Sender identity is `relay_src_ip`, not `source`.** `source` is whatever hostname the sender claims. (Live in Graylog.)
7. **Make "no data" mean something on purpose.** `openbao_sealed` treats no data as firing, so its metric must exist before the rule is deployed.
8. **Validate generated config structurally.** Literal blocks in a step are 2 spaces deeper than in the file, and `syntax-check` cannot see inside `content: |` strings. `scripts/check_grafana_provisioning.py` parses the inline Grafana files and walks every rule through the routing.
9. **A rule's own error alert inherits its labels.** `DatasourceError` and `DatasourceNoData` carry `page: "true"`, so they would page with an unrendered annotation. They have their own route to Discord warning, and the checker simulates them for every rule.
10. **Test a drill from a host that is not on the allowlist.** The workstation, the Pis' own tooling and Greenbone are allowlisted on purpose, so drilling from them proves the allowlist, not the alert. `argon-01` (192.168.1.22) is a convenient non-allowlisted LAN host while the Kali laptop is off.
11. **A critical alert that is not a page must be proven not to page.** Drill A (`docker stop cadvisor`) checks both halves: it arrives in Discord and Telegram stays silent.
12. **Thresholds follow the hardware, not a global default.** The Pis' SSDs run 48 to 56 C normally, so 55 C paged `argon-02` for nothing; the Pis have their own 60 C rule and everything else keeps 55 C (operator, 2026-10-24).

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
- **Freshness:** the tripwire treats "no data" as fine, so a stalled sync would leave it blind without a word. The rule
  `Honeypot data has stopped arriving` fires (Discord `#security`) when fewer than 1,000 Suricata events arrive in an hour; normal is
  7,200 to 10,000, and no hour in 14 days was below 7,231. It also fires if OpenSearch or the T-Pot sync is down for over an hour, for any
  reason, including a planned move of `opensearch-stack` or `secpipe-stack`: that is the rule working, and the tripwire is blind then.

## What exists today (verified 2026-10-24)

| Piece | State |
|---|---|
| Graylog stamps `relay_src_ip`; "Pentest Segment" stream (14-day index) | **Live** (commit `e8b0b4ef`) |
| MikroTik: pentest_seg may reach only Graylog (514) and step-ca (443) | **Live** |
| Discord server, four channels, four webhooks, OpenBao `services/grafana`, manifest | **Live**; bot token still to be reset in the Developer Portal |
| Telegram bot, credentials in OpenBao `services/grafana` (v3) and the manifest | **Live** |
| Grafana alerting: 37 rules, 5 contact points, policy, message templates | **Live** (deployed 2026-10-24, nine times, including the vulnerability, honeypot-freshness and six NAS rules). Eight router rules (mktxp) are in the repo and go live with the next monitoring-stack deploy |
| OpenBao seal-status metric (`openbao_sealed`) | **Live**, value 0; the nightly snapshot succeeds at 03:30 |
| T-Pot to OpenSearch sync | **Live**, every 10 minutes (`tpot_findings_ingest_on_calendar`) |
| node_exporter fleet repair (SIGHUP bug) | **Done** 2026-10-24; seven stacks reporting again |
| Omada metrics in VictoriaMetrics | **Restored** by the monitoring-stack deploy |
| NVMe/SMART metrics for pve, pve-tiny, argon-01/02 | Live. `smartctl` cannot read pve `sdg` (NVMe in a USB bridge) or pve-tiny's NVMe |
| Temperatures | Live; pve NVMe composites read about 67 C against a 70 C warning |
| MikroTik hardware | One health sensor, `cpu-temperature` (63 C). RouterOS 7.25 (upgraded 2026-10-24), RouterBOARD firmware 7.19.6 with 7.25 ready. Least-privilege API access is **live**; mktxp and eight rules are built, **not yet deployed** |
| NAS (Asustor Drivestor) | SNMPv3 (authNoPriv/MD5) through `snmp-exporter`; six rules **live and verified** 2026-10-24. `Volume1` is `linear` (no redundancy) |
| Workstation `garuda`, argon-01/02 | **In Graylog** (2026-10-24, proven by a proof message and its `relay_src_ip` from each): workstation warning and above via syslog-ng, the Pis via the `rsyslog_forward` role with kernel logging kept |
| `pve-test` laptop (and the Kali VM on it) | Off on purpose (heatsinks being reseated) |
| pentagi | Decommissioned; its scrape jobs were removed from the monitoring deploy |
| OCI box | aarch64, 8 GB RAM (about 6.9 GB free), 2 CPUs, load 0.03; Pangolin, Traefik and Gerbil use under 700 MB |

## Proven live (2026-10-24)

| Check | Result |
|---|---|
| Contact-point **Test**, `homelab-page` and `homelab-tripwire` | Telegram and Discord both delivered. Confirms Grafana 13's Telegram keys (`bottoken`, `chatid`, `parse_mode`) |
| Drill A: `docker stop cadvisor` on the monitoring host | "Scrape target down" in `#alerts-critical` after about 6m40s (5m pending plus evaluation); **nothing on Telegram**; `[RESOLVED]` followed after the restart |
| Honeypot tripwire from `argon-01` (445 and 23) | Telegram and `#security`, source named **192.168.1.22** (the dotted `src_ip.keyword` label survives the notification stage); about 11 minutes from probe to page |
| Allowlist: the same probes from the workstation (192.168.1.104) | Recorded as flows, correctly **not** alerted |
| First real page: pve-tiny `nvme0n1`, 7 new media errors in an hour | Telegram, as designed. Silenced until the RMA drive is in |
| Grafana restart | Rule states reset; a `DatasourceError` for the tripwire paged once (fixed, see lessons) |

## Where things live

| What | Where |
|---|---|
| Alert rules | `terraform/lxc/stacks/monitoring-stack/alerting/homelab-{baseline,hardware,honeypot}.yml` |
| Wiring (datasource, copy, contact points, policy, Telegram vars, restart) | `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` |
| Message templates | `terraform/lxc/stacks/monitoring-stack/alerting/templates/homelab-templates.yml` |
| Routing and config check | `scripts/check_grafana_provisioning.py` (rules, routing, templates, synthetic error alerts) |
| Discord setup | `scripts/discord_bootstrap.py` (17 tests), [discord-setup.md](discord-setup.md) |
| Telegram setup | `scripts/telegram_setup.py` (12 tests), [telegram-setup.md](telegram-setup.md) |
| OpenBao seal metric | `terraform/lxc/ansible/files/openbao/openbao_health.py` (5 tests) + `deploy-openbao.yml` |
| T-Pot sync cadence | `terraform/lxc/ansible/roles/tpot_findings_ingest/` (defaults, timer) |
| Graylog sender IP and pentest stream | `roles/rsyslog_forward/templates/graylog_inbound.conf.j2`, `playbooks/configure-graylog-pentest-seg.yml` |
| MikroTik narrowing | `ansible/00-initial-setup/mikrotik-firewall-pentest-seg-narrow.yml`, `terraform/lxc/network/pve.yaml` |
| Workstation and Pi enrolment (written, not run) | plan steps `alerting-00` to `02` |
| **Parked relay** | `~/git/oci/roles/alert_relay/` (not in any git repo I can see: the Pangolin source was copied into this repo's `oci/` on `task/oci-security-prs-integration`, unmerged, and `~/git/oci` stays the operational source until that cutover; when the import merges, carry `roles/alert_relay/` into `oci/roles/`). `site.yml` has the role commented out. Superseded runbook: [relay-deploy.md](relay-deploy.md) |

## Open items for the operator

1. **Silence the NVMe media-errors alert for pve-tiny** until the RMA drive is in (Grafana, Alerting, Silences). **Set 2026-10-24, ends 2026-10-26 13:46: extend it when the RMA date is known, nothing reminds you when it lapses**. The pve-tiny evacuation (a parallel stream, `work/pve-tiny-evacuation`) will move stacks off that host, so its `stack=pve-tiny` alerts and the secpipe/honeypot sync host change with it. Re-check the silence and the `node_exporter_hw` targets after each stack moves. The operator is managing the expiry (2026-10-26 13:46).
2. ~~Reset the Discord bot token~~ Done 2026-10-24.
3. **`OpenBao manifest drift` is firing at warning level for `services/pentest-lab`**: it exists in OpenBao but not in `stable`'s manifest. It clears when the pentest-lab manifest change merges.
4. **NAS monitoring is live** (SNMPv3). `Volume1` is a `linear` volume with no redundancy: decide whether that is intended.
5. **Deploy the MikroTik monitoring** (mktxp, built; plan Phase 0b). The firmware-update notice will fire at once: RouterBOARD firmware 7.19.6 is installed and 7.25 is ready. The workstation and Pis are enrolled.
6. **Both argon Pis run crash-looping Portainer containers** (`portainer-ce` and `portainer-agent` on argon-01, 67k+ restarts each over weeks; a `portainer` and an agent on argon-02). Found by the enrolment; they are probably obsolete and add noise to the Pis' logs. Operator decision to remove.
7. **Deploy the Phase 5 vulnerability rules** (next monitoring-stack deploy), then **Phase 6** digest and native integrations. Phase 2, the Graylog log alerts, is applied and drilled.
8. **Decide the future state:** keep the relay, or Grafana plus Uptime Kuma. Also the dedicated port (9443 proposed) and who terminates mTLS. The relay code moves with the Pangolin source into `oci/` when `task/oci-security-prs-integration` merges.
9. **Phase 7: align monitoring with the post-migration lab** (plan.md). The honeypot sync cadence is fixed (W1, drill outstanding); the `pve-tiny` silence needed before it is powered off (W3); 15 running guests, including `opensearch-stack`, have no metrics (W2); nothing alerts on a failed backup (W5).
10. **Until the dead man's switch exists, nothing watches Grafana, VictoriaMetrics, Graylog or the monitoring host.**
    The independent Icinga pair on the Argon Pis ([docs/icinga-pi-observability](../icinga-pi-observability/README.md))
    is the planned answer: Stage 1 (the HA pair) is live, the checks of Grafana/VictoriaMetrics/Graylog are Stage 2 and the
    direct Discord/Telegram notifications are Stage 3, neither enabled yet. It supersedes Phase 4b's blackbox_exporter probes 3-7
    (decided 2026-10-25, plan.md Phase 4b): they are not built; Icinga owns them.

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

All 2026-10-24, on `work/graylog-sender-ip-pentest-stream`, merged to `stable` as one branch (it also carries the
operator's `2fd7175d`, mcp-utility back to pve, which the pve-tiny evacuation branch already contains):

- `e8b0b4ef` Graylog sender IP, `pentest_seg` stream, MikroTik narrowing (the first live change).
- `b52209b3`..`5c60e214` Discord bootstrap script, runbook and fixes; channels and webhooks live.
- `dff30d4c` Discord fields in the manifest.
- `927f6d28`, `8f9c1e49` rule files, routing, SATA and SMART-blindness rules, the config checker.
- `7a59e2f3` Telegram setup script; the operator connected the bot.
- `683f8a90`..`e0be1478` relay runbook, then marked superseded.
- `bbf1dc74` Telegram paging through Grafana, the honeypot tripwire, 10-minute T-Pot sync.
- `15c4ca89` OpenBao seal-status metric.
- `47aae0f8` documentation brought up to date (pre-deploy).
- `b3708f47` pentagi scrape targets removed (they would have fired three "target down" alerts).
- `a3d65869` Telegram fields added to the `services/grafana` manifest (OpenBao written first).
- `c611c2f7` short plain-text messages and Discord/Telegram templates.
- `3c32df75` a rule's datasource-error alert must never page.
- `519aa393` `~/git/oci` is moving into this repo's `oci/`: nothing to commit there.

Deploy order on the day (each run by the operator): node_exporter repair, OpenBao seal metric, Telegram credentials
into OpenBao, then the manifest, monitoring-stack (three times: rules, templates, error routing), secpipe-stack
(10-minute sync), then the drills.

## Lessons learned

**Process**

- **Write the secret to OpenBao first, the manifest second.** The wrappers fail closed on a manifest field with
  no value; the order held and nothing broke.
- **A plan's literal blocks are 2 spaces deeper than the file they describe.** It broke a datasource, baseline
  rules and the contact points. `syntax-check` cannot see inside `content: |`, so the checker parses the inline
  files and walks every rule through the routing. Mutation-test a checker: it initially missed "critical hardware
  rule loses its page label".
- **The production wrapper treats `env`, `ssh`, `curl` and `ansible-playbook` as mutating.** Reads that need
  credentials (a Grafana query, an `env` readback) need the operator to approve and run them; write the script,
  have it print only counts, and hand it over.
- **Running a playbook by hand needs `ANSIBLE_CONFIG` and `ANSIBLE_ROLES_PATH`** (`provision.sh` sets them), or
  `lxc_base` is "not found". `--check` reports `Enable timers` as failed for a unit it has not written yet;
  that is an artifact, not a fault.
- **Do not take a stack list from an old note.** pentagi was decommissioned, yet the plan listed it and the
  monitoring deploy still scraped it. Read the live target list (`up==0`) before telling the operator what to expect.
- **Check where a sibling repo's work really lives.** `~/git/oci` is being imported into this repo's `oci/` on an
  unmerged branch, so "commit the oci tree" was wrong advice.

**Alerting design**

- **A rule's own error alert inherits its labels, including `page`.** The honeypot rule paged Telegram with raw
  template text when Grafana restarted before OpenSearch was ready. Fix: route `DatasourceError` and
  `DatasourceNoData` to Discord warning; the checker simulates them per rule.
- **Telegram must be plain text.** Markdown parsing rejects a stray `_` or `*`, and our labels are full of
  underscores; the failure mode is a lost page. Fix noise with a template, not a parse mode.
- **Restarting Grafana resets rule states** and can re-send open alerts once; expect it after each deploy.
- **A drill from an allowlisted host proves the allowlist.** The first honeypot drill came from the workstation
  and was correctly ignored; the Kali VM was off (its laptop is being repaired). Use a LAN host that is not on the list.
- **The honeypot's port 22 answers as a "TP-Link router"** (Cowrie). An `ssh root@tpot` is a decoy hit, not a login.
- **The OpenBao drift check compares against `stable`'s manifest on GitHub**, so a secret written ahead of its
  manifest change raises a warning until that merges. It did its job.
- **The scrape of framework `llamacpp :8080` was down for lack of the API key** in the old config; the monitoring
  deploy added it and it came up. (The CSE panel's separate "unreachable" report was investigated in another session.)
- **A critical alert that is not a page must be proven not to page** (drill A checks both halves).
- **An event rule on a gauge threshold flaps when the series has gaps** (2026-10-24, after an accidental router power cycle).
  "Router has restarted" was `uptime < 3600`, so it stayed firing for an hour, and every time mktxp's session to the router dropped
  (every 15 minutes after the reboot) the series vanished for about two minutes, the alert resolved, and it re-fired when the series
  returned: four firing episodes and eight Discord messages for one restart. An event ages out, it does not recover. Fix: bridge gaps with
  `last_over_time(...[30m])`, keep the window short (15 minutes), and label the rule `event: "true"`, which routes to a contact point with no
  resolve message. The checker fails an `event` rule that can send a resolve message. Replayed against the real data: 4 episodes became 1.
- **A gap in the data also stops every rule that has a `for`.** The same fault (the router closes mktxp's API session every 15
  minutes, cause not found: a packet capture showed the router sending the FIN, there is no scheduler or script on it, and
  before the power cycle one session lasted 1 h 44 min) removes the router's metrics for about two minutes each time. Grafana
  restarts a rule's `for` from zero when its data vanishes, so with 14-minute unbroken stretches the 15-minute temperature rule and the
  one-hour update notices could not fire at all. Router gauge rules now use `last_over_time(...[5m])` (replayed since the power
  cycle: the firmware notice's longest unbroken run went from 15 to 65 minutes) and the "metrics have stopped arriving" rule uses
  `absent_over_time(...[5m])`. Turning off mktxp's persistent connection was rejected: it would add a login and logout every minute,
  about 2,900 Graylog messages a day, and push the router's useful history out of its 1,000-line memory log in eight hours.
  **Open:** why the router now ends API sessions after exactly 15 minutes. Worth a router restart or a look at RouterOS 7.25 release notes.
