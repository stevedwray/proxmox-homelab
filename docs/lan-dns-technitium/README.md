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

**Planned 2026-09-29. `lan-dns-02`–`10` done 2026-09-29 as file changes — not yet deployed anywhere. `lan-dns-11` done; graylog-stack and technitium-stack deployed on pve 2026-09-29 (Phase 2 live on the primary, `lan-dns-12` all PASS). Graylog rule updated; DNS query logs carry `dns_*` fields. Phase 3 file steps `lan-dns-13`–`16` done 2026-09-29. Cluster formed and verified 2026-09-29 (`lan-dns-17` all PASS). **Phase 3 complete** (failover drill PASS). **LAN cut over to Technitium 2026-09-29 ~12:45 NZDT.** Soak until ~2026-10-06 (argon-02 kept as fallback), then Phase 5.** Operator decisions are
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

| Phase | What | Status |
|---|---|---|
| 1 | Cluster-compatible zone automation: `technitium_zone` role, cluster-aware NS/SOA in `deploy-technitium-stack.yml`, zone adoption (`lan-dns-02`–`05`) | ✅ |
| 2 | Primary as LAN resolver: DoH, Hagezi Pro + TIF-mini + StevenBlack, rebinding protection, router forwarders, Log Exporter → Graylog `dns_*` fields, cAdvisor, metrics token (`lan-dns-06`–`12`) | ✅ live |
| 3 | `technitium-tiny-stack` on pve-tiny, cluster `cluster.lab.gibbsgreatly.xyz`, all zones in the catalog, monitoring + "Technitium DNS" dashboard, security checklist, failover drill (`lan-dns-13`–`18`) | ✅ live |
| 4 | LAN restricted to DNS on the Technitium IPs; DHCP hands out both nodes; RA DNS off (`lan-dns-19`–`21`) | ✅ cut over 2026-09-29 ~12:45 NZDT — **soak to ~2026-10-06** |
| 5 | Retire the Pis (`lan-dns-22`) | ⏳ after soak |
| 6 | DHCP to Technitium — dhcp-refactor Stage E/F, decoupled by `lan-dns-23` | `lan-dns-23` ✅; Stage E/F not started |

**Live endpoints:** `192.168.20.15` (primary, `tech.cluster.lab.gibbsgreatly.xyz`),
`192.168.20.17` (secondary, `technitium-tiny.cluster.lab.gibbsgreatly.xyz`);
admin UI `https://technitium.lab.gibbsgreatly.xyz`; Grafana "Technitium DNS";
Graylog stream "DNS Queries". **Rollback of the LAN switch:**
`./with-secrets-prod ansible-playbook ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml -e lan_dns_mode=pihole`.

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

### 2026-09-29 — cluster formation

- Operator decisions: the Wazuh `apt_repository` deprecation is left for
  the next Wazuh upgrade; the `lan-dns-06` rsyslog change is kept.
- Zone adoption, attempt 1: failed with `role 'technitium_zone' was not
  found` (`changed=0`, one failure per zone — nothing modified). Cause: the
  standalone command ran from the repo root without the
  `ANSIBLE_CONFIG`/`ANSIBLE_ROLES_PATH` that `provision.sh` exports, so
  `terraform/lxc/ansible/ansible.cfg`'s `roles_path` wasn't used. The
  plan's gates ran from `terraform/lxc/ansible` and `--syntax-check` never
  resolves dynamic `include_role`, so they couldn't catch it. Plan and the
  Graylog playbook's usage comment fixed to export both variables.- Cluster formed via the API (operator): the UI refused because an SSO
  user can't initialize a cluster. Init on the primary OK (renamed
  `tech.cluster.lab.gibbsgreatly.xyz`, HTTPS 53443 up). First join failed
  ("Address must be a domain name") — `primaryNodeUrl` must use the
  primary's cluster name; rerun with
  `https://tech.cluster.lab.gibbsgreatly.xyz:53443/` +
  `primaryNodeIpAddress=192.168.20.15` joined. Verified read-only: the
  secondary (`technitium-tiny.cluster.lab.gibbsgreatly.xyz`) has the DoH
  forwarders, blocking (AnyAddress, 2 lists, 13 bypass subnets), all 3
  apps, users `admin`/`metrics`/SSO user; blocks `googlesyndication.com`
  and rebinding-protects `10.0.0.1.nip.io`; the `metrics` token
  authenticates on both nodes. Zones: only the cluster's own until
  adoption. Plan updated with both corrections.- Zone adoption (attempt 2) and clustered deploy ran `failed=0` but
  **adopted nothing** (`changed=0`): Technitium 15.2 returns the node list
  as `clusterNodes`, not `nodes` as its API docs say, so the role decided
  the primary wasn't a cluster primary and skipped (and the deploy's
  cluster assertion would have read the wrong field). Fixed in the role,
  the deploy playbook and the plan; re-tested against the **live**
  cluster-state JSON (primary → catalog name, secondary → none; assertion
  shape passes). No zones had changed.
- The primary reported the secondary `Unreachable`: the join saved
  `webServiceEnableTls=true` on the secondary but never restarted its web
  service, so 53443 wasn't bound (log shows only the HTTP bind). Config
  sync still worked (the secondary pulls). Fix: restart the Technitium
  container on pve-tiny (operator).- Operator restarted the secondary's container: 53443 now answers, the
  primary shows `technitium-tiny.cluster.lab.gibbsgreatly.xyz` as
  `Connected`, and the secondary still blocks. Plan updated with the
  restart step.- **Zone adoption + clustered deploy** (after the `clusterNodes` fix and
  the secondary restart): deploy `failed=0`, smoke PASS, and "Assert the
  cluster manages the parity zone's apex NS and SOA" → **ok** (clustered
  path proven). Both nodes: 12 zones, all `cluster-catalog` members (the
  secondary as Secondary/SecondaryForwarder copies); 3 blocklists (incl.
  StevenBlack), 434,574 entries each; `ad.doubleclick.net` → 0.0.0.0 on
  both.
- **lan-dns-17-verify-secondary**: all 7 critical gates PASS
  (`blocklists-synced`, `lab-zone-replicated`, `lab-serial-matches`,
  `forwarders-synced`, `cluster-owns-lab-ns`, `reverse-zone-synced`,
  `public-over-tcp`) + `cluster-port` PASS. Lab NS is now
  `tech.cluster…` + `technitium-tiny.cluster…` (so `lan-dns-12`'s
  `standalone-ns-unchanged` no longer applies, as planned).

### 2026-09-29 — monitoring + security checklist

- **monitoring-stack** (`TASK_APPROVAL=lan-dns-monitoring`): `failed=0`,
  `changed=9`, smoke PASS.
- **lan-dns-18-verify-observability**: all 4 gates PASS
  (`technitium-job-up`, `node-exporter-up`, `cadvisor-up`,
  `queries-counted` — 2 targets each). Grafana has "Technitium DNS", the
  "CoreDNS" dashboard is gone. Dashboard queries return data: both nodes
  up; ~0.28 q/s on pve, 0 on pve-tiny (no clients yet); 12% blocked over
  1h (mostly tests/platform telemetry); LXC memory ~530 MB / ~480 MB;
  Technitium container ~340 MB / ~255 MB.
- **Checklist, verified by Claude (read-only):**
  - Graylog: "DNS Queries" has messages from **both** nodes with `dns_*`
    fields (pve-tiny: `googlesyndication.com`/`ad.doubleclick.net` →
    Blocked, `example.net` → Recursive, `lab.gibbsgreatly.xyz` →
    Authoritative).
  - Wazuh: agents `technitium-stack` (v4.14.7) and `technitium-tiny-stack`
    (v4.14.8) both **active** with fresh keepalives. Version drift is
    harmless; note for the planned Wazuh upgrade.
  - Backups (pve): job `backup-8b90fc3e-c3a5` (daily 11:00, `pbs-iscsi`,
    all guests minus an exclude list) covers 20015.
- **Checklist, still operator/deferred:** pve-tiny backup job covers 20017
  (not readable — no read-only token in that profile); GVM `.17` in the
  next mgmt_seg scan; NetBox next `netbox-populate` run; Harbor dashboard
  Critical findings on `technitium/dns-server:15.2.0` / cAdvisor.
- **Failover drill** (`TASK_APPROVAL=lan-dns-failover-drill`, operator):
  primary container stopped ~15 s; the secondary answered everything —
  blocking, lab zone, router-owned name, public (DoH), reverse — all PASS;
  primary restarted. After: primary answers normally, SOA serials 64/64,
  router lab path OK, cluster shows the secondary `Connected`,
  VictoriaMetrics re-scraped the primary within one interval.

### 2026-09-29 — lan-dns-19..20 (Phase 4 file steps), executed by Claude in-session

- Operator hand-tested both nodes with dig from garuda: resolution, both
  blocklists (TXT report shows Hagezi + StevenBlack matches), split-horizon
  `nas.gibbsgreatly.xyz`, LAN PTR, lab zone + cluster NS, rebinding
  protection — all as expected.
- **lan-dns-19-mikrotik-playbook** — created
  `ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml`. Gates
  `syntax-check`, `both-modes` PASS. Pre-check probes use
  `googlesyndication.com`.
- **lan-dns-20-mikrotik-firewall-lan** — created
  `ansible/00-initial-setup/mikrotik-firewall-technitium-lan.yml`. Gates
  `syntax-check`, `drop-is-new-only` PASS.

### 2026-09-29 — Phase 4 cutover, attempt 1 (mis-targeted, no client impact)

- Operator ran both MikroTik playbooks with `./with-secrets`, as the plan
  then said. That wrapper defaults to pve-test-vm, whose
  `LAB_IP_TECHNITIUM` is `192.168.20.115`, so both used `.115` instead of
  `.15` (`.17` came from the shared `.env` and was right).
- Resolver switch: its pre-check couldn't reach `.115` and refused —
  **DHCP unchanged** (still `192.168.1.23`), RA unchanged.
- Firewall: the 4 `technitium-lan:` rules were added, correctly ordered
  before `*AE`, but the `technitium-dns` address list got `.115` + `.17`,
  so the primary `.15` was left unrestricted; the final DNS check then
  failed on `.115`. No breakage (LAN → `.15` unchanged).
- Fixes: both playbooks now refuse unless `PVE_ENV=pve`; the firewall
  playbook removes address-list entries that aren't Technitium nodes and
  asserts the list is exact; plan commands use `./with-secrets-prod`.
  Logic tested against the live address list (removes only `.115`, adds
  `.15`).

### 2026-09-29 — Phase 4 cutover, attempt 2 (live)

- Operator re-ran both playbooks via `./with-secrets-prod`
  (`TASK_APPROVAL=lan-dns-cutover`); resolver recap `failed=0`,
  `changed=2`.
- Router verified (GET): DHCP `dns-server` = `192.168.20.15,192.168.20.17`;
  `bridgeLocal` ND `advertise-dns=no` (dns list kept for rollback);
  `technitium-dns` address list exactly `.15` + `.17`; the 4
  `technitium-lan:` rules in order (udp/53, tcp/53, garuda, drop-new).
- garuda: `nmcli device reapply` doesn't renew the lease; its T1 renewal
  picked up `192.168.20.15`/`.17` within the minute. System-resolver
  checks: `googlesyndication.com` → 0.0.0.0, `github.com` resolves,
  `nas.gibbsgreatly.xyz` and `traefik.lab…` via getent, HTTPS to github OK.
- Other clients switch at their own lease renewal (30 min lease).
- **Soak (7 days):** watch argon-02's Pi-hole query log for clients with
  hard-coded DNS; Technitium dashboard for SERVFAIL and `dropped`
  (QPM limit 600/min per client); over-blocking reports → allow entries in
  `configure-technitium-lan-resolver.yml`. Rollback:
  `./with-secrets-prod ansible-playbook ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml -e lan_dns_mode=pihole`.
- **lan-dns-21-docs-after-cutover** (Claude): `router/desired-config.md`
  — DHCP-hands-out, RA DNS and Upstream bullets updated as specified.
  Beyond the step's text (same file, allowed path): the `ND (bridgeLocal)`
  bullet's `advertise-dns=yes` corrected to `no`, and a short note on the
  four `technitium-lan:` forward rules added above the IPv4 forward-chain
  table. Gates `dhcp-line`, `pihole-line-gone` PASS.

### 2026-09-29 — lan-dns-23 + docs sweep (Claude)

- **lan-dns-23-dhcp-dns-option**: Decision 9 added to
  `docs/dhcp-refactor/decisions.md`; the cutover packet's DNS-option row and
  checklist now read the live value at execution time (the checklist's
  stale "not Technitium" tail removed too). Gates `decision-9`,
  `stale-dns-gone` PASS.
- Docs brought to live state: `technitium-stack/STACK_CONTRACT.md`
  (status + dependents), `docs/design/network.md` (LAN resolver path,
  pve-tiny node), `docs/dhcp-refactor/{README,current-state}.md` (dated
  updates incl. Compute now at `.105`), `docs/dns-refactor/README.md`
  pointer, `docs/design/architecture.md` FR-12 note; `plan.md` gained an
  execution-status section with the lessons from running it.
