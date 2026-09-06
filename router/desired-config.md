# hAP ax3 Configuration

**This is the live, current router configuration**, not a future target —
the hAP ac → hAP ax3 migration this document originally planned is complete.
The VLAN addressing, hardware identity, RouterOS version, DHCP, DNS, and
firewall/WiFi run-state below were all confirmed directly against the
running device on 2026-07-03 via a working REST scrape (see
[README.md](./README.md)'s "Verified Live State" and "Re-scraping" sections).
The firewall rule *contents* (as opposed to counts) and WiFi security-profile
details were not independently re-diffed line-by-line in this pass.

---

## Hardware

| Field | Value |
|-------|-------|
| Model | MikroTik hAP ax3 (RBD53G-5HacD2HnD+TC) |
| RouterOS | 7.23.1 stable (confirmed live 2026-07-03; was 7.22.2 at authoring) |
| Timezone | Pacific/Auckland (UTC+12/+13 DST) |
| 2.5G port | ether1 → bridgeLocal (switch uplink) |
| 1G ports | ether2 = WAN, ether3/4/5 = bridgeLocal |

---

## Bridge & VLANs

**Bridge:** `bridgeLocal`
Members: ether1, ether3, ether4, ether5, wifi1, wifi2

| Interface | VLAN ID | Purpose |
|-----------|---------|---------|
| vlan1-wan | 10 | WAN uplink — tagged on ether2, DHCP client |
| vlan10-build | 10 | build_seg gateway (192.168.10.1/24) |
| vlan20-mgmt | 20 | mgmt_seg gateway (192.168.20.1/24) |
| vlan30-edge | 30 | edge_seg gateway (192.168.30.1/24) |
| vlan40-infra | 40 | infra_seg gateway (192.168.40.1/24) |

---

## IP Addresses

| Interface | Address | Notes |
|-----------|---------|-------|
| bridgeLocal | 192.168.1.1/24 | LAN gateway |
| bridgeLocal | 192.168.1.251/24 | Management (permanent, kept for API access) |
| vlan1-wan | ISP-assigned | DHCP client, add-default-route=yes, use-peer-dns=no |
| vlan10-build | 192.168.10.1/24 | |
| vlan20-mgmt | 192.168.20.1/24 | |
| vlan30-edge | 192.168.30.1/24 | |
| vlan40-infra | 192.168.40.1/24 | |
| bridgeLocal | 2404:440c:234f:f00::/64 | IPv6 LAN — from-pool, advertise=yes |

---

## WAN

- **IPv4:** DHCP client on `vlan1-wan` (VLAN 10 tagged on ether2)
- **IPv6:** DHCPv6-PD client on `vlan1-wan`, requests address+prefix, pool-name=default-pool, pool-prefix-length=64
- **IPv6 pool:** `default-pool` — delegates /64s from the ISP-assigned /56

---

## DNS

- **Upstream:** DoH via `https://dns.google/dns-query`
- **Fallback servers:** 8.8.8.8, 8.8.4.4
- **Allow remote requests:** yes (router acts as local resolver on 192.168.1.1)
- **Verify DoH cert:** no
- **Static entries:** 72 host entries (was 80 when copied from the hAP ac —
  some dropped during or after migration)
- **DHCP hands out:** 192.168.1.22, 192.168.1.23 (Pi-holes) ✅
- **ULA address on router:** fd00::1/64 on bridgeLocal (stable IPv6 for DNS)

---

## DHCP

**Server:** `lan` on bridgeLocal, lease-time=30m (was documented as 10m —
corrected against live scrape)
**Pool:** `dhcp_pool0` (192.168.1.100–192.168.1.200)
**Network:** 192.168.1.0/24, gateway=192.168.1.1
**Leases:** 13 total (5 static, 8 dynamic) as of 2026-07-03

### Static Leases

| Hostname | MAC | Address | Notes |
|----------|-----|---------|-------|
| argon-01 | E4:5F:01:0A:56:E1 | 192.168.1.22 | Pi-hole primary |
| argon-02 | E4:5F:01:F4:A4:88 | 192.168.1.23 | Pi-hole secondary |
| garuda | 10:7C:61:B6:A4:91 | 192.168.1.104 | Workstation |
| RBR350 | 34:98:B5:9D:56:0D | 192.168.1.110 | |
| *(unlabeled)* | 88:A2:9E:57:E6:24 | 192.168.1.28 | Found in live scrape 2026-07-03 — no hostname/comment set on the router; identify this device and label it on the router and here |

---

## IPv6

- **DHCPv6-PD:** client on vlan1-wan, requests address+prefix from ISP (~10 min lease)
- **LAN prefix:** first /64 from delegated /56, assigned to bridgeLocal via `from-pool`
- **ND (bridgeLocal):** M=yes, O=yes, hop-limit=64, advertise-dns=yes
- **RA DNS:** `fd00::22, fd00::23` (Pi-holes via ULA — stable across ISP prefix changes)
- **DHCPv6 server:** `LANIPv6DHCP` on bridgeLocal, address-pool=static-only, prefix-pool=default-pool
- **IPv6 firewall:** 14 rules — allow established/ICMPv6, allow LAN→WAN, drop WAN→LAN, drop invalid, 6 kid-curfew drop rules (MAC-based)

### ULA addresses

| Host | ULA address | Purpose |
|------|-------------|---------|
| router (bridgeLocal) | fd00::1/64 | IPv6 DNS resolver endpoint |
| argon-01 | fd00::22/64 | Pi-hole primary IPv6 DNS |
| argon-02 | fd00::23/64 | Pi-hole secondary IPv6 DNS |

Pi-holes configured as upstream: 2001:4860:4860::8888, 2001:4860:4860::8844 (Google IPv6 DoH not available, plain DNS used)

---

## WiFi

Both interfaces are members of bridgeLocal, issue DHCP, and provide internet access.

| Interface | Radio | SSID | Band | Width | Channel | Country | Security | FT | Status |
|-----------|-------|------|------|-------|---------|---------|----------|----|--------|
| wifi1 | 5GHz-ax | T5 | 5ghz-ax | 20/40/80MHz | auto | New Zealand | wpa2-psk + wpa3-psk | disabled | ✅ Running |
| wifi2 | 2.4GHz-ax | T2 | 2ghz-ax | 20/40MHz | auto | New Zealand | wpa2-psk + wpa3-psk | enabled | ✅ Running |

**Password (both):** frackalicious
**skip-dfs-channels:** 10min-cac (both)

### Security profile / config objects

| Object | Name | Notes |
|--------|------|-------|
| wifi configuration | `wifi_base` | base config (was `home`) |
| wifi security | `t5_secure` | used by wifi1 (was `t5_wpa2_test`) |
| wifi configuration | `t5` | removed |

> **Important:** wifi1 passphrase and security settings are applied **directly on the interface**,
> not inherited from the shared profile. Do not consolidate into a shared profile until wifi1 has
> survived a reboot and normal client reconnects. The root cause of the earlier outage was
> inconsistent security profile state on wifi1 caused by API-driven blank-SSID/inactive-state
> manipulation.

---

## Firewall

### IPv4 forward chain

| # | Action | Rule |
|---|--------|------|
| 1 | accept | established/related |
| 2 | drop | invalid |
| 3–8 | drop | kid-curfew pc/iphone/nih pm+am (MAC, in=bridgeLocal out=vlan1-wan, time-gated) |
| 9 | accept | LAN→WAN (in=bridgeLocal out=vlan1-wan) |
| 10 | drop | WAN→LAN (in=vlan1-wan out=bridgeLocal) |

Plus NAT: masquerade on vlan1-wan.

### IPv6 forward chain

Mirrors IPv4 forward chain exactly:

| # | Action | Rule |
|---|--------|------|
| 1 | accept | established/related |
| 2 | drop | invalid |
| 3–8 | drop | kid-curfew pc/iphone/nih pm+am (MAC, in=bridgeLocal out=vlan1-wan, time-gated) |
| 9 | accept | LAN→WAN (in=bridgeLocal out=vlan1-wan) |
| 10 | drop | WAN→LAN (in=vlan1-wan out=bridgeLocal) |

---

## Services

| Service | Port | State |
|---------|------|-------|
| www (HTTP) | 80 | disabled |
| www-ssl (HTTPS) | 443 | enabled |
| ssh | 22 | enabled |
| api-ssl | 8729 | enabled |
| winbox | 8291 | enabled |
| api (plain) | 8728 | disabled |

**Certificate:** self-signed CA + server cert, assigned to www-ssl.

---

## Outstanding Issues

1. **wifi1 stability** — likely resolved: live scrape (2026-07-03) shows
   both `wifi1` and `wifi2` running with the router at ~3 weeks uptime, so
   T5 has survived at least one long run without a security-profile
   consolidation. Still hasn't been through an explicit, deliberate reboot
   test — do that before finally consolidating into the shared profile.
2. **IPv6 pool short lease (~10 min)** — ISP behaviour, not a config issue; prefix appears stable across renewals
3. **Unlabeled static DHCP lease** (`192.168.1.28`, MAC `88:A2:9E:57:E6:24`)
   — found in the 2026-07-03 scrape, not in the static-leases table above
   until now. Identify the device and add a hostname/comment on the router.
