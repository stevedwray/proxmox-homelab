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
re-homing the live primary's Terraform state first.

Found while planning (live, 2026-09-29): **argon-01 answers ping but not
DNS**, and the MikroTik already hands out only `192.168.1.23` — so the
LAN currently has a single working resolver. The dhcp-refactor cutover
packet's recorded DNS option (`192.168.1.22`) is stale for the same
reason; `lan-dns-13` fixes that.

## Phases

| Phase | What | Client impact |
|---|---|---|
| 0 | Export and transcribe the Pi-hole config (`lan-dns-01`) | none |
| 1 | Primary becomes a LAN-grade resolver: DoH, blocklists, router forwarders, query-log app (`lan-dns-02`–`04`) | none (no LAN client uses it yet; SDN subnets bypass blocking) |
| 2 | `technitium-tiny-stack` on pve-tiny, clustered, zones replicated (`lan-dns-05`–`09`) | none |
| 3 | MikroTik DHCP hands out both Technitium nodes; 7-day soak (`lan-dns-10`–`11`) | **cutover** — one-command rollback |
| 4 | Retire the Pis (`lan-dns-12`) | none after soak |
| 5 | DHCP to Technitium — existing dhcp-refactor Stage E/F, decoupled by `lan-dns-13` | separate window |

Steps with no dependency on each other (e.g. `lan-dns-05` and
`lan-dns-13`) can run in any order; `depends_on` in each step is
authoritative.

## Files

- [plan.md](./plan.md) — decisions, research, and the step blocks
  (`docs/agent-design/step-packet-schema.md` shape)
- `pihole-inventory.md` — created by `lan-dns-01`
- `artifacts/` — gitignored; holds the raw Pi-hole export

## Hand-back log

Each executed step appends an entry here: step id, date, the edit made,
each gate's actual result.

_No steps executed yet._
