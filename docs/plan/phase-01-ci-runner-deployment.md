# Phase 01 — CI Runner Deployment and Actions Pinning

## Goal

Bring back the self-hosted CI runner early in the greenfield rebuild so repository
validation can run again, then verify workflow action pins remain hardened.

This phase restores the runner capability needed by workflow jobs that target:

- `self-hosted`
- `pve-test`
- `build`

## Why this phase matters

Without `ci-runner-01`, commits still trigger workflows, but self-hosted jobs such as
`terraform-validate` and `ansible-lint` queue indefinitely. This phase restores that
execution path.

## Current intended order

This phase comes after Phase 00b, not before it. The current implementation expects
`pve-test` to be isolated behind the local Portainer bootstrap before the runner is brought
up.

## Dependencies

- Phase 00b complete
- `build_seg` SDN zone/VNet available on `pve-test`
- GitHub CLI authenticated on the workstation
- `terraform/lxc/stacks/ci-runner-01/` and `deploy-ci-runner.yml` available

## Deliverables

- `ci-runner-01` running at `10.57.0.63` / VMID 141
- GitHub Actions runner online with labels `self-hosted`, `pve-test`, `build`
- workflow action references still pinned to immutable SHAs

## Live task docs

- [01-ci-runner-01 — Deploy and register ci-runner-01 on build_seg](tasks/01-ci-runner-01-deploy-ci-runner.md)
- [01-ci-runner-02 — Verify and maintain immutable GitHub Actions pins](tasks/01-ci-runner-02-pin-github-actions.md)

## Out of Scope

- apt proxy and Terraform mirror follow-up work from Phase 03c
- supply-chain CI jobs from Phase 05

## Acceptance Criteria

- [ ] VMID 141 exists and is reachable at `10.57.0.63`
- [ ] Runner is online in GitHub with the expected labels
- [ ] Self-hosted validation jobs can be scheduled again
- [ ] Runner returns after reboot
- [ ] No mutable workflow action refs remain in active workflows

## Notes

- Historical deployment detail and troubleshooting context remains available in archived
  task docs under `docs/plan/tasks/done/`
