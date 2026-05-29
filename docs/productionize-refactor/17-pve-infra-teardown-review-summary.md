# pve Infra-Only Teardown Review Summary

## Purpose

Capture the operator-facing outcome of the latest advisory `pve` infra-only
teardown planner run, with emphasis on blast-radius review.

This is not a destroy approval. It is a review summary for the current
evidence set.

## Evidence Reviewed

- stamped planner run:
  [summary.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-173500/summary.md:1)
- live platform status:
  [platform-status-in-scope-present.log](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-173500/logs/platform-status-in-scope-present.log:1)
  [platform-status-out-of-scope-guests.log](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-173500/logs/platform-status-out-of-scope-guests.log:1)

## Current Read

The advisory planner run for `20260523-173500` did not surface an obvious
automation blocker.

What it supports:

- all 10 in-scope infra guests were present on `pve`
- no in-scope guest was missing
- live read-only `pct`, `qm`, and `pvesm` checks all succeeded
- all per-stack destroy plans exited `0`
- no obvious `pve-test` bleed-through was identified in the destroy-plan logs

## In-Scope Guests

The infra-only set under consideration remains:

- `ci-runner-01`
- `authentik-stack`
- `step-ca-stack`
- `monitoring-stack`
- `dns-stack`
- `portainer-stack`
- `proxy-stack`
- `harbor-stack`
- `apt-cacher-stack`
- `netbox-stack`

## Out-Of-Scope Guests

The same planner run explicitly observed out-of-scope guests on `pve` that must
remain untouched by any future destructive packet, including:

- `torrent-stack`
- `management-stack`
- `media-stack`
- `gaming-stack`
- `cloud-stack`
- `proxmox-backup-server`
- `securityonion`
- `wazuh`
- `analysis-stack`
- `elastic-stack`
- `pve-test`
- `omada-controller`
- `test-docker`
- `debian13-template-builder`

See the full observed list in
[platform-status-out-of-scope-guests.log](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-173500/logs/platform-status-out-of-scope-guests.log:1).

## Practical Meaning

The main remaining question is no longer whether the planner can run. It is
whether the operator is satisfied that:

1. any future teardown packet must touch only the 10 in-scope infra guests
2. every listed out-of-scope guest on `pve` must remain completely untouched
3. each per-stack destroy plan has been manually reviewed for scope safety

## Not Yet Approved

This review summary does not replace:

- human review of each `plan-destroy-*.log`
- human shared-host blast-radius sign-off
- final approval of any real `pve` teardown test
