# lan-dns-technitium — Pi-hole to Technitium for the whole LAN

## What this is

Replace the two Raspberry Pi Pi-holes (`argon-01` 192.168.1.22,
`argon-02` 192.168.1.23) with Technitium as the LAN's DNS resolver: two
synced Technitium nodes — the existing `technitium-stack` on `pve`
(192.168.20.15, cluster primary) and a new `technitium-tiny-stack` on
`pve-tiny` (192.168.20.17, cluster secondary) — with Pi-hole-style
ad/malware blocking. Then, as a separate, largely independent track,
LAN DHCP moves to Technitium via the already-planned
[docs/dhcp-refactor/](../dhcp-refactor/) Stage E/F.

## Status

**Planned 2026-09-29. `lan-dns-02`–`10` done 2026-09-29 as file changes — not yet deployed anywhere. `lan-dns-11` done; graylog-stack and technitium-stack deployed on pve 2026-09-29 (Phase 2 live on the primary, `lan-dns-12` all PASS). Graylog rule updated; DNS query logs carry `dns_*` fields. Phase 3 file steps `lan-dns-13`–`16` done 2026-09-29. technitium-tiny-stack created and deployed on pve-tiny 2026-09-29. Next: cluster formation.** Operator decisions are
recorded at the top of [plan.md](./plan.md): mgmt_seg IPs as the client
path (IPv4 DNS only, RA stops advertising DNS), argon-02 kept as a cold
fallback through a 7-day soak then both Pis retired, DoH forwarding
(Cloudflare + Quad9), and a new secondary stack on pve-tiny rather than
re-homing the live primary's Terraform state first. No Pi-hole config is
carried over (operator, 2026-09-29) — Technitium gets its own blocklists.
Everything, zones included, syncs through Technitium clustering; Phase 1
makes the repo's zone automation compatible with that (operator,
2026-09-29). Both nodes get the platform's monitoring, logging and
security coverage (Grafana, Graylog incl. every DNS query, Wazuh, GVM,
LAN access lockdown, rebinding protection); no alerting — none exists
platform-wide yet (operator, 2026-09-29).

Found while planning (live, 2026-09-29): **argon-01 answers ping but not
DNS**, and the MikroTik already hands out only `192.168.1.23` — so the
LAN currently has a single working resolver. The dhcp-refactor cutover
packet's recorded DNS option (`192.168.1.22`) is stale for the same
reason; `lan-dns-23` fixes that.

## Phases

| Phase | What | Client impact |
|---|---|---|
| 1 | Make zone automation cluster-compatible: shared `technitium_zone` role, cluster-aware NS/SOA handling in `deploy-technitium-stack.yml`, zone-adoption playbook (`lan-dns-02`–`05`) | none (behavior-neutral while standalone) |
| 2 | Primary becomes a LAN-grade resolver with observability: rsyslog forwards structured data, Graylog "DNS Queries" index set, DoH + Hagezi blocklists + rebinding protection + Log Exporter + query-log app, cAdvisor + console logging, metrics token; graylog-stack then technitium-stack re-provisioned (`lan-dns-06`–`12`) | none (no LAN client uses it yet; SDN subnets bypass blocking/rebinding) |
| 3 | `technitium-tiny-stack` on pve-tiny, cluster formed, zones adopted, monitoring scrapes both nodes + "Technitium DNS" dashboard (CoreDNS job/dashboard removed), security checklist, failover drill (`lan-dns-13`–`18`) | none |
| 4 | LAN restricted to DNS on the Technitium IPs, then MikroTik DHCP hands out both nodes; 7-day soak (`lan-dns-19`–`21`) | **cutover** — one-command rollback for each |
| 5 | Retire the Pis (`lan-dns-22`) | none after soak |
| 6 | DHCP to Technitium — existing dhcp-refactor Stage E/F, decoupled by `lan-dns-23` | separate window |

Steps with no dependency on each other (e.g. `lan-dns-13` and
`lan-dns-23`) can run in any order; `depends_on` in each step is
authoritative.

## Files

- [plan.md](./plan.md) — decisions, research, and the step blocks
  (`docs/agent-design/step-packet-schema.md` shape)
- `artifacts/` — gitignored scratch, not created yet

## Hand-back log

Each executed step appends an entry here: step id, date, the edit made,
each gate's actual result.

### 2026-09-29 — lan-dns-02..05 (Phase 1), executed by Claude in-session

File changes only; nothing run against any host. Applied from the plan's
literal blocks verbatim.

- **lan-dns-02-zone-role** — created `roles/technitium_zone/{defaults,tasks}/main.yml`.
  Gates: `yaml-parses` PASS, `uses-catalog-and-cluster-state` PASS.
- **lan-dns-03-zone-role-consumers** — `technitium_dns_record` reverse-zone
  creation and `technitium-framework-forwarder.yml`'s forwarder creation now
  go through `technitium_zone`. Gates: `syntax-dns-record-consumer` PASS,
  `syntax-framework` PASS, `no-direct-zone-create` PASS. Checked separately:
  no remaining references to the removed registered variables.
- **lan-dns-04-deploy-cluster-aware** — bootstrap/parity zone creation via
  the role; NS/SOA reconciliation wrapped in a standalone-only block plus
  two clustered-mode assertion tasks. Gates: `syntax-check`,
  `only-lab-forwarder-create-left`, `standalone-guard`,
  `ns-soa-tasks-preserved` all PASS. Checked separately: the five
  re-indented NS/SOA tasks are byte-identical to HEAD apart from the extra
  4-space indent.
- **lan-dns-05-adopt-zones-playbook** — created
  `playbooks/technitium-cluster-adopt-zones.yml`; appended the cluster-
  contract bullet to `technitium-stack/STACK_CONTRACT.md`. Gates:
  `syntax-check` PASS, `contract-bullet` PASS.

`python3 -m unittest discover -s terraform/lxc -p "test_*.py"`: 87 tests,
8 failures — the identical set fails on the pre-change HEAD
(`test_reconcile_edge` ×7, `test_render_edge_coredns` ×1), so pre-existing
and unrelated. Real validation of Phase 1 happens at the Phase 2
`provision.sh --stack technitium-stack` run on pve (standalone path).

### 2026-09-29 — lan-dns-06..10 (Phase 2 file steps), executed by Claude in-session

File changes only; nothing run against any host. Applied from the plan's
literal blocks verbatim.

- **lan-dns-06-rsyslog-structured-data** — `GraylogForward` now forwards
  `%STRUCTURED-DATA%` (was a literal `-`), plus the two comment lines.
  Gates: `template-updated` PASS, `single-template-definition` PASS.
- **lan-dns-07-graylog-dns-queries** — created
  `playbooks/configure-graylog-dns-queries.yml`; imported at the end of
  `deploy-graylog-stack.yml` (additions only). Gates: `syntax-standalone`,
  `syntax-graylog-deploy`, `import-is-last` all PASS.
- **lan-dns-08-resolver-playbook** — created
  `playbooks/configure-technitium-lan-resolver.yml`. Gates: `syntax-check`,
  `blocklists-present`, `bypass-excludes-lan` all PASS.
- **lan-dns-09-node-observability** — created
  `playbooks/technitium-node-observability.yml`; observability bullet added
  to `technitium-stack/STACK_CONTRACT.md`. Gates: `syntax-check`,
  `separate-compose-project`, `contract-bullet` all PASS.
- **lan-dns-10-import-into-deploy** — three imports appended to
  `deploy-technitium-stack.yml` (additions only, verified with `git diff`).
  Gates: `syntax-check` PASS, `import-order` PASS.

Unit tests: same 8 pre-existing failures as before Phase 1, nothing new.

### 2026-09-29 — metrics token + lan-dns-11

- Operator created Technitium user `metrics` (removed from Everyone,
  Dashboard: View only), an API token `victoriametrics`, and wrote it to
  OpenBao `services/technitium` field `TECHNITIUM_METRICS_TOKEN` with
  `scripts/openbao_write.py` (write + snapshot reported OK).
- **lan-dns-11-metrics-token-manifest** — edited by the operator (Claude's
  permissions deny `secrets/`). Gates, run by the operator:
  `field-declared` PASS ("manifest ok"), `wrapper-resolves-it` PASS.

### 2026-09-29 — Phase 2 production deploys (pve), run by the operator

Claude's harness blocks production deploys even after chat approval, so
the operator ran each approved command; Claude verified afterwards.

- **graylog-stack** (`TASK_APPROVAL=lan-dns-graylog`): `failed=0`,
  `changed=9`, smoke PASS. Verified read-only via the Graylog API: "DNS
  Queries" index set (`gl-dns`, P30D) and stream (running) exist; rule
  `route-dns-queries`; pipeline `dns-queries` added to the Default Stream
  beside `log-segmentation` and `source-identity-fixups`; 8 other stacks'
  logs still arriving with unchanged `application_name`s. Only rsyslog
  noise: brief "connection refused" from forwarders during the relay
  restart, all reconnected.
- **technitium-stack, run 1** (`lan-dns-technitium-primary`): failed at
  "Probe blocking from the LAN" after the settings/apps had applied.
  Cause: the probe used `doubleclick.net`, which Hagezi Pro deliberately
  does not block (it lists subdomains such as `g.doubleclick.net`).
  Blocking itself worked (380,970 block-list zones loaded). Fixed in
  af06595f (probe `googlesyndication.com`, a listed domain); all remaining
  probes pre-checked by hand before the rerun.
- **technitium-stack, run 2**: `failed=0`, `changed=6`, smoke
  (`verify-parity.sh`) PASS.
- **lan-dns-12-verify-primary**: all 9 critical gates PASS
  (`blocks-ads`, `resolves-public`, `lab-zone`, `router-owned-name`,
  `lan-ptr`, `rebinding-protection`, `split-horizon-still-private`,
  `cadvisor-up`, `standalone-ns-unchanged`).
- **Graylog DNS logs**: 253 query logs in 15 min, all in "DNS Queries",
  facility `local6`; Technitium server log in Docker Chatter as
  `docker-technitium`. **But no per-query fields**: the Log Exporter
  double-wraps (its formatter emits a full RFC 5424 line which the sink
  wraps again), so `[meta clientIp=... responseType=... qName=...]` is
  text in the message body. `lan-dns-06` was therefore unnecessary for
  this (kept; byte-identical). Fix: `route-dns-queries` now extracts
  `dns_client_ip`, `dns_protocol`, `dns_response_type`, `dns_rtt_ms`,
  `dns_rcode`, `dns_qname`, `dns_qtype`, `dns_answers`, and the playbook
  updates the rule on drift. Regexes tested against real messages; rule
  source accepted by Graylog's parse-only endpoint; Ansible-rendered source
  byte-identical to the parsed one. Needs an approved run of
  `configure-graylog-dns-queries.yml` on graylog-stack.
- **Graylog rule update** (`TASK_APPROVAL=lan-dns-graylog-rule`, targeted
  `configure-graylog-dns-queries.yml` run): `changed=1`, `failed=0`.
  Verified: new "DNS Queries" messages carry `dns_client_ip`,
  `dns_response_type`, `dns_qname`, `dns_qtype`, `dns_rcode`,
  `dns_answers`, `dns_rtt_ms` — e.g. garuda's `googlesyndication.com` →
  `Blocked`, `wikipedia.org` → `Recursive`. Every unparsed `local6`
  message predates the rule reload (first parsed 20:03:39Z); the same
  message shapes parse after it. Cosmetic: `dns_answers` keeps the
  answer's surrounding quotes.

### 2026-09-29 — lan-dns-13..16 (Phase 3 file steps), executed by Claude in-session

File changes only; nothing run against any host.

- **lan-dns-13-ip-wiring** — `.env` (`LAB_IP_TECHNITIUM_TINY`,
  `TF_VAR_lab_ip_technitium_tiny` = 192.168.20.17), `variables.tf`,
  `main.tf`; `terraform fmt` clean. Gates `env-vars`, `tf-wired`, `fmt` PASS.
  Checked separately: same infrastructure touchpoints as the last variable
  added this way (`lab_ip_cse_panel`).
- **lan-dns-14-stack-files** — `stacks/technitium-tiny-stack/{stack.yaml,STACK_CONTRACT.md}`,
  `environments/pve-tiny/technitium-tiny-stack/terragrunt.hcl` (copy of
  cse-panel-stack's), `network/pve-tiny.yaml` container entry. Gates
  `metadata-valid`, `network-yaml-parses`, `terragrunt-copied` PASS.
- **lan-dns-15-deploy-playbook** — `deploy-technitium-tiny-stack.yml`
  (Docker base play copied byte-for-byte from the primary's playbook, then
  the literal). Gates `syntax-check`, `imports-node-observability`,
  `same-image-tag` PASS.
- **lan-dns-16-monitoring-scrape-dashboard** — both nodes added to the
  `node_exporter` and `cadvisor` jobs, dead `coredns` job replaced by the
  `technitium` job (bearer token), `coredns.json` removed,
  `technitium.json` (12 panels) added. Gates `syntax-check`, `coredns-gone`,
  `technitium-targets`, `dashboard-valid` PASS.

Unit tests: same 8 pre-existing failures.
- **Pre-deploy (read-only)**: `terragrunt plan` for technitium-tiny-stack
  = 5 add / 0 change / 0 destroy; CT 20017 on pve-tiny, 192.168.20.17/24
  gw .20.1, bridge `tvmgmt`, 1 core, 2048 MB + 1024 MB swap, 12 GB rootfs +
  6 GB docker on `local-lvm`, unprivileged + nesting, start on boot.
  192.168.20.17 doesn't answer ping and has no PTR. VMID check left to the
  operator (pve-tiny profile has no read-only API token). Plan corrected:
  creation is `terragrunt apply` then `provision.sh` — `provision.sh` alone
  never creates the CT.

### 2026-09-29 — technitium-tiny-stack deployed (pve-tiny), run by the operator

- `terragrunt apply` + `provision.sh --stack technitium-tiny-stack`
  (`TASK_APPROVAL=lan-dns-technitium-tiny-deploy`): `failed=0`,
  `changed=62`.
- Verified from garuda: `.17` resolves public names itself (default
  recursion), doesn't block yet and has no lab zone (both arrive with the
  cluster), API :5380 200, cAdvisor :8080 200, node_exporter :9100 401
  (auth required = running). Server domain
  `technitium-tiny.lab.gibbsgreatly.xyz` → becomes
  `technitium-tiny.cluster.lab.gibbsgreatly.xyz` on join.
- `secrets/manifest.json` (lan-dns-11) committed by Claude with operator
  consent (4f78c9a4).
- **StevenBlack unified hosts added** to the blocklists (operator decision):
  covers the ad hosts Hagezi deliberately leaves alone (`doubleclick.net`,
  `ad.doubleclick.net`, `adservice.google.com` all listed). Goes live at the
  next technitium-stack run (cluster step 5). Capacity: primary is at
  410 MiB / 2 GiB with 380k entries (249 MiB before lists); StevenBlack
  adds ~81k lines.
