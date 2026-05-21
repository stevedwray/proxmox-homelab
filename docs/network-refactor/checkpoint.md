# Network Refactor Checkpoint

## Why This Refactor Exists

The preserved `refactor/productionize` work proved that production-targeted
stack modeling is viable, but it also exposed a provisioning/networking
assumption that conflicts with the intended platform design.

The current Terraform/Ansible path for SDN-backed guests assumes:

1. generated inventory connects through `ProxyJump=root@<proxmox-host>`
2. the Proxmox host itself must be able to reach guest SDN subnets directly
3. host-side route/IP priming is acceptable as part of normal stack bring-up

The intended design is different:

1. inter-VLAN/subnet routing belongs to the main router
2. Proxmox should not become the default administrative jump host for guest
   networks
3. host-side route priming should not be the long-term provisioning model

## What The Productionizing Work Already Achieved

The paused `refactor/productionize` branch established:

1. production credential controls and separate production secrets handling
2. a production non-secret env model in `.env.pve` / `.env.pve.template`
3. production storage intent in `terraform/lxc/storage/pve.yaml`
4. production network intent in `terraform/lxc/network/pve.yaml`
5. stack targeting decoupled from hardcoded `pve-test`
6. Portainer-specific secrets no longer blocking unrelated stack plans
7. SDN creation guardrails widened from `pve-test`-only to environment-aware
   creation, while destroy remained conservative
8. `apt-cacher-stack` identified and prepared as the first production canary

## Production Canary Evidence Preserved

For `apt-cacher-stack` on `pve`:

1. production-targeted plans rendered successfully
2. collision checks found no live conflict for:
   - VMID `40011`
   - IP `192.168.40.11`
   - an existing production `apt-cacher` workload
3. a narrow targeted apply created production SDN prerequisites for the canary:
   - zone `tvinfra`
   - VNet `tvinfra`
   - subnet `192.168.40.0/24`
   - gateway `192.168.40.1`

## The Specific Design Mismatch

Current repo behavior:

1. `terraform/lxc/templates/inventory.tpl` emits:
   - `ansible_ssh_common_args: ... ProxyJump=root@${pve_host}`
2. `terraform/lxc/main.tf` includes:
   - `null_resource.prime_sdn_host_route`
3. `prime_sdn_host_route` mutates host networking by adding:
   - a host-side bridge IP (`*.254`)
   - a route for the SDN guest subnet through that bridge

This is a workaround for the current provisioning path, not evidence that the
network should be designed this way.

## Live pve-test Evidence

Read-only checks against `pve-test` showed:

1. SDN zones and VNets exist for:
   - `tvinfra`
   - `tvmgmt`
   - `tvedge`
   - `tvsegc`
2. `apt-cacher-stack` and `harbor-stack` are live on `bridge=tvinfra`
3. `tvmgmt` has working host-side L3 presence:
   - interface IP `192.168.20.254/24`
   - route `192.168.20.0/24 dev tvmgmt src 192.168.20.254`
4. `tvinfra` exists as a link, but did not show comparable working host-side
   reachability during inspection
5. route lookup from `pve-test` to `10.57.3.11` fell back to the default route
   via `vmbr0`
6. ping from `pve-test` to `10.57.3.11` failed

Interpretation:

- `pve-test` does not currently demonstrate a clean, router-centric reachability
  model for SDN-backed guest provisioning
- it also does not support assuming that host-side route priming is unnecessary

## Current Program Decision

Do not continue production canary apply work yet.

Instead:

1. preserve the productionizing branch state for later reuse
2. plan and validate a dedicated network/provisioning refactor first
3. require at least one teardown + redeploy validation cycle on `pve-test`
   before returning to production canary progression

## What Can Be Reused Later

When this refactor is complete, the preserved productionizing work should still
be reusable:

1. production env and secret separation
2. production storage and network manifests
3. environment-driven stack targeting
4. production canary candidate selection (`apt-cacher-stack`)
5. SDN bootstrap logic, if still relevant after the corrected access model is
   chosen
