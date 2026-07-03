# Router Configuration

MikroTik management. **The hAP ac → hAP ax3 migration described below is
complete** — the ax3 is the live router. See "Verified Live State" for what's
been confirmed directly against the device, and "Pre-Migration Snapshot" for
the (now historical) hAP ac config this repo originally migrated from.

## Hardware

| Role | Model | ROS Version | Notes |
|------|-------|-------------|-------|
| Current (active) | hAP ax3 | 7.23.1 | ARM64, 4 cores, 1024 MB RAM, WiFi 6 — confirmed live 2026-07-03 |
| Previous (retired) | hAP ac | 7.21.2 | MIPS, 128 MB RAM |

## Directory Layout

```
router/
├── config/
│   └── current-config.json   # Scraped from the hAP ac, 2026-04-25 — STALE, predates the ax3 migration
├── scripts/
│   └── scrape-config.sh      # REST API scraper
└── README.md
```

## Verified Live State (2026-07-03)

Confirmed by running RouterOS CLI commands directly on the router (`/ip
address print`, `/interface vlan print`, `/system resource print`) — the
REST API scraper currently fails with `401 Unauthorized` (see "Re-scraping"
below), so this was a manual verification, not an automated re-scrape.

- Router is the **hAP ax3** (`board-name: hAP ax^3`), RouterOS `7.23.1
  (stable)`, ARM64, 4 cores, 1024 MiB RAM.
- WAN (`vlan1-wan`, VLAN ID 10) is tagged on **`ether2`**, not `ether1` —
  matches [desired-config.md](./desired-config.md)'s port table, not the
  pre-migration summary below.
- VLAN gateways match the current repo-wide addressing scheme (see
  `docs/design/network.md`), **not** the legacy `10.57.x.x` scheme:

  | VLAN | ID | Interface | Gateway |
  |------|----|-----------|---------|
  | vlan10-build | 10 | bridgeLocal | `192.168.10.1/24` |
  | vlan20-mgmt | 20 | bridgeLocal | `192.168.20.1/24` |
  | vlan30-edge | 30 | bridgeLocal | `192.168.30.1/24` |
  | vlan40-infra | 40 | bridgeLocal | `192.168.40.1/24` |

**Not independently re-verified** against the live ax3: DNS static entries,
DHCP leases, firewall rule counts, WiFi config. The figures in "Pre-Migration
Snapshot" below are from the retired hAP ac and should not be trusted for the
live device until a fresh REST scrape succeeds.

## Pre-Migration Snapshot (hAP ac, retired)

Scraped from the **hAP ac** (now retired) at `192.168.1.1` via REST API
(`api-user`), 2026-04-25. Kept for historical reference only — do not treat
as current. `config/current-config.json` is this same stale scrape.

### Network Topology

WAN was DHCP on `vlan1-wan` (VLAN ID 10, tagged on `ether1` on the hAP ac).
LAN ports were bridged into `bridgeLocal`; VLANs were sub-interfaces on the
bridge. VLAN gateway addresses shown here are the **legacy `10.57.x.x`
scheme** the hAP ac was running at scrape time — see "Verified Live State"
above for the current addresses.

| VLAN | ID | Subnet (at scrape time) | Purpose |
|------|----|--------------------------|---------|
| vlan1-wan | 10 | ISP-assigned | WAN uplink (`ether1` on hAP ac, DHCP) |
| vlan10-build | 10 | `10.57.0.0/24` | build_seg |
| vlan20-mgmt | 20 | `10.57.1.0/24` | mgmt_seg |
| vlan30-edge | 30 | `10.57.2.0/24` | edge_seg |
| vlan40-infra | 40 | `10.57.3.0/24` | infra_seg |

### DNS

- Upstream: DoH via `https://dns.google/dns-query`
- Local resolver enabled (`allow-remote-requests = true`)
- 80 static host entries

### DHCP

- 1 server, 1 network, 13 active leases

### Firewall

- 30 filter rules, 3 NAT rules, 0 mangle rules

## Provisioning the hAP ax3 (historical — already completed)

### Credentials

Stored in SOPS at `terraform/secrets.enc.yaml`. Decrypt with:

```bash
eval "$(sops -d terraform/secrets.enc.yaml | grep ^MIKROTIK | sed 's/: /=/;s/^/export /')"
```

### Re-scraping

**Currently broken:** as of 2026-07-03, the `api-user` credential in SOPS
returns `401 Unauthorized` against the live router's REST API. Either the
password was rotated on the router without updating
`terraform/secrets.enc.yaml`, or the account changed. Fix the credential
before trusting this command — see "Verified Live State" above for how the
VLAN addressing was confirmed in the meantime (direct RouterOS CLI).

```bash
MIKROTIK_USER=api-user \
MIKROTIK_PASSWORD=<from SOPS> \
./router/scripts/scrape-config.sh [host]
```

Once the credential is fixed, re-running this against `192.168.1.1` will
overwrite `config/current-config.json` with a fresh, accurate scrape of the
live hAP ax3 — diff it with `git diff` before committing, and update the
"Pre-Migration Snapshot" section above to a "Current" section once confirmed.

### Migration Plan (completed)

The hAP ac → hAP ax3 migration described here has already happened — kept
for historical reference on how it was done.

1. Flash hAP ax3 to latest stable ROS 7.x (or verify it matches current version)
2. Apply base config: identity, services, users
3. Configure WAN: `ether2` with VLAN 10 tag, DHCP client
4. Build bridge + VLAN sub-interfaces matching current layout
5. Apply IP addresses and static routes
6. Apply firewall rules (filter + NAT)
7. Configure DNS (DoH upstream + 80 static entries)
8. Configure DHCP server + network + static leases
9. Configure WiFi (2.4 GHz / 5 GHz / 6 GHz) — not on the retired hAP ac, added fresh

All source data for steps 2–8 is in `config/current-config.json`.
