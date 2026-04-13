# 01-ci-runner-01 — Deploy ci-runner-01 LXC via Terragrunt

## Status

COMPLETE

The `ci-runner-01` LXC (VMID 141) was provisioned on pve-test via `terragrunt apply` on
2026-04-10. The LXC is running at `10.57.0.63` with 2 vCPU and 4 GB RAM in the `build_seg`
SDN zone. SDN egress for `build_seg` was codified in Terraform and Ansible automation for
pve-test in the same session. See commit `49663c8` and issue #66 for detail.

## Phase

Phase 01 — CI Runner Deployment and Actions Pinning

## Prerequisites

- Phase 00 (housekeeping) complete
- pve-test Proxmox node reachable
- `build_seg` SDN zone live on pve-test (confirmed commit `e898386`, issue #52)
- `.env` sourced with `PM_API_TOKEN_ID`, `PM_API_TOKEN_SECRET`, `PM_API_URL`, `LXC_PASSWORD`

## Objective

VMID 141 (`ci-runner-01`) exists on pve-test, is reachable via SSH at `10.57.0.63`, and Terragrunt state shows `apply complete` with no pending changes.

## Scope

- `terragrunt apply` in `terraform/lxc/stacks/ci-runner-01/`
- Verify LXC is reachable

## Out of Scope

- Runner registration (task 01-02)
- Workflow verification (task 01-03)
- Actions pinning (task 01-04)

## Inputs

- `terraform/lxc/stacks/ci-runner-01/stack.yaml`
- `terraform/lxc/stacks/ci-runner-01/terragrunt.hcl`
- `.env` and `.env.pve-test`

## Expected Outputs

- VMID 141 running on pve-test at `10.57.0.63`
- Terraform state updated

## Constraints and Conventions

- Source `.env` before apply; `.env.pve-test` last to override to pve-test target
- Verify `TF_VAR_proxmox_node=pve-test` before apply

## Acceptance Criteria

- [x] VMID 141 (`ci-runner-01`) exists on pve-test
- [x] SSH to `10.57.0.63` succeeds as root
- [x] `terragrunt apply` exits 0 with `0 to add, 0 to change, 0 to destroy` on re-run

## Session Prompt

```
This task is COMPLETE. ci-runner-01 (VMID 141) is already running on pve-test at 10.57.0.63.

To verify the current state:
  gh api repos/stevedwray/proxmox-homelab/actions/runners \
    --jq '.runners[] | {name, status}'
  # Expected: ci-runner-pve-test with status: online

No action required.
```
