# Network Refactor Handoff

## Session Goal

Prepare the network/provisioning refactor so future implementation work can
correct SDN-backed guest reachability without relying on Proxmox as the default
jump host.

This handoff is for planning and evidence gathering first, not immediate
implementation.

## Start Here

Read these in order:

1. [README.md](/home/steve/git/proxmox-homelab/docs/network-refactor/README.md:1)
2. [checkpoint.md](/home/steve/git/proxmox-homelab/docs/network-refactor/checkpoint.md:1)
3. [plan.md](/home/steve/git/proxmox-homelab/docs/network-refactor/plan.md:1)
4. [terraform/lxc/templates/inventory.tpl](/home/steve/git/proxmox-homelab/terraform/lxc/templates/inventory.tpl:1)
5. [terraform/lxc/main.tf](/home/steve/git/proxmox-homelab/terraform/lxc/main.tf:595)
6. [terraform/lxc/network/pve-test.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/network/pve-test.yaml:1)
7. [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)

## What Is Already Known

1. The current generated inventory uses `ProxyJump=root@${pve_host}`.
2. `prime_sdn_host_route` adds host-side IP/route state on the Proxmox host.
3. Production canary prep for `apt-cacher-stack` worked up to the point where
   the jump-host/routing model became the design concern.
4. `pve-test` live state is inconsistent:
   - `tvmgmt` has host-side reachability
   - `tvinfra` guests exist, but host-side reachability did not behave the same

## What The Next Session Should Do

1. Confirm the intended L3 model:
   - which networks are routed by the main router
   - which hosts/admin workstations are supposed to reach which guest subnets
2. Map the current implementation assumptions:
   - inventory generation
   - ProxyJump usage
   - host-route priming
   - any manual router/proxmox configuration
3. Convert the current `plan.md` into a more concrete task breakdown under
   `docs/network-refactor/`.
4. Define the teardown validation gate for the refactor.

## Expected Outputs From The Next Session

At minimum, produce:

1. a clarified target network/provisioning model doc
2. a concrete implementation plan doc
3. a teardown validation plan doc
4. explicit open questions that still require operator decisions

## Constraints

1. Do not resume production canary apply work in this planning session.
2. Do not merge preserved `refactor/productionize` work into a promotion branch.
3. Do not normalize `prime_sdn_host_route` as the final design without an
   explicit architecture decision.
4. Prefer read-only inspection and documentation updates first.
