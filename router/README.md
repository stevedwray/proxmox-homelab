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
│   └── current-config.json   # Live hAP ax3 scrape, 2026-07-03 (see "Re-scraping")
├── scripts/
│   └── scrape-config.sh      # REST API scraper
└── README.md
```

## Verified Live State (2026-07-03, fully re-scraped)

The REST API scraper is **now fixed and confirmed working** (see
"Re-scraping" below) — `config/current-config.json` is a real, current
automated scrape of the live hAP ax3, not the manual-CLI spot check this
section originally recorded. Every figure below is from that fresh scrape.

- Router is the **hAP ax3** (`board-name: hAP ax^3`), RouterOS `7.23.1
  (stable)`, ARM64, 4 cores, 1024 MiB RAM, uptime ~3 weeks at scrape time
  (consistent with the ax3 cutover landing around the last prior `router/`
  commit, 2026-06-12).
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

- DHCP: 1 server (`lan` on `bridgeLocal`), lease-time **30m** (not the 10m
  `desired-config.md` documented), pool `192.168.1.100–192.168.1.200`, 13
  total leases (5 static, 8 dynamic) — one static lease (`192.168.1.28`,
  MAC `88:A2:9E:57:E6:24`) has **no hostname/comment set on the router** and
  isn't in `desired-config.md`'s static-lease table; identify and label it.
- DNS: 72 static host entries (was 80 at last hAP ac scrape — some were
  dropped in the migration or since).
- Firewall: 29 filter rules, 1 NAT rule (masquerade), 0 mangle rules.
- WiFi: both `wifi1` (`t5_secure`) and `wifi2` (`secure_profile`) are
  `running=true`, `disabled=false` — consistent with the ~3 week uptime, so
  the "wifi1 stability across reboot" open question in `desired-config.md`
  looks resolved in practice, though it hasn't been through an explicit
  reboot test.

## Pre-Migration Snapshot (hAP ac, retired)

Scraped from the **hAP ac** (now retired) at `192.168.1.1` via REST API
(`api-user`), 2026-04-25. Kept for historical reference only — do not treat
as current. This snapshot has been superseded in `config/current-config.json`
by the 2026-07-03 live ax3 scrape (see "Verified Live State" above); it's
preserved here in prose only, and in git history for the file itself.

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

Two separate bugs, now both fixed:

1. **`scrape-config.sh` had an auth bug**, independent of any credential
   issue: it built `AUTH="-u ${USER}:${PASS}"` and passed it to curl as a
   single quoted argument (`"${AUTH}"`), which curl does not word-split —
   so Basic auth was never actually applied, every field silently fell back
   to `null`, and the script produced an all-null "scrape" that looked like
   a working run. Fixed by passing `-u "${USER}:${PASS}"` directly.
2. **The documented `api-user` credential was broken as of 2026-07-03
   (401 Unauthorized in all three SOPS files), but is working again as of a
   follow-up check the same day** — confirmed `HTTP 200` against
   `/rest/system/identity` with the `secrets.enc.yaml` copy. Root cause of
   the original 401 (rotated on-device vs. never valid) was never
   identified, so if it recurs, don't assume it's the same bug fixed in
   item 1 above — check auth separately from the script. Other working
   accounts, useful if `api-user` ever regresses:
   `MIKROTIK_ADMIN`/`MIKROTIK_ADMIN_PASSWORD` (`dns-user`, full admin, in
   all three files) and `MIKROTIK_READONLY_USER`/`MIKROTIK_READONLY_PASSWORD`
   (`api-ro`, **only** in `secrets.pve.enc.yaml`) — note `api-ro`
   authenticates but its API policy doesn't grant read access to most
   `/rest` endpoints tested here (returned HTTP 200 with an empty body).

```bash
eval "$(sops -d terraform/secrets.enc.yaml | grep -E '^MIKROTIK_(USER|PASSWORD):' | sed 's/: /=/;s/^/export /')"
./router/scripts/scrape-config.sh 192.168.1.1
```

`config/current-config.json` is now a fresh scrape taken this way on
2026-07-03 — real data, not the stale hAP ac snapshot. Diff future re-scrapes
with `git diff` before committing.

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
