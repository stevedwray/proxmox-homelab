# Router Configuration

MikroTik management — scraping the current router config and provisioning the replacement.

## Hardware

| Role | Model | ROS Version | Notes |
|------|-------|-------------|-------|
| Current (active) | hAP ac | 7.21.2 | MIPS, 128 MB RAM |
| Replacement | hAP ax3 | 7.x | WiFi 6, more powerful CPU |

## Directory Layout

```
router/
├── config/
│   └── current-config.json   # Full config scraped from active router
├── scripts/
│   └── scrape-config.sh      # REST API scraper
└── README.md
```

## Current Config Summary

Scraped from `192.168.1.1` via REST API (`api-user`).

### Network Topology

WAN is DHCP on `vlan1-wan` (VLAN ID 10, tagged on `ether1`). LAN ports are bridged into `bridgeLocal`; VLANs are sub-interfaces on the bridge.

| VLAN | ID | Subnet | Gateway | Purpose |
|------|----|--------|---------|---------|
| vlan1-wan | 10 | ISP-assigned | — | WAN uplink (ether1, DHCP) |
| vlan10-build | 10 | 10.57.0.0/24 | 10.57.0.1 | build_seg |
| vlan20-mgmt | 20 | 10.57.1.0/24 | 10.57.1.1 | mgmt_seg |
| vlan30-edge | 30 | 10.57.2.0/24 | 10.57.2.1 | edge_seg |
| vlan40-infra | 40 | 10.57.3.0/24 | 10.57.3.1 | infra_seg |

### DNS

- Upstream: DoH via `https://dns.google/dns-query`
- Local resolver enabled (`allow-remote-requests = true`)
- 80 static host entries

### DHCP

- 1 server, 1 network, 13 active leases

### Firewall

- 30 filter rules, 3 NAT rules, 0 mangle rules

## Provisioning the hAP ax3

### Credentials

Stored in SOPS at `terraform/secrets.enc.yaml`. Decrypt with:

```bash
eval "$(sops -d terraform/secrets.enc.yaml | grep ^MIKROTIK | sed 's/: /=/;s/^/export /')"
```

### Re-scraping

```bash
MIKROTIK_USER=api-user \
MIKROTIK_PASSWORD=<from SOPS> \
./router/scripts/scrape-config.sh [host]
```

### Migration Plan

1. Flash hAP ax3 to latest stable ROS 7.x (or verify it matches current version)
2. Apply base config: identity, services, users
3. Configure WAN: `ether1` with VLAN 10 tag, DHCP client
4. Build bridge + VLAN sub-interfaces matching current layout
5. Apply IP addresses and static routes
6. Apply firewall rules (filter + NAT)
7. Configure DNS (DoH upstream + 80 static entries)
8. Configure DHCP server + network + static leases
9. Configure WiFi (2.4 GHz / 5 GHz / 6 GHz) — not on current router, add fresh

All source data for steps 2–8 is in `config/current-config.json`.
