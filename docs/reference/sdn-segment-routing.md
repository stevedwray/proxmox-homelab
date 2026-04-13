# SDN Segment Routing Pattern

## Overview

pve-test uses **Proxmox SDN VLAN zones** for network segmentation. Each zone is a
VLAN-tagged sub-bridge; containers attach to a zone and receive an IP in that zone's
subnet. The **MikroTik router** owns all gateway IPs and performs all L3 routing
between zones. Proxmox does not route or NAT — it is a pure L2 switch.

This document describes the VLAN zone model, how routing works, and the pattern for
adding a new segment.

---

## Architecture: MikroTik as L3 gateway

```text
  Workstation (192.168.1.x)
         |
    MikroTik (router/firewall)
    ├── LAN: 192.168.1.1/24       (untagged)
    ├── VLAN 10: 10.57.0.1/24    (build_seg)
    ├── VLAN 20: 10.57.1.1/24    (mgmt_seg)
    ├── VLAN 30: 10.57.2.1/24    (edge_seg)
    └── VLAN 40: 10.57.3.1/24    (infra_seg)
         |
    pve-test (trunk port — all VLANs tagged)
    ├── vmbr0 (VLAN-aware bridge)
    ├── tvnetc   → VLAN 10 → containers in build_seg
    ├── tvmgmt   → VLAN 20 → containers in mgmt_seg
    ├── tvedge   → VLAN 30 → containers in edge_seg
    └── tvinfra  → VLAN 40 → containers in infra_seg
```

Each container uses its zone's MikroTik interface as its default gateway
(e.g. `10.57.3.1` for infra_seg). All routing — including inter-zone traffic,
LAN access, and internet egress — flows through the MikroTik. Proxmox does
not have any gateway IPs and performs no routing or SNAT.

---

## Why VLAN zones, not Simple zones

| | Simple zones | VLAN zones |
|---|---|---|
| L3 gateway | Proxmox host (iptables) | MikroTik (hardware router) |
| SNAT | Proxmox host (double NAT) | MikroTik WAN only (single NAT) |
| LAN → container ingress | Requires static route on router | MikroTik directly connected |
| Inter-zone routing | Requires static routes per zone pair | MikroTik routing table (automatic) |
| Container identity in logs | Masked by Proxmox SNAT | Real container IP preserved |
| MikroTik firewall enforcement | Partial (only at WAN) | Full (all inter-zone traffic) |

With VLAN zones, **no static routes are needed on the MikroTik** — the VLAN
interfaces are directly connected routes. Any host on 192.168.1.0/24 can reach
any container at 10.57.x.x directly via the MikroTik.

---

## Current zone state

| Zone | VNet bridge | VLAN | Subnet | Gateway | Containers |
|---|---|---|---|---|---|
| `build_seg` | `tvnetc` | 10 | `10.57.0.0/24` | `10.57.0.1` | ci-runner-01 (10.57.0.63) |
| `mgmt_seg` | `tvmgmt` | 20 | `10.57.1.0/24` | `10.57.1.1` | Authentik (10.57.1.10), step-ca (10.57.1.11), Monitoring (10.57.1.12) |
| `edge_seg` | `tvedge` | 30 | `10.57.2.0/24` | `10.57.2.1` | Traefik (10.57.2.10) |
| `infra_seg` | `tvinfra` | 40 | `10.57.3.0/24` | `10.57.3.1` | Harbor (10.57.3.10), apt-cacher (10.57.3.11), NetBox (10.57.3.12) |

---

## Pattern: adding a new segment

### Step 1 — Assign VLAN ID and subnet

Choose a VLAN ID and subnet that does not conflict with existing zones. Update
`terraform/lxc/network/pve-test.yaml` with the new attachment:

```yaml
  new_seg:
    description: New zone description
    type: sdn_vnet
    bridge: tvnew
    firewall: false
    sdn:
      zone: tvnew
      zone_type: vlan
      bridge: vmbr0
      nodes:
        - pve-test
      vnet: tvnew
      vlan_tag: 50          # ← new VLAN ID
      alias: pve-test new segment
      subnet: "10.57.4.0/24"
      gateway: "10.57.4.1"
      snat: false           # ← always false — MikroTik handles routing
```

Also add the zone and its containers to the `zones:` block.

### Step 2 — Configure MikroTik (out-of-band, mandatory first)

**This must be done before any container is deployed on the new segment**, so the
new VLAN is routable before the container boots.

In the MikroTik terminal:

```text
/interface vlan add interface=<trunk-iface> name=vlan50-new vlan-id=50
/ip address add address=10.57.4.1/24 interface=vlan50-new comment="pve-test new_seg gw"
```

Verify the new VLAN interface is up and reachable:

```bash
# From the workstation — should respond
ping -c 3 10.57.4.1
```

### Step 3 — Apply SDN zone manually (Terraform code gap)

The `configure-network-sdn-vnet.yml` playbook currently handles Simple zone
creation only. VLAN zones must be created manually with pvesh until the playbook
is updated for `zone_type: vlan`.

```bash
# Create the SDN zone
pvesh create /cluster/sdn/zones --type vlan --zone tvnew --bridge vmbr0 --nodes pve-test

# Create the VNet
pvesh create /cluster/sdn/vnets --vnet tvnew --zone tvnew --tag 50

# Create the subnet
pvesh create /cluster/sdn/vnets/tvnew/subnets --subnet 10.57.4.0/24 --gateway 10.57.4.1 --type subnet

# Apply SDN config
pvesh set /cluster/sdn
```

Verify the zone appears in Proxmox:

```bash
pvesh get /nodes/pve-test/sdn/zones
# Expected: tvnew listed
```

### Step 4 — Deploy and verify

Once the zone is created and a container is deployed:

```bash
# From a workstation — container should be reachable
ping -c 3 10.57.4.<host>

# From pve-test — internet egress via MikroTik
pct exec <vmid> -- ping -c 3 8.8.8.8

# Inter-zone routing — e.g. from a container in build_seg to new_seg
pct exec 141 -- ping -c 3 10.57.4.<host>
```

---

## Cross-zone traffic

All cross-zone traffic flows through the MikroTik. The MikroTik routing table
has directly-connected routes for all VLAN subnets, so no additional static
routes are required. Inter-zone policy is enforced via MikroTik firewall rules.

The Proxmox VNet firewall (`firewall: true` on a zone) controls inbound traffic
to individual containers within a zone, but does NOT enforce cross-zone policies.
There is a known bug in `main.tf:86-95` where cross-zone ACCEPT rules are never
generated — see the code gaps table in `docs/plan/README.md`. The Proxmox
firewall is disabled for dev passes; cross-zone policy is enforced by the
MikroTik firewall only.

---

## No SNAT at Proxmox

`snat: false` must be set on all SDN zones. The MikroTik performs WAN SNAT for
all traffic leaving the home network. Adding a second SNAT layer at Proxmox
would:

- Double NAT all traffic (MikroTik + Proxmox)
- Break LAN → container ingress (source IP becomes pve-test, not the client)
- Mask container IPs in logs

Do not set `snat: true` on any zone in `pve-test.yaml`.

---

## Related

- `terraform/lxc/network/pve-test.yaml` — declarative zone/VNet/subnet intent
- `terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml` — SDN
  provisioner (Simple zones only; VLAN support pending)
- `docs/design/NetworkPlanning.md` — zone design rationale
- `docs/plan/README.md` — Phase 04 bring-up sequence, known code gaps
