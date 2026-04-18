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

## DNS standard for SDN-attached LXCs

For every SDN-attached LXC, the expected resolver is the MikroTik interface for that
zone:

| Zone | Resolver target |
|---|---|
| `build_seg` | `10.57.0.1` |
| `mgmt_seg` | `10.57.1.1` |
| `edge_seg` | `10.57.2.1` |
| `infra_seg` | `10.57.3.1` |

This is the intended platform contract. Public resolvers such as `1.1.1.1` are not the
target architecture for normal LXC operation.

Resolver entry point and record authority are separate concerns. Zone clients use the
MikroTik zone gateway IP as first-hop resolver. Specific internal zones can be delegated
behind that resolver. For shared platform services, `lab.gibbsgreatly.xyz` is delegated
to a dedicated internal DNS server while clients continue querying MikroTik.

### 2026-04-16 runner recovery note

During the greenfield `ci-runner-01` recovery, `build_seg` was missing its MikroTik VLAN
interface initially, and router-local DNS on `10.57.0.1` did not answer during runner
bootstrap even after the VLAN and gateway were added. A temporary `dns_server: "1.1.1.1"`
override was used to recover the runner.

That workaround is documented so future tasks understand the incident, but it should not
be copied forward as the default pattern. If a new stack needs public DNS to come up, the
platform DNS path is still broken and should be fixed before treating the stack as done.

### Where DNS fixes belong

Template rebuilds are useful when a common package set or baseline filesystem content must
change for all future LXCs. They are not sufficient by themselves to guarantee runtime DNS
because Proxmox can rewrite `/etc/resolv.conf` during container boot.

For DNS behavior that must survive create, stop, and reboot cycles, fix the platform layer:

- ensure the MikroTik VLAN interface and DNS service are reachable for the zone
- ensure Proxmox/Terraform container initialization writes the intended resolver
- use per-container playbook workarounds only as temporary recovery steps

### Future automation note

The current DNS validator is intentionally black-box from the guest side: it confirms
that a stack is configured with the expected `dns_server` and that the resolver answers
queries from inside the LXC. The next maturity step is to add RouterOS-aware validation
through the MikroTik API so the platform can also prove, before or alongside stack
deployment, that:

- the expected VLAN interface exists for the zone
- the expected gateway IP is bound to that interface
- MikroTik DNS service is enabled for remote requests
- the router is actually answering DNS on the zone-local gateway IP

When that work is taken on, keep the guest-side validator as the final end-to-end proof.
Router API checks should supplement the platform contract, not replace runtime validation
from inside the LXC.

### Internal zone delegation model (`lab.gibbsgreatly.xyz`)

* Client behavior remains unchanged: query MikroTik zone gateway resolver.
* MikroTik forwards only `lab.gibbsgreatly.xyz` to an internal authoritative DNS server.
* MikroTik may continue serving static records and current recursive behavior for non-delegated names.
* This preserves stable client configuration while enabling platform DNS authority to move into code-managed services.

Automation scope for this delegation model should include:

* validate conditional forwarding exists for `lab.gibbsgreatly.xyz`
* validate delegated authority answers from the configured internal DNS server
* validate all SDN zones can resolve delegated internal names and public probe names through MikroTik
* defer full recursive DoH migration off MikroTik to a later phase

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
creation only. Use `ansible/00-initial-setup/proxmox-sdn-setup.yml` for VLAN
zones until Terraform-side support is updated for `zone_type: vlan`.

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

# Delegated internal zone check via zone resolver
pct exec <vmid> -- dig @10.57.<zone>.1 +short traefik.lab.gibbsgreatly.xyz

# Public probe check via the same resolver path
pct exec <vmid> -- dig @10.57.<zone>.1 +short github.com
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
