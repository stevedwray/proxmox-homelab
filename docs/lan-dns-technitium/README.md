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

**Planned 2026-09-29. `lan-dns-02`–`10` done 2026-09-29 as file changes — not yet deployed anywhere. Next: operator creates the Technitium `metrics` token and writes it to OpenBao, then `lan-dns-11`, then the approved graylog-stack and technitium-stack deploys.** Operator decisions are
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
