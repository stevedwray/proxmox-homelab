# Phase 03c — Artifact Proxy (apt-cacher-ng + Terraform mirror)

## Goal

Provide the lightweight local artifact plumbing needed by the greenfield platform build:

1. `apt-cacher-ng` for Debian package caching
2. a Terraform provider filesystem mirror for repeatable local and CI init operations
3. ci-runner follow-up so the runner actually uses both of the above

This phase intentionally avoids introducing a heavy artifact manager.

## Why this phase matters

Later phases repeatedly install packages and initialize Terraform/OpenTofu. Without local
artifact services, the rebuild is slower, less deterministic, and more dependent on
upstream availability.

## Dependencies

- Phase 00b complete
- Harbor deployment available for later image pulls
- `infra_seg` available on `pve-test`
- ci-runner available if the runner follow-up task is to be completed immediately

## Deliverables

- `apt-cacher-ng` at `10.57.3.11` / VMID 142
- shared LXC/base-role apt proxy configuration
- `terraform/terraform-providers/` mirror path defined and usable
- ci-runner updated to use apt proxy and `.terraformrc`

## Live task docs

- [03c-artifact-proxy-01 — Deploy apt-cacher-ng stack on infra_seg](tasks/03c-artifact-proxy-01-deploy-apt-cacher.md)
- [03c-artifact-proxy-02 — Configure Terraform provider filesystem mirror](tasks/03c-artifact-proxy-02-configure-terraform-mirror.md)
- [03c-artifact-proxy-03 — Apply apt proxy and Terraform mirror config to ci-runner-01](tasks/03c-artifact-proxy-03-update-ci-runner.md)

## Out of Scope

- Nexus or any heavy multi-artifact repository
- application-level package mirrors beyond what later phases explicitly require
- Harbor image policy enforcement, which belongs to Phase 05

## Acceptance Criteria

- [ ] apt-cacher-ng is healthy at `10.57.3.11:3142`
- [ ] new LXCs inherit `/etc/apt/apt.conf.d/01proxy`
- [ ] Terraform provider mirror exists and is usable locally
- [ ] ci-runner has both apt proxy config and `.terraformrc`
- [ ] no additional pip caching service is required

## Notes

- Keep this phase focused on infrastructure-level artifact plumbing
- Prefer task docs for concrete file creation, playbook changes, and verification commands
