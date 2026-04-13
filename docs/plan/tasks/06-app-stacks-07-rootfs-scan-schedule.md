# 06-app-stacks-07 — Add Trivy rootfs scheduled scan workflow

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/119

## Phase

Phase 06 — Application Stack Migration

## Prerequisites

- Tasks 06-03 to 06-06 complete — all Phase 06 LXCs deployed and running
- Phase 05 Task 05-01 complete — Trivy image scan CI job exists (Trivy installed on ci-runner-01)
- ci-runner-01 can SSH to all LXC IPs used by the platform and app segments (`10.57.x.x`, `10.60.x.x`, `10.61.x.x`)

## Objective

A scheduled GitHub Actions workflow `rootfs-scan.yml` runs every Monday at 03:00 UTC, SSHes into each LXC, runs `trivy rootfs /`, and uploads SARIF results to the GitHub Security tab. No CRITICAL findings exist on any LXC.

## Scope

- Install Trivy on each Phase 06 LXC via the base Ansible role
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
- `terraform/lxc/ansible/roles/base-lxc/tasks/main.yml` — add Trivy install here

## Expected Outputs

- `.github/workflows/rootfs-scan.yml` (new)
- `terraform/lxc/ansible/roles/base-lxc/tasks/main.yml` updated with Trivy install task
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
- [ ] Branch merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Add a scheduled Trivy rootfs scan CI workflow that SSHes into all LXCs weekly.

CONTEXT:
- Trivy is already installed on ci-runner-01 (from Phase 05)
- Full spec: docs/plan/phase-06-app-stacks.md (section "Trivy rootfs scheduled scans")
- LXCs to scan:
    10.57.3.11   (apt-cacher-ng)
    10.57.1.10   (Authentik)
    10.57.1.11   (step-ca)
    10.57.2.10   (Traefik)
    10.57.1.12   (Monitoring)
    10.60.0.10   (Pi-hole)
    10.60.0.20   (arr-stack)
    10.60.0.21   (Jellyfin)
    10.61.0.10   (game-stack)
- Add Phase 04/06 LXC IPs to the matrix even if Trivy hasn't been installed on them yet —
  the install step in STEP 2 covers them.

STEP 1 — Add Trivy install to base LXC Ansible role:
  Read terraform/lxc/ansible/roles/base-lxc/tasks/main.yml

  Add Trivy install task (pin to same version as Phase 05 image scan job):
    - name: Install Trivy
      ansible.builtin.shell: |
        curl -sSfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | \
          sh -s -- -b /usr/local/bin v<TRIVY_VERSION>
      args:
        creates: /usr/local/bin/trivy

STEP 2 — Install Trivy on all Phase 06 LXCs (and any Phase 04 LXCs not yet updated):
  # Run the base role or a targeted playbook against each LXC IP
  ansible-playbook -i "10.60.0.10,10.60.0.20,10.60.0.21,10.61.0.10," \
    terraform/lxc/ansible/playbooks/install-trivy.yml
  # Or add as --tags to existing stack playbooks and re-run each

  # Verify on one:
  ssh root@10.60.0.10 "trivy --version"

STEP 3 — Create .github/workflows/rootfs-scan.yml:
  Full YAML structure from docs/plan/phase-06-app-stacks.md.
  Key elements:
  - on.schedule: cron "0 3 * * 1"
  - on.workflow_dispatch
  - jobs.rootfs-scan:
      runs-on: [self-hosted, pve-test, build]
      strategy.matrix.host: [list of all LXC IPs above]
      steps:
        - actions/checkout@v4
        - name: Run Trivy rootfs scan via SSH
          run: |
            ssh -o StrictHostKeyChecking=accept-new root@${{ matrix.host }} \
              "trivy rootfs --severity HIGH,CRITICAL \
               --format sarif --output /tmp/trivy-rootfs.sarif / && \
               cat /tmp/trivy-rootfs.sarif" > trivy-rootfs-${{ matrix.host }}.sarif
        - name: Upload rootfs SARIF
          uses: github/codeql-action/upload-sarif@<pin>
          if: always()
          with:
            sarif_file: trivy-rootfs-${{ matrix.host }}.sarif
            category: rootfs-${{ matrix.host }}

STEP 4 — Test: run manually via workflow_dispatch and check the Security tab.

STEP 5 — Review findings: address any CRITICAL findings before merging.
  (Document any MEDIUM/LOW findings for follow-up — do not block on them.)

STEP 6 — Commit and merge:
  git checkout dev/pve-test && git pull
  git checkout -b feat/rootfs-scan
  git add .github/workflows/rootfs-scan.yml \
          terraform/lxc/ansible/roles/base-lxc/tasks/main.yml
  git commit -m "feat(ci): add weekly Trivy rootfs scan for all LXCs"
  git checkout dev/pve-test && git merge feat/rootfs-scan
  git push origin dev/pve-test

DONE WHEN: Workflow runs successfully via dispatch, SARIF uploaded to Security tab,
no CRITICAL findings, base role updated. Phase 06 is complete.
```
