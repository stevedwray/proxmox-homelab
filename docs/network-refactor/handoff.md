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
4. [target-model.md](/home/steve/git/proxmox-homelab/docs/network-refactor/target-model.md:1)
5. [validation-gate.md](/home/steve/git/proxmox-homelab/docs/network-refactor/validation-gate.md:1)
6. [terraform/lxc/templates/inventory.tpl](/home/steve/git/proxmox-homelab/terraform/lxc/templates/inventory.tpl:1)
7. [terraform/lxc/main.tf](/home/steve/git/proxmox-homelab/terraform/lxc/main.tf:595)
8. [terraform/lxc/network/pve-test.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/network/pve-test.yaml:1)
9. [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)

## What Is Already Known

1. The current generated inventory uses `ProxyJump=root@${pve_host}`.
2. `prime_sdn_host_route` was removed in Session 5; host-side route priming
   is no longer part of the current Terraform apply flow.
3. Production canary prep for `apt-cacher-stack` worked up to the point where
   the jump-host/routing model became the design concern.
4. `pve-test` live state is inconsistent:
   - `tvmgmt` has host-side reachability
   - `tvinfra` guests exist, but host-side reachability did not behave the same

## What The Next Session Should Do

1. Start from the session roadmap in `plan.md` rather than re-scoping the
   architecture from scratch.
2. Run Session 6 preflight and evidence capture, then Session 7 representative
   stack validation.
3. Capture inventory, SSH-path, DNS, and health evidence for the direct path.
4. Record any stack-specific exceptions that still prevent the teardown gate.

## Expected Outputs From The Next Session

At minimum, produce:

1. an updated target network/provisioning model doc when new evidence changes it
2. an updated implementation plan doc with session progress recorded
3. an updated teardown validation plan doc when validation mechanics change
4. explicit open questions that still require operator decisions

## Constraints

1. Do not resume production canary apply work in this planning session.
2. Do not merge preserved `refactor/productionize` work into a promotion branch.
3. Do not normalize `prime_sdn_host_route` as the final design without an
   explicit architecture decision.
4. Prefer read-only inspection and documentation updates first.
