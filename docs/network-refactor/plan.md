# Network Refactor Plan

## Problem Statement

The preserved productionizing checkpoint uncovered a provisioning assumption
that does not match the intended platform design:

1. `terraform/lxc/templates/inventory.tpl` emits `ProxyJump=root@${pve_host}`
   for stack provisioning.
2. SDN-backed guests therefore depend on the Proxmox host having direct
   host-side reachability into guest subnets.
3. `terraform/lxc/main.tf` compensates with `null_resource.prime_sdn_host_route`
   to add a host bridge IP and route dynamically.
4. The intended network model is that inter-VLAN/subnet routing belongs to the
   main router, not to Proxmox acting as the default jump host or gateway.

## Preserved Evidence

The previous branch established:

1. production env, storage, and network manifests can be modeled cleanly
2. `apt-cacher-stack` on `pve` can render and partially bootstrap
3. production SDN object creation for `tvinfra` is now possible
4. `pve-test` live inspection shows inconsistent host-side SDN reachability:
   - `tvmgmt` has a host-side IP/route
   - `tvinfra` guests exist but the host does not currently route to them in
     the expected way

Reference:

- [checkpoint.md](/home/steve/git/proxmox-homelab/docs/network-refactor/checkpoint.md:1)

## Refactor Goals

1. Make the intended routed network model explicit for `pve-test` and `pve`.
2. Decide the correct provisioning access model for SDN-backed guests.
3. Remove accidental dependence on Proxmox as a general-purpose jump host if
   that is not the intended design.
4. Prove the corrected model with teardown/redeploy validation before resuming
   production canary work.

## Key Questions

1. Which systems are meant to have L3 reachability into:
   - `build_seg`
   - `mgmt_seg`
   - `edge_seg`
   - `infra_seg`
2. Is the operator workstation expected to reach these subnets directly via the
   main router?
3. If not direct, what is the intentional administrative access path?
4. Are Proxmox hosts expected to have subnet-local bridge IPs for any of these
   SDN networks, and if so, which ones and why?
5. Should Terraform/Ansible provisioning connect:
   - directly to guest IPs
   - through a router-accessible path
   - through a bastion that is not the Proxmox host

## Workstreams

### 1. Design Clarification

Document the intended L2/L3 model for:

1. router VLAN interfaces and gateways
2. Proxmox bridge/VNet responsibilities
3. host management reachability
4. operator/admin workstation reachability
5. provisioning access path for stack automation

### 2. Implementation Inventory

Map the current live and repo behavior:

1. generated Ansible inventory and `ProxyJump` usage
2. `prime_sdn_host_route` behavior
3. current SDN zone/VNet creation path
4. live `pve-test` routing/interface state
5. any manual router/proxmox configuration that the repo currently assumes

### 3. Refactor Plan

Define the exact code/doc changes needed, likely including:

1. inventory generation changes
2. Terraform/Ansible provisioning path changes
3. SDN host-route logic removal or narrowing
4. any required router-side documentation or automation
5. validation updates for both `pve-test` and future `pve`

### 4. Validation Plan

This refactor must include at least one teardown/redeploy validation cycle on
`pve-test`.

Minimum validation should cover:

1. SDN zone/VNet creation and guest attachment
2. provisioning reachability to SDN-backed guests without unintended
   Proxmox-host routing hacks
3. representative stack deploys after teardown:
   - `apt-cacher-stack`
   - one `mgmt_seg` stack
   - one additional SDN-backed stack if needed

## Initial Deliverables

1. This planning directory.
2. A clarified branch/workflow model in `AGENTS.md`.
3. Detailed task docs to be added next:
   - scope and assumptions
   - target network model
   - implementation plan
   - teardown validation gate
4. A session-ready handoff:
   - [handoff.md](/home/steve/git/proxmox-homelab/docs/network-refactor/handoff.md:1)

## Non-Goals

For the initial planning phase, do not:

1. resume production canary apply work
2. merge preserved `refactor/productionize` work into a promotion branch
3. normalize `prime_sdn_host_route` as the accepted final design without a
   deliberate architecture decision
