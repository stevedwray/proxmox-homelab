# ci-runner-01 Canary Handoff (pve)

## Purpose

Use this packet to prepare the next low-risk production migration after NetBox:
`ci-runner-01` on `pve`.

## Scope

- validate the current `ci-runner-01` contract against the production target
- confirm the runner remains a consumer of the platform, not a dependency for it
- verify build-seg networking, Docker provisioning, and direct-access behavior
- identify any IP reuse or counterpart cleanup risk before cutover

## Source Documents

- [docs/productionize-refactor/tasks/07-incremental-migration-plan.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/07-incremental-migration-plan.md:1)
- [terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md:1)
- [terraform/lxc/stacks/ci-runner-01/stack.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01/stack.yaml:1)
- [terraform/lxc/stacks/ci-runner-01/terragrunt.hcl](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01/terragrunt.hcl:1)

## Done When

- the task backlog identifies `ci-runner-01` as the next migration after `portainer-stack`
- the stack contract and current generated inventory agree on the intended target behavior
- the next execution packet can be derived without further source discovery
