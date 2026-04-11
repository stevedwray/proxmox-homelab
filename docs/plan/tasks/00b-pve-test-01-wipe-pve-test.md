# 00b-pve-test-01 — Wipe pve-test before Portainer bootstrap

## Status

PENDING

## Phase

Phase 00b — pve-test Management Bootstrap

## Prerequisites

- SSH access to `root@pve-test.gibbsgreatly.xyz`
- `.env` and `.env.pve-test` both present in repo root (`.env.pve-test` sets `TF_VAR_proxmox_node=pve-test`)
- Terragrunt installed on workstation
- Terraform state files for both stacks exist at the paths listed below

## Objective

All LXC containers are destroyed on pve-test and `pvesh get /nodes/pve-test/lxc` returns an empty list, leaving pve-test clean for a fresh Portainer-first deployment sequence.

## Scope

- Destroy `netbox-stack-test` (VMID 142) via `terragrunt destroy`
- Destroy `ci-runner-01` (VMID 141) via `terragrunt destroy`
- Manually destroy any VMIDs not tracked in Terraform state
- Verify pve-test is empty via `pvesh`

## Out of Scope

- Any changes to production `pve` node
- Modifying Terraform or Ansible source files
- Deploying anything (that is task 00b-02 and 00b-03)

## Inputs

- `terraform/lxc/stacks/netbox-stack-test/` — Terraform state at `terraform.tfstate.d/pve-test/`
- `terraform/lxc/stacks/ci-runner-01/` — Terraform state at `terraform.tfstate.d/pve-test/`
- `.env` and `.env.pve-test` in repo root

## Expected Outputs

- No files modified
- Both LXCs deleted from pve-test infrastructure
- Terraform state updated to reflect destroyed resources

## Constraints and Conventions

- **Safety rule**: always verify `TF_VAR_proxmox_node=pve-test` and `TF_WORKSPACE=pve-test` before any destroy. Stop immediately if either is wrong.
- Source `.env` first, then `.env.pve-test` last so pve-test overrides win.
- Terragrunt runs `tofu init -reconfigure` via a `before_hook` — no manual init needed.
- Destroy in reverse deploy order: netbox-stack-test first, then ci-runner-01.

## Acceptance Criteria

- [ ] `TF_VAR_proxmox_node` prints `pve-test` before each destroy
- [ ] `TF_WORKSPACE` prints `pve-test` before each destroy
- [ ] `netbox-stack-test` (VMID 142) destroyed: `terragrunt destroy` exits 0
- [ ] `ci-runner-01` (VMID 141) destroyed: `terragrunt destroy` exits 0
- [ ] `pvesh get /nodes/pve-test/lxc --output-format json` returns `[]`
- [ ] No orphaned VMIDs remain on pve-test

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Wipe all LXC containers from pve-test in preparation for a clean Portainer-first
deployment sequence (Phase 00b).

CONTEXT:
- pve-test is a nested Proxmox VM used as a test deployment target.
- All existing LXCs must be destroyed before the new standalone Portainer server is deployed.
- This is a DESTROY-only task. Do not create or modify any files.
- The production `pve` node must NEVER be targeted. Verify the node target before every
  destroy command.

CONTAINERS TO DESTROY (on pve-test only):
| Stack              | VMID | State path                                            |
|--------------------|------|-------------------------------------------------------|
| netbox-stack-test  | 142  | terraform/lxc/stacks/netbox-stack-test/               |
| ci-runner-01       | 141  | terraform/lxc/stacks/ci-runner-01/                    |

SAFETY PROCEDURE (mandatory before every destroy):
1. Source environment:
   source /home/steve/git/proxmox-homelab/.env
   source /home/steve/git/proxmox-homelab/.env.pve-test

2. Verify targets (stop immediately if either is wrong):
   echo "Node target  : $TF_VAR_proxmox_node"   # must print: pve-test
   echo "TF workspace : $TF_WORKSPACE"           # must print: pve-test

DESTROY SEQUENCE:
   cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/netbox-stack-test
   terragrunt destroy

   cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01
   terragrunt destroy

VERIFY EMPTY:
   ssh root@pve-test.gibbsgreatly.xyz \
     "pvesh get /nodes/pve-test/lxc --output-format json | jq '.[].vmid'"
   # Expected: no output (empty array)

If pvesh shows VMIDs not listed in the table above, destroy them manually:
   ssh root@pve-test.gibbsgreatly.xyz "pct stop <vmid> ; pct destroy <vmid>"

DONE WHEN: pvesh returns an empty JSON array and both terragrunt destroys exited 0.
No files need to be committed — this task has no code changes.
```
