# 06-app-stacks-07 — Add Trivy rootfs scheduled scan workflow

> Historical task packet.
> This document reflects the earlier `pve-test` Phase 06 and supply-chain
> planning workflow and retired branch model.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/119

## Phase

 [ ] Trivy task added to `lxc_base` Ansible role (future LXCs get it automatically)
- Phase 05 Task 05-01 complete — Trivy image scan CI job exists (Trivy installed on ci-runner-01)
- ci-runner-01 can SSH to all LXC IPs used by the platform and app segments (`10.57.x.x`, `10.60.x.x`, `10.61.x.x`)
 `terraform/lxc/ansible/roles/lxc_base/tasks/main.yml` — add Trivy install here

## Scope

- Install Trivy on each Phase 06 LXC via the lxc_base Ansible role
- Create `.github/workflows/rootfs-scan.yml` with matrix over all LXC IPs
- Ensure ci-runner-01 SSH host key is accepted for each LXC IP (or configure `StrictHostKeyChecking=accept-new`)
- Run the workflow once manually to verify

## Out of Scope

- Installing Trivy on Phase 04 LXCs (add those IPs to the matrix but Trivy install is done via their respective playbooks)
- Remediating found vulnerabilities (that is a follow-up task — the workflow produces the report)
- systemd timer alternative (Option B from the phase doc) — stick with GitHub Actions scheduled workflow (Option A)

## Inputs

- `docs/plan/phase-06-app-stacks.md` — Trivy rootfs scheduled scans section for the workflow YAML
- All LXC IPs to scan (Phase 03c apt-cacher at `10.57.3.11`, Phase 04 LXCs `10.57.1.10`, `10.57.1.11`, `10.57.2.10`, `10.57.1.12`, and Phase 06 LXCs `10.60.0.10`, `10.60.0.20`, `10.60.0.21`, `10.61.0.10`)
- `terraform/lxc/ansible/roles/lxc_base/tasks/main.yml` — add Trivy install here

## Expected Outputs

- `.github/workflows/rootfs-scan.yml` (new)
- `terraform/lxc/ansible/roles/lxc_base/tasks/main.yml` updated with Trivy install task
- Trivy installed on all Phase 06 LXCs
- Workflow runs successfully (at least once via `workflow_dispatch`)

## Constraints and Conventions

- Trivy version must be the same pin used in the Phase 05 image scan job
- SARIF format: `--format sarif --output /tmp/trivy-rootfs.sarif /`
- Matrix covers all LXC IPs; add new LXCs to the matrix as they are deployed in future
- `actions/upload-sarif` with `if: always()` — upload results even if findings exist
- Workflow trigger: `schedule: cron: "0 3 * * 1"` plus `workflow_dispatch`

## Acceptance Criteria

- [ ] `rootfs-scan.yml` present in `.github/workflows/`
- [ ] Workflow runs on schedule (Monday 03:00 UTC)
- [ ] Workflow can be triggered manually via `workflow_dispatch`
- [ ] All Phase 06 LXC IPs in the matrix
- [ ] All Phase 04+05 LXC IPs in the matrix
- [ ] Trivy task added to `base-lxc` Ansible role (future LXCs get it automatically)
- [ ] Trivy installed and functional on all Phase 06 LXCs
- [ ] SARIF upload to GitHub Security tab confirmed (workflow_dispatch test run)
- [ ] No CRITICAL findings on any LXC after initial run
- [ ] Branch merged to `baseline/teardown-validated`


TASK: Add a scheduled Trivy rootfs scan CI workflow that SSHes into all LXCs weekly.

    10.57.3.11   (apt-cacher-ng)
    10.57.1.10   (Authentik)
    10.57.1.11   (step-ca)
    10.60.0.20   (arr-stack)
    10.60.0.21   (Jellyfin)
    10.61.0.10   (game-stack)
STEP 1 — Add Trivy install to base LXC Ansible role:
  Read terraform/lxc/ansible/roles/lxc_base/tasks/main.yml

          sh -s -- -b /usr/local/bin v<TRIVY_VERSION>
      args:
        creates: /usr/local/bin/trivy
  # Or add as --tags to existing stack playbooks and re-run each

  # Verify on one:
      steps:
        - actions/checkout@v4
        - name: Run Trivy rootfs scan via SSH
          run: |
            ssh -o StrictHostKeyChecking=accept-new root@${{ matrix.host }} \
              "trivy rootfs --severity HIGH,CRITICAL \
               --format sarif --output /tmp/trivy-rootfs.sarif / && \
               cat /tmp/trivy-rootfs.sarif" > trivy-rootfs-${{ matrix.host }}.sarif
        - name: Upload rootfs SARIF
            sarif_file: trivy-rootfs-${{ matrix.host }}.sarif
            category: rootfs-${{ matrix.host }}

STEP 4 — Test: run manually via workflow_dispatch and check the Security tab.

STEP 5 — Review findings: address any CRITICAL findings before merging.
  (Document any MEDIUM/LOW findings for follow-up — do not block on them.)

STEP 6 — Commit and merge:
  git checkout -b feat/rootfs-scan
  git add .github/workflows/rootfs-scan.yml \
          terraform/lxc/ansible/roles/base-lxc/tasks/main.yml
  git commit -m "feat(ci): add weekly Trivy rootfs scan for all LXCs"
  git checkout baseline/teardown-validated && git pull --ff-only origin baseline/teardown-validated
  git merge feat/rootfs-scan
  git push origin baseline/teardown-validated

DONE WHEN: Workflow runs successfully via dispatch, SARIF uploaded to Security tab,
no CRITICAL findings, base role updated. Phase 06 is complete.
```
