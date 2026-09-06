# 06-app-stacks-02 — Create app_seg and game_seg SDN zones

> Historical task packet.
> This task still references the retired `baseline/teardown-validated`
> promotion path and the earlier `pve-test` validation model.
> Keep it as migration-planning history rather than current workflow guidance.
> For current branch and environment rules, use
> [docs/workflow/branch-model.md](../../workflow/branch-model.md) and
> [docs/workflow/environments.md](../../workflow/environments.md).

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/114

## Phase

Phase 06 — Application Stack Migration

## Prerequisites

- Task 06-01 complete — workload discovery done; confirmed which IPs and subnets are needed
- Validated stack-owned edge foundation is running (Traefik, Authentik, step-ca, Monitoring)
- `terraform/lxc/network/` reviewed to understand existing SDN zone management approach

## Objective

Two new SDN zones (`app_seg` at `10.60.0.0/24` and `game_seg` at `10.61.0.0/24`) exist in Proxmox, LXCs can be provisioned into them, and the subnets are registered in NetBox.

## Scope

- Review `terraform/lxc/network/` to determine whether zones are Terraform-managed or Proxmox-UI-managed
- Create `app_seg` (10.60.0.0/24) — for Pi-hole, arr stack, Jellyfin
- Create `game_seg` (10.61.0.0/24) — for game servers
- Register subnets and zones in NetBox
- Verify that a test LXC can be provisioned into each zone (do not leave test LXCs running)

## Out of Scope

- Provisioning the application LXCs themselves (tasks 06-03 to 06-06)
- Firewall rules between zones (initial connectivity is permissive — tighten in a future phase)
- Adjusting subnets if they conflict with existing network layer — resolve conflicts before this task

## Inputs

- `terraform/lxc/network/` — review existing zone definitions
- `docs/plan/phase-06-app-stacks.md` — Segmentation target section
- Current network ranges in use (check NetBox or `ip route` on pve-test)

## Expected Outputs

- `app_seg` zone defined in Proxmox SDN with subnet `10.60.0.0/24`
- `game_seg` zone defined in Proxmox SDN with subnet `10.61.0.0/24`
- NetBox updated with both subnets
- If Terraform-managed: new `.tf` or variable additions committed

## Constraints and Conventions

- Verify `10.60.0.0/24` and `10.61.0.0/24` do not conflict with existing routes on pve-test or the host Proxmox
- Gateway for `app_seg`: `10.60.0.1`; Gateway for `game_seg`: `10.61.0.1`
- Zone names must match exactly what `stack.yaml` files in tasks 06-03 to 06-06 reference

## Acceptance Criteria

- [ ] `app_seg` zone visible in Proxmox SDN UI (or Terraform state)
- [ ] `game_seg` zone visible in Proxmox SDN UI (or Terraform state)
- [ ] `10.60.0.0/24` and `10.61.0.0/24` registered as subnets in NetBox
- [ ] An LXC can be assigned to each new zone without error (verified by test or deploy)
- [ ] Commit (if code changes) pushed to `baseline/teardown-validated`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Create app_seg (10.60.0.0/24) and game_seg (10.61.0.0/24) SDN zones for Phase 06
application stacks. These are additional internal networks separate from mgmt_seg (192.168.1.x).

STEP 1 — Review existing network configuration:
  ls -la terraform/lxc/network/
  cat terraform/lxc/network/*.tf  # or look at how current zones are defined
  # Also check docs/reference/sdn-segment-routing.md for context

STEP 2 — Verify no conflicts:
  # On pve-test or Proxmox host:
  ssh root@<pve-test> "ip route show | grep -E '10\.60\.|10\.61\.'"
  # Should return empty (subnets not already in use)

STEP 3a — If zones are Terraform-managed:
  Add app_seg and game_seg definitions to the appropriate .tf file in terraform/lxc/network/.
  Follow the pattern of existing zone definitions.
  Run: terragrunt plan → terragrunt apply

STEP 3b — If zones are Proxmox-UI-managed:
  In Proxmox web UI → Datacenter → SDN → Zones, create:
    - app_seg: VXLAN or Simple zone, subnet 10.60.0.0/24, gateway 10.60.0.1
    - game_seg: VXLAN or Simple zone, subnet 10.61.0.0/24, gateway 10.61.0.1
  Click Apply in the SDN interface to activate.

STEP 4 — Register in NetBox:
  Access http://192.168.1.30 (NetBox).
  Under IPAM → Prefixes, create:
    - 10.60.0.0/24 — description: "app_seg — application stacks"
    - 10.61.0.0/24 — description: "game_seg — game servers"
  Under Virtualization → Cluster Groups or Sites, note the zones.

STEP 5 — Verify routing from pve-test to new zones:
  ssh root@<pve-test> "ip route show | grep -E '10\.60\.|10\.61\.'"
  # Should show routes via the SDN bridge now

STEP 6 — Commit if code was changed:
  git checkout baseline/teardown-validated && git pull --ff-only origin baseline/teardown-validated
  git checkout -b feat/app-seg-zones
  git add terraform/lxc/network/
  git commit -m "feat(network): add app_seg (10.60.0.0/24) and game_seg (10.61.0.0/24) SDN zones"
  git checkout baseline/teardown-validated && git pull --ff-only origin baseline/teardown-validated
  git merge feat/app-seg-zones
  git push origin baseline/teardown-validated

DONE WHEN: Both zones exist in Proxmox, subnets in NetBox, routing confirmed.
Tasks 06-03 to 06-06 are now unblocked.
```
