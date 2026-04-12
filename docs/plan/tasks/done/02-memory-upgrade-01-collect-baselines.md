# 02-memory-upgrade-01 — Collect LXC memory baselines and right-size limits

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/87

## Phase

Phase 02 — pve-test Memory Upgrade (32 GB)

## Prerequisites

- Phase 01 complete: CI runner online
- Harbor (VMID 121) and NetBox (VMID 119) have been **live for at least a few hours** so memory readings are representative
- SSH access to `root@pve-test.gibbsgreatly.xyz`

## Objective

Real working-set memory figures are recorded for Harbor and NetBox LXCs, any over-provisioned limits are corrected in `stack.yaml` and applied via Terragrunt, and all changes are committed before the host VM is resized.

## Scope

- SSH into pve-test and run `free -h` and `docker stats` inside each LXC (exec via pct)
- Compare observed RSS against configured limits in `stack.yaml`
- If right-sizing applies: edit `stack.yaml` memory field and run `terragrunt apply` (live resize, no restart needed)
- Commit any `stack.yaml` changes

## Out of Scope

- Resizing the pve-test VM itself (that is task 02-02)
- Changing cores, storage, or any non-memory fields
- Phase 04 stacks (not yet deployed)

## Inputs

- `terraform/lxc/stacks/harbor-stack/stack.yaml` — current `memory: 8192`
- `terraform/lxc/stacks/netbox-stack/stack.yaml` — current `memory: 4096`
- SSH access to pve-test to run `pct exec`
- `docs/plan/phase-02-memory-upgrade.md` — Part A for right-sizing rules

## Expected Outputs

- Observed RSS values recorded (in a commit message or comment)
- `stack.yaml` files updated if right-sizing applies
- `terragrunt apply` run to push any limit changes live

## Constraints and Conventions

- Right-size rule: reduce limit only if observed RSS is **consistently below** the threshold for several hours
  - `harbor-stack`: reduce to 6144 MB if stable below 5 GB RSS
  - `netbox-stack`: reduce to 3072 MB if stable below 2 GB RSS
- Do not increase limits here — that comes with the host resize in task 02-02
- Commit changes before proceeding to task 02-02
- Source `.env` and `.env.pve-test` before running `terragrunt apply`

## Acceptance Criteria

- [ ] Working-set RSS recorded for `harbor-stack` (VMID 121) and `netbox-stack` (VMID 119)
- [ ] Right-sizing decision documented (reduce / keep as-is) for each stack
- [ ] If right-sizing applied: `stack.yaml` updated and `terragrunt apply` exited 0
- [ ] Changes committed to `dev/pve-test` before proceeding

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Collect memory working-set baselines for Harbor and NetBox LXCs on pve-test, then
right-size their stack.yaml memory limits if they are over-provisioned.

BEFORE STARTING, READ:
  terraform/lxc/stacks/harbor-stack/stack.yaml   (current memory: 8192)
  terraform/lxc/stacks/netbox-stack/stack.yaml   (current memory: 4096)
  docs/plan/phase-02-memory-upgrade.md           (Part A — full rules and context)

STEP 1 — Collect baselines on pve-test:
  # Harbor LXC (VMID 121):
  ssh root@pve-test.gibbsgreatly.xyz \
    "pct exec 121 -- bash -c 'free -h && echo --- && docker stats --no-stream 2>/dev/null || true'"

  # NetBox LXC (VMID 119):
  ssh root@pve-test.gibbsgreatly.xyz \
    "pct exec 119 -- bash -c 'free -h && echo --- && docker stats --no-stream 2>/dev/null || true'"

  # Overall host pressure:
  ssh root@pve-test.gibbsgreatly.xyz "free -h"

STEP 2 — Apply right-sizing rules:
  - harbor-stack: If RSS consistently below ~5 GB → reduce stack.yaml memory to 6144
  - netbox-stack: If RSS consistently below ~2 GB → reduce stack.yaml memory to 3072
  If neither threshold is met, leave as-is and document the observed values.

STEP 3 — If right-sizing any stack, apply live:
  source .env && source .env.pve-test
  echo "Node: $TF_VAR_proxmox_node"   # must print: pve-test

  cd terraform/lxc/stacks/harbor-stack   # (or netbox-stack)
  terragrunt apply
  # LiveResizing does not require LXC restart

STEP 4 — Commit:
  cd /home/steve/git/proxmox-homelab
  git add terraform/lxc/stacks/harbor-stack/stack.yaml \
          terraform/lxc/stacks/netbox-stack/stack.yaml
  git commit -m "chore(infra): right-size LXC memory limits from observed working sets

harbor-stack: 8192 → <new-value> MB (observed RSS ~X GB)
netbox-stack: 4096 → <new-value> MB (observed RSS ~X GB)

Pre-step before pve-test host resize to 32 GB (issue #67)"

  git push origin dev/pve-test

DONE WHEN: Baselines recorded, any right-sizing committed. Then proceed to task
02-memory-upgrade-02-resize-vm.md.
```
