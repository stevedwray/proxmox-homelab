# 08 — Networking Refactor Checkpoint

## Purpose

Preserve the current `refactor/productionize` branch state before continuing
with any production canary apply beyond SDN bootstrap.

This checkpoint exists because the productionizing refactor uncovered a
provisioning/networking assumption that does not match the intended platform
design:

- the generated Ansible inventory currently uses `ProxyJump=root@<proxmox-host>`
- SDN-backed stack provisioning therefore depends on the Proxmox host having
  direct L3 reachability into guest subnets
- the current implementation compensates with `prime_sdn_host_route`
- the intended design is for routed VLAN/subnet reachability to be handled by
  the main router, not by treating Proxmox as the jump host or subnet gateway

This branch should be preserved for later reuse. It should not be promoted to
`baseline/teardown-validated` or `dev/pve-test` in its current form.

## Current Branch State

Branch:

- `refactor/productionize`

Recent commits in this phase:

1. `a4b6578` `Add production credential control scaffolding`
2. `65be08a` `Record validated production credential state`
3. `adeefa7` `Define production non-secret environment overlays`
4. `a54772a` `Add production LXC storage manifest`
5. `fa3e3e4` `Define production SDN network intent`
6. `1f92de6` `Decouple active stacks from pve-test targeting`
7. `584252c` `Clarify production address contract for active stacks`
8. `8543188` `Scope Portainer secrets to Portainer workflows`
9. `5a6c51d` `Tighten SDN guardrails for production targeting`

## What Was Achieved

The productionizing work accomplished several important pieces that should be
retained:

1. Production credential controls and separate production secret handling were
   introduced.
2. `.env.pve` and `.env.pve.template` were expanded into a coherent production
   non-secret environment model.
3. Production storage intent was modeled in:
   - `terraform/lxc/storage/pve.yaml`
4. Production network intent was modeled in:
   - `terraform/lxc/network/pve.yaml`
5. Active stack targeting was decoupled from hardcoded `pve-test`.
6. Portainer-only secrets were removed as blockers for unrelated stack plans.
7. SDN creation guardrails were widened from `pve-test`-only to
   environment-aware creation, while SDN destroy remained conservative.
8. The first production-targeted canary stack candidate (`apt-cacher-stack`)
   was validated through plan and partial SDN bootstrap steps.

## Production Validation Performed

For `apt-cacher-stack` on `pve`:

1. Production-targeted read-only plans rendered successfully.
2. Collision checks showed no live conflict for:
   - VMID `40011`
   - IP `192.168.40.11`
   - an existing production `apt-cacher` workload
3. SDN prerequisites were initially missing on `pve`.
4. A narrow targeted apply was run for:
   - `local_file.network_sdn_vars`
   - `null_resource.configure_network_sdn_attachment`
5. That targeted apply created the production SDN objects for the canary path:
   - zone `tvinfra`
   - VNet `tvinfra`
   - subnet `192.168.40.0/24`
   - gateway `192.168.40.1`

## The Blocking Discovery

The current Terraform/Ansible provisioning path for SDN-backed guests assumes
Ansible connects through the Proxmox host.

Evidence:

1. `terraform/lxc/templates/inventory.tpl` generates:
   - `ansible_ssh_common_args: ... ProxyJump=root@${pve_host}`
2. `terraform/lxc/main.tf` contains `null_resource.prime_sdn_host_route`.
3. `prime_sdn_host_route` mutates host networking on the Proxmox node to add:
   - a host-side IP on the SDN bridge (`*.254`)
   - a route for the guest subnet via that bridge

This is a provisioning workaround, not the intended network architecture.

## What Live pve-test Inspection Showed

Live checks against `pve-test` showed that the current test environment is
already inconsistent in this area:

1. SDN zones and VNets exist for:
   - `tvinfra`
   - `tvmgmt`
   - `tvedge`
   - `tvsegc`
2. `apt-cacher-stack` and `harbor-stack` are live on `bridge=tvinfra`.
3. `tvmgmt` has a host-side IP and route:
   - `192.168.20.254/24`
   - `192.168.20.0/24 dev tvmgmt src 192.168.20.254`
4. `tvinfra` exists as a link, but did not show a comparable host-side IPv4
   address during inspection.
5. Route lookup on `pve-test` for `10.57.3.11` fell back to the default route
   via `vmbr0`, and ping failed.
6. Route lookup for a `tvmgmt` guest resolved correctly via `tvmgmt`.

Interpretation:

- the current `pve-test` environment does not provide clean evidence that
  host-side route priming is unnecessary
- instead, it shows that the jump-host provisioning model and the intended
  routed-VLAN network design are currently out of alignment

## Why This Branch Must Pause

This branch is valuable, but it is not a safe promotion candidate.

Reasons:

1. The productionizing refactor is now entangled with an unplanned networking
   behavior change.
2. The current path can likely make production canaries work, but by leaning on
   a host-route/jump-host model that is not the desired end state.
3. Promoting this branch without first addressing the networking model would
   normalize tactical infrastructure behavior into the baseline.

## Recommended Next Program

The next effort should be a dedicated network/provisioning refactor planning
track with its own documentation and at least one teardown validation cycle.

Suggested planning topics:

1. Desired routing model for SDN-backed guest subnets.
2. Whether operator workstations should reach guest VLANs directly via the main
   router instead of ProxyJump via Proxmox.
3. How Terraform-generated inventories should connect to guests when the target
   stack is on an SDN VNet.
4. Whether `prime_sdn_host_route` should be removed entirely, replaced, or kept
   only as a temporary compatibility shim.
5. What teardown/redeploy tests are required to prove the corrected model on
   `pve-test` before reattempting production canary progression.

## Branching Note

Per repository workflow rules in `AGENTS.md`:

- `baseline/teardown-validated` is a promotion target only
- new development should not be based directly on `baseline/teardown-validated`

For the follow-on refactor, use a normal working branch for planning and
implementation rather than developing directly on a promotion branch.

## Resume Point For This Branch

When the networking refactor is planned and validated, return to this branch
state and reuse the preserved productionizing work:

1. production env and secret separation
2. production storage/network manifests
3. active stack environment decoupling
4. apt-cacher production canary preparation
5. production SDN bootstrap logic, if still relevant after redesign

Until then, treat `refactor/productionize` as a preserved checkpoint branch,
not a merge candidate.
