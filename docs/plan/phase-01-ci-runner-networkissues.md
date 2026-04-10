# Phase 01 — Identified Problems and Proposed Resolutions

## Problem 1 — SDN Simple zones provide no egress

### Symptom

Containers placed in `build_seg` (and any other SDN-backed zone) cannot ping external addresses, cannot reach their configured gateway, and cannot resolve DNS. The LXC starts, is reachable via `pct exec` from the Proxmox host, but has no outbound connectivity.

### Root cause

`pve-test.yaml` maps `build_seg` → attachment `seg_c` → SDN zone `tvsegc` / VNet `tvnetc`, with `zone_type: simple`.

A Proxmox SDN Simple zone creates an isolated Layer 2 broadcast domain with a virtual bridge on the Proxmox node, but the bridge has **no IP address, no routing, and no NAT**. It is designed for east-west microsegmentation between guests, not for containers requiring north-south internet access.

`ci-runner-01/stack.yaml` instructs the LXC to configure itself with:

```
ip_address: 10.57.0.63/24
gateway:    10.57.0.1
```

Nothing is serving `10.57.0.1`. All outbound traffic reaches a dead route. The same structural gap exists on `seg_a` (zones `apps_seg`, `infra_seg`) and `seg_b` (zones `media_seg`, `observe_seg`): any container assigned a gateway on those subnets will have the same failure.

### Why validation didn't catch it

`validate-network-layer.yml` tests east-west reachability between containers sharing a VNet using `pct exec` tunnelled through the Proxmox host. It never tests outbound internet access or gateway reachability. The validation suite passes cleanly while the egress gap is entirely invisible.

### Where the plans are silent

Both `docs/plans/GreenField.md` and `docs/plans/NetworkPlanning.md` describe what zones to create and what traffic to allow between them. Neither specifies what provides routing between a segmented zone and the internet. `NetworkPlanning.md` recommends the hybrid model (Option 3) with VLAN-aware bridges as transport, and notes that routing/firewalling is handled by "your router/firewall", which is a physical external concern. That model does not apply to SDN Simple zones, which have no physical uplink by design.

---

## Proposed resolution

### Approach: SDN subnet with gateway and SNAT on the Proxmox node

Proxmox VE 8.x SDN Simple zones support subnets. A subnet entry on a VNet causes Proxmox to:

1. Assign the gateway IP to the VNet bridge interface on the node (makes `10.x.x.1` reachable from the container).
2. Add a MASQUERADE / SNAT rule for the subnet CIDR through the node's LAN interface (provides internet egress without a separate router).

This resolves gateway unreachability and DNS resolution in a single step, using only the existing Proxmox node — no additional VMs, no managed switch VLANs, no BGP.

#### Comparison of alternatives

| Option | Why not preferred |
|---|---|
| Dedicated router LXC per zone | Extra compute per VNet, more to Terraform and maintain, no advantage over native SNAT |
| Change zone type to EVPN | Requires BGP on the node; significant complexity increase; overkill for a test environment |
| VLAN-backed bridge with physical router | Hardware dependency (managed switch + router VLAN config); may not be available on `pve-test` |
| Move containers to `vmbr0` (flat LAN) | Loses the isolation intent entirely; sidesteps the design |

### What would change

**`terraform/lxc/network/pve-test.yaml`**

Add optional `subnet`, `gateway`, and `snat` fields to each SDN attachment that requires egress. Attachments that should remain fully isolated (no egress) leave these fields absent. Example for `seg_c`:

```yaml
seg_c:
  description: Third SDN VNet attachment for artifact flow validation on pve-test
  type: sdn_vnet
  bridge: tvnetc
  firewall: true
  sdn:
    zone: tvsegc
    zone_type: simple
    nodes:
      - pve-test
    vnet: tvnetc
    alias: pve-test network layer 3
    subnet: "10.57.0.0/24"
    gateway: "10.57.0.1"
    snat: true
```

**`terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml`**

Add two tasks after the existing VNet creation block, guarded by `when: network_sdn_subnet is defined`:

1. Read existing subnets for the VNet via `pvesh get /cluster/sdn/vnets/{vnet}/subnets`.
2. Create the subnet when absent via `pvesh create /cluster/sdn/vnets/{vnet}/subnets --subnet ... --gateway ... --snat 1`.

The existing `pvesh set /cluster/sdn` call at the end of the playbook picks up the subnet change automatically — no additional apply step is needed.

**DNS**

No change required at this stage. Once SNAT is in place the container's existing resolver configuration (`/etc/resolv.conf`, typically pointing at a public resolver) will work correctly. When a `dns-core` zone is introduced in a later phase, containers would switch to an internal resolver.

### Scope

Two YAML files and one playbook extension, all within the existing automation structure. No change to Terraform modules, no new resources, no new stacks.

---

## Related context

- `terraform/lxc/network/pve-test.yaml` — SDN zone/VNet/attachment definitions
- `terraform/lxc/stacks/ci-runner-01/stack.yaml` — LXC spec with `network.zone: build_seg`
- `terraform/lxc/main.tf` — resolves zone → attachment → bridge and emits `network-sdn-vars.yml`
- `terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml` — creates zone and VNet; does not currently create subnets
- `terraform/lxc/ansible/playbooks/validate-network-layer.yml` — east-west validation only; does not test egress
- `docs/plans/GreenField.md` — zone design and platform intent
- `docs/plans/NetworkPlanning.md` — zone model, routing discussion, and option analysis

---

## Teardown and redeploy findings

### Problem 2 — SDN destroy failed because subnets were left behind

#### Symptom

The first destroy attempt for `ci-runner-01` failed while removing the SDN VNet.

Observed failure:

- `vnet: Can't delete vnet if subnets exists`

#### Root cause

The destroy playbook deleted the VNet before removing the subnet entry attached to that VNet. Proxmox refuses to delete a VNet while subnets still exist underneath it.

#### Fix

- Updated [`terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml`](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml) to delete subnets first
- Applied pending SDN changes after the subnet deletion so the destroy path could complete cleanly

### Problem 3 — Fresh redeploys could not SSH into the recreated container directly

#### Symptom

After a clean destroy, the recreated LXC came back, but the runner provisioning step failed during SSH-based Ansible execution.

Observed failures:

- `ssh: connect to host 10.57.0.63 port 22: No route to host`
- `timed out waiting for ping module test`

#### Root cause

The container network is intentionally segmented behind `pve-test`, so the workstation cannot SSH straight to `10.57.0.63`. The inventory template was trying to connect directly instead of jumping through the Proxmox host. On top of that, the deploy playbook was gathering facts before the guest had become reachable.

#### Fix

- Updated [`terraform/lxc/templates/inventory.tpl`](/home/steve/git/proxmox-homelab/terraform/lxc/templates/inventory.tpl) to use `ProxyJump=root@pve-test.gibbsgreatly.xyz`
- Added `wait_for_connection` and deferred fact gathering in [`terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/deploy-ci-runner.yml)

### Problem 4 — Runner registration still needs an explicit token

#### Symptom

The redeploy got through container creation and SSH setup, but the runner registration step failed with:

- `'runner_registration_token' is undefined`

#### Root cause

The playbook expects a GitHub Actions registration token, but the Terraform/Terragrunt flow does not currently generate or pass one automatically.

#### Fix status

- Not fixed in the teardown/redeploy test
- The issue is now isolated to runner bootstrap data plumbing rather than networking
