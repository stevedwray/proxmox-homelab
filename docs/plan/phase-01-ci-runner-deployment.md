# Phase 01 — CI Runner Deployment and Actions Pinning

## Goal

Bring up the self-hosted CI runner early in the greenfield rebuild so runner-dependent
repository validation can execute on the fresh `pve-test` environment, then verify
workflow action pins remain hardened.

This phase restores the runner capability needed by workflow jobs that target:

- `self-hosted`
- `pve-test`
- `build`

## Why this phase matters

On a fresh `pve-test` rebuild, GitHub-hosted workflows still run, but self-hosted jobs
such as `terraform-validate` and `ansible-lint` have no execution target until
`ci-runner-01` is deployed and registered. This phase establishes that execution path.

GitHub-hosted checks continue to run without the self-hosted runner. The current active
GitHub-hosted path covers Terraform format, Harbor image-policy enforcement, SOPS decrypt
verification, Trivy filesystem/secret/misconfiguration scanning, Snyk IaC, TruffleHog,
and SonarCloud. Phase 01 is specifically about restoring the self-hosted validation and
future build-pipeline path.

## Current intended order

This phase comes after Phase 00b, not before it. The current implementation expects
`pve-test` to be isolated behind the local Portainer bootstrap before the runner is brought
up.

## Greenfield assumptions

- `pve-test` is a fresh bare-metal Proxmox laptop rebuild
- Phase 00a and 00b are already complete
- Portainer is running locally on `mgmt_seg` at `192.168.20.20`
- the SDN VLAN zones, including `build_seg`, are already applied on `pve-test`
- no higher-phase shared services are assumed to exist yet

## Dependencies

- Phase 00b complete
- `build_seg` SDN zone/VNet available on `pve-test`
- GitHub CLI authenticated on the workstation
- `terraform/lxc/stacks/ci-runner-01/` and `deploy-ci-runner.yml` available

## Deliverables

- `ci-runner-01` running at `192.168.10.63` / VMID 10063
- GitHub Actions runner online with labels `self-hosted`, `pve-test`, `build`
- workflow action references still pinned to immutable SHAs
- self-hosted validation jobs re-enabled in `validate.yml`

## Current CI baseline

As of the 2026-04-16 recovery:

- workflow action references in `.github/workflows/` are pinned to immutable SHAs
- GitHub-hosted security and repository checks remain active
- self-hosted `terraform-validate` and `ansible-lint` jobs in `validate.yml` are
  re-enabled and again target `ci-runner-pve-test`

For a greenfield pass, the verified Phase 01 path is therefore:

1. ensure `build_seg` exists end-to-end, including the MikroTik `vlan10-build`
  interface and `192.168.10.1/24` gateway
2. deploy or redeploy `ci-runner-01`
3. if router-local DNS on `192.168.10.1` is still broken during bootstrap, treat any
  public resolver override as a temporary recovery step only and record it as debt
4. verify the runner is online, then use it as the execution target for self-hosted
  validation and future Phase 05 image scan, SBOM, and signing jobs

## Live task docs

- [01-ci-runner-01 — Deploy and register ci-runner-01 on build_seg](tasks/01-ci-runner-01-deploy-ci-runner.md)
- [01-ci-runner-02 — Verify and maintain immutable GitHub Actions pins](tasks/01-ci-runner-02-pin-github-actions.md)

## Troubleshooting

- [DNS and Egress Issues — Destroy/Deploy Testing](../troubleshooting/dns-egress-issues.md)

## Out of Scope

- apt proxy and Terraform mirror follow-up work from Phase 03c
- supply-chain CI jobs from Phase 05

## Acceptance Criteria

- [x] VMID 10063 exists and is reachable at `192.168.10.63`
- [x] Runner is online in GitHub with the expected labels
- [x] Self-hosted validation jobs can be scheduled again
- [x] Runner returns after reboot
- [x] No mutable workflow action refs remain in active workflows

## Notes

- Historical deployment detail and troubleshooting context remains available in archived
  task docs under `docs/plan/tasks/done/`
- The runner lives in `build_seg`, not `mgmt_seg`, by design
- The 2026-04-16 recovery exposed two greenfield bootstrap requirements that were easy to
  miss: the MikroTik needed an explicit `vlan10-build` interface with `192.168.10.1/24`,
  and the runner could not depend on router-local DNS on `192.168.10.1` during initial
  bootstrap. A temporary `1.1.1.1` override was used during recovery, then removed after
  platform DNS handling was corrected and the runner was revalidated against `192.168.10.1`.
- Proxmox rewrites `/etc/resolv.conf` on container boot, so a post-provision file copy was
  not enough for reboot persistence. `deploy-ci-runner.yml` now installs a root-owned
  `homelab-runner-resolver.service` and makes the runner service depend on it so the
  intended resolver is restored before the runner starts.
- Target state remains unchanged: all SDN-attached LXCs should use the MikroTik VLAN
  gateway as both default gateway and DNS resolver. Future tasks should not copy the
  temporary `1.1.1.1` recovery workaround into new stacks.
- The durable fix belongs in the platform lifecycle, not only in workload playbooks:
  either Proxmox container initialization or Terraform-driven post-create config must
  set the resolver that Proxmox will reapply on boot. Rebuilding the Debian template is
  only useful for shared package/baseline changes; template contents alone do not win
  against Proxmox rewriting `/etc/resolv.conf` during container startup.
