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

**Planned 2026-09-29, no steps executed.** Operator decisions are
recorded at the top of [plan.md](./plan.md): mgmt_seg IPs as the client
path (IPv4 DNS only, RA stops advertising DNS), argon-02 kept as a cold
fallback through a 7-day soak then both Pis retired, DoH forwarding
(Cloudflare + Quad9), and a new secondary stack on pve-tiny rather than
re-homing the live primary's Terraform state first. No Pi-hole config is
carried over (operator, 2026-09-29) — Technitium gets its own blocklists.
Everything, zones included, syncs through Technitium clustering; Phase 1
makes the repo's zone automation compatible with that (operator,
2026-09-29).

Found while planning (live, 2026-09-29): **argon-01 answers ping but not
DNS**, and the MikroTik already hands out only `192.168.1.23` — so the
LAN currently has a single working resolver. The dhcp-refactor cutover
packet's recorded DNS option (`192.168.1.22`) is stale for the same
reason; `lan-dns-16` fixes that.

## Phases

| Phase | What | Client impact |
|---|---|---|
| 1 | Make zone automation cluster-compatible: shared `technitium_zone` role, cluster-aware NS/SOA handling in `deploy-technitium-stack.yml`, zone-adoption playbook (`lan-dns-02`–`05`) | none (behavior-neutral while standalone) |
| 2 | Primary becomes a LAN-grade resolver: DoH, Hagezi Pro + TIF-mini blocklists, router forwarders, query-log app; one `provision.sh` run also validates Phase 1 (`lan-dns-06`–`08`) | none (no LAN client uses it yet; SDN subnets bypass blocking) |
| 3 | `technitium-tiny-stack` on pve-tiny, cluster formed, all zones adopted into the cluster catalog, failover drill (`lan-dns-09`–`12`) | none |
| 4 | MikroTik DHCP hands out both Technitium nodes; 7-day soak (`lan-dns-13`–`14`) | **cutover** — one-command rollback |
| 5 | Retire the Pis (`lan-dns-15`) | none after soak |
| 6 | DHCP to Technitium — existing dhcp-refactor Stage E/F, decoupled by `lan-dns-16` | separate window |

Steps with no dependency on each other (e.g. `lan-dns-09` and
`lan-dns-16`) can run in any order; `depends_on` in each step is
authoritative.

## Files

- [plan.md](./plan.md) — decisions, research, and the step blocks
  (`docs/agent-design/step-packet-schema.md` shape)
- `artifacts/` — gitignored scratch, not created yet

## Hand-back log

Each executed step appends an entry here: step id, date, the edit made,
each gate's actual result.

_No steps executed yet._
