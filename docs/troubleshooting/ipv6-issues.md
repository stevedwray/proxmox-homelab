# IPv6 Setup and Fix Summary (Proxmox + MikroTik)

## Overview
This document records the issues discovered with IPv6 connectivity in the Proxmox homelab environment and the solutions that were applied.
It is intended as a reference for future troubleshooting and to ensure consistent configuration across hosts and containers.

---

## Problems Identified

### 1. Duplicate / Conflicting Prefixes
- The MikroTik router was advertising **two IPv6 prefixes** on the LAN:
  - `2404:440c:1357:2a00::/64` (static, not routed upstream)
  - `2404:440c:234e:5900::/64` (dynamic, valid and routed)
- Proxmox hosts and containers auto-configured addresses from both prefixes.
- Packets sourced from the invalid `…:2a00::/64` never received replies, causing broken IPv6 connectivity.

### 2. Proxmox Host Configuration
- `/etc/network/interfaces` only contained IPv4 static config.
- IPv6 was left to kernel defaults:
  - Router Advertisements (RA) were not always accepted.
  - Packet loss occurred with larger payloads due to **PMTU black-holing** on the upstream path.

### 3. LXC Container Networking
- Containers were configured with **IPv6 = Static** in Proxmox UI.
- They did not accept Router Advertisements and failed to acquire:
  - Global IPv6 addresses
  - Default IPv6 route
  - Upstream DNS servers
- Result: Containers had no usable IPv6 connectivity.

---

## Solutions Applied

### MikroTik Router
- Disabled and removed the static `2404:440c:1357:2a00::/64` prefix.
- Left only the **valid routed prefix** `2404:440c:234e:5900::/64` advertised via ND.
- Ensured RA continued to provide default gateway and recursive DNS servers.

### Proxmox Host
- Updated `/etc/network/interfaces` for bridge `vmbr0`:
  ```ini
  auto vmbr0
  iface vmbr0 inet static
      address 192.168.1.9/24
      gateway 192.168.1.1
      bridge-ports ens33
      bridge-stp off
      bridge-fd 0
      mtu 1480

  iface vmbr0 inet6 auto
      accept_ra 2
