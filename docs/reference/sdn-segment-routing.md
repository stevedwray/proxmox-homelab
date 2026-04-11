# SDN Segment Routing Pattern

## Overview

SDN Simple zones on pve-test provide isolated Layer 2 broadcast domains for
microsegmentation validation. When a container in a segmented zone needs:

- Outbound internet access (e.g. package downloads, GitHub API calls)
- Inbound access from the LAN (e.g. workstation → ci-runner)

...the correct model is **routing**, not SNAT/MASQUERADE.

This document describes the pattern, the out-of-band router prerequisite, and
how to apply it when a new segment gains a subnet.

---

## Why routing, not SNAT

| | SNAT | Routing |
|---|---|---|
| Outbound internet | ✅ works | ✅ works |
| LAN → container ingress | ❌ broken (no DNAT rules) | ✅ works natively |
| Container identity in logs | ❌ masked (appears as pve-test IP) | ✅ real container IP |
| NAT hops to internet | 2× (pve-test + home router) | 1× (home router only) |
| Config needed per service | DNAT rule per port | none |

The home router (MikroTik) already SNATs all LAN traffic to the WAN IP. Adding a
second SNAT layer at pve-test provides no benefit and loses source attribution.

IP forwarding is permanently enabled on pve-test (`net.ipv4.ip_forward = 1`). The
SDN VNet bridge interface (`tvnetc`, `tvneta`, etc.) already has the gateway IP when
a subnet is configured via Proxmox SDN. The only missing piece for routing is a
static route on the home router.

---

## Current segment state

| Segment | Attachment | Subnet | Gateway | SNAT | Router route needed |
|---|---|---|---|---|---|
| `seg_c` (`build_seg`, `artifacts_seg`) | `tvnetc` | `10.57.0.0/24` | `10.57.0.1` | `false` | ✅ `10.57.0.0/24 via 192.168.1.40` |
| `seg_a` (`apps_seg`, `infra_seg`) | `tvneta` | — | — | — | not yet (no subnet assigned) |
| `seg_b` (`media_seg`, `observe_seg`) | `tvnetb` | — | — | — | not yet (no subnet assigned) |

`seg_a` and `seg_b` have no subnets yet. When Phase 04 services are assigned to
segmented zones, follow the pattern below.

---

## Pattern: adding egress to a new segment

### Step 1 — Declare the subnet in `pve-test.yaml`

In `terraform/lxc/network/pve-test.yaml`, add `subnet`, `gateway`, and `snat: false`
to the attachment's `sdn` block:

```yaml
  seg_a:
    description: First SDN VNet attachment ...
    type: sdn_vnet
    bridge: tvneta
    firewall: true
    sdn:
      zone: tvsega
      zone_type: simple
      nodes:
        - pve-test
      vnet: tvneta
      alias: pve-test network layer
      subnet: "10.55.0.0/24"    # ← add
      gateway: "10.55.0.1"      # ← add
      snat: false               # ← always false — use routing not SNAT
```

Also update the comment block near the top of `attachments:` with the new route:

```yaml
# Current required routes:
#   10.57.0.0/24 via 192.168.1.40   (seg_c: build_seg / artifacts_seg)
#   10.55.0.0/24 via 192.168.1.40   (seg_a: apps_seg / infra_seg)   ← add
```

### Step 2 — Add static route on the MikroTik (out-of-band, mandatory first)

**This must be done before applying Terraform** so containers retain internet
egress throughout the change. If the route is absent when any existing SNAT rule
is removed, containers lose connectivity.

In the MikroTik terminal:

```
/ip route add dst-address=<subnet> gateway=192.168.1.40 comment="pve-test SDN <seg_name>"
```

Example for `seg_a`:

```
/ip route add dst-address=10.55.0.0/24 gateway=192.168.1.40 comment="pve-test SDN seg_a"
```

Verify before continuing:

```bash
# From the workstation — should resolve via pve-test, not drop
ping -c 3 <gateway-ip>     # e.g. ping -c 3 10.55.0.1

# From pve-test — internet egress test for the segment bridge
ssh root@pve-test.gibbsgreatly.xyz \
  "ip route get 8.8.8.8 from 10.55.0.1"
# Next hop should be 192.168.1.1, not a MASQUERADE chain
```

### Step 3 — Apply via Terraform

Any stack assigned to a zone on the newly configured segment triggers the SDN
apply when `terragrunt apply` runs. The `configure-network-sdn-vnet.yml` playbook
handles both create (new subnet) and update (existing subnet with wrong SNAT) cases
idempotently — no manual `pvesh` commands needed.

```bash
source .env && source .env.pve-test
cd terraform/lxc/stacks/<first-stack-on-new-segment>
terragrunt apply
```

### Step 4 — Verify

```bash
HOST=pve-test.gibbsgreatly.xyz

# 1. SDN subnet SNAT flag
ssh root@${HOST} \
  "pvesh get /cluster/sdn/vnets/<vnet>/subnets --output-format json | python3 -m json.tool"
# snat should be 0

# 2. No iptables MASQUERADE for the segment subnet
ssh root@${HOST} "iptables -t nat -L -n | grep <subnet-prefix>"
# should return nothing

# 3. Container internet egress
ssh root@${HOST} "pct exec <vmid> -- ping -c 3 8.8.8.8"

# 4. LAN → container ingress (from workstation)
ping -c 3 <container-ip>
```

---

## Applying to existing segments with SNAT already on

If a segment is live with `snat: true` and needs to be converted to routing:

1. **Add the router static route first** (Step 2 above).
2. Change `snat: false` in `pve-test.yaml`.
3. Run `terragrunt apply` on any stack using that segment. The playbook's
   `Update SDN subnet when existing egress config differs from desired state`
   task will issue `pvesh set` to flip `snat=0` and call `pvesh set /cluster/sdn`
   to apply.

Do not remove the router static route once added — even if the segment has no
active containers, leaving the route in place is harmless and prevents an outage
if containers are redeployed.

---

## Validation gap

The `validate-network-layer.yml` test suite currently only covers east-west
reachability between containers on the same VNet. It does not test north-south
egress or LAN → container ingress. This is tracked in issue **#80**.

Until that is resolved, verify manually with the checks in Step 4 above after
each new segment is brought up with a subnet.

---

## Related

- `terraform/lxc/network/pve-test.yaml` — declarative segment/subnet/zone intent
- `terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml` — idempotent
  SDN zone/VNet/subnet provisioner; handles create and update
- `docs/plans/NetworkPlanning.md` — hybrid model rationale, zone design
- Issues: #78 (remove SNAT from seg_c), #79 (document router route prerequisite),
  #80 (egress validation in test suite)
