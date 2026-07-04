# 05-supply-chain-01 — Add Trivy image scan CI job

> Historical task packet.
> This document reflects the earlier `pve-test` CI and branch workflow.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

COMPLETE

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/108

## Phase

Phase 05 — Supply Chain Security

## Prerequisites

- Phase 01 complete — ci-runner-01 online at `10.57.0.63`, registered under `[self-hosted, pve-test, build]`
- Phase 03b complete — Harbor running at `10.57.3.10` in `infra_seg`, Trivy scanner enabled, `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` already stored as GitHub Actions secrets
- Phase 04 complete — full Phase 04 stack running (Authentik, Traefik, step-ca, Monitoring)
- Trivy is already present on the runner (installed in the `sast-scan` job setup); the difference here is adding an image-specific scan job

## Network placement

This task does not deploy a new container. All work runs on ci-runner-01 (VMID 141, `10.57.0.63`) in `build_seg` (`10.57.0.0/24`). No new network configuration is required. ci-runner-01 reaches Harbor (`10.57.3.10`) via MikroTik routing between `build_seg` (VLAN 10) and `infra_seg` (VLAN 40).

## Objective

A `trivy-image-scan` CI job exists in the relevant workflow, runs on the self-hosted runner after every image build, fails on CRITICAL/HIGH findings, and uploads the SARIF report to the GitHub Security tab.

## Scope

- Add `trivy-image-scan` job to `.github/workflows/` (the relevant build workflow)
- Job uses `aquasecurity/trivy-action` pinned to a specific version
- Job logs in to Harbor before scanning (`10.57.3.10`)
- SARIF output uploaded via `github/codeql-action/upload-sarif`
- `exit-code: "1"` ensures CRITICAL/HIGH findings break the build

## Out of Scope

- Filesystem / secrets / IaC Trivy scans (already in `sast-scan` job — do not change)
- External attestation integration, if reintroduced in a future phase
- Harbor Trivy scan-on-push configuration (done in Phase 03b)

## Inputs

- `.github/workflows/` — read existing jobs to find the correct workflow file to extend
- `docs/plan/phase-05-supply-chain.md` — Part A for exact YAML

## Expected Outputs

- One new job `trivy-image-scan` added to a build workflow

## Constraints and Conventions

- Pin `aquasecurity/trivy-action` to a specific version tag (e.g., `@v0.35.0`) — never `@main`
- Pin `github/codeql-action/upload-sarif` to its current hash or version
- Severity: `CRITICAL,HIGH` — do not include MEDIUM/LOW (too noisy)
- Image reference must use Harbor proxy format: `10.57.3.10/<project>/<image>:<tag>`
- This job only runs when a build job exists in the same workflow — if there is no image build job yet, add it to the workflow as a placeholder with a `if: false` gate or document it as extending in Phase 06

## Acceptance Criteria

- [x] `trivy-image-scan` job present in CI workflow
- [x] Job uses `runs-on: [self-hosted, pve-test, build]`
- [x] Docker login to `10.57.3.10` present (uses `HARBOR_ROBOT_USER`/`HARBOR_ROBOT_PASSWORD` secrets)
- [x] `exit-code: "1"` set for CRITICAL/HIGH
- [x] SARIF uploaded to GitHub Security tab (`upload-sarif` step)
- [x] Commit pushed to `baseline/teardown-validated`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Add a Trivy image scan CI job to the GitHub Actions workflow.

PREREQUISITES BRING-UP (pve-test is wiped between passes — bring up Phase 04 first):
  Follow the full Phase 04 bring-up sequence documented in the session prompt of
  docs/plan/tasks/04-core-services-05-deploy-monitoring.md (Steps 0 through 0f),
  then verify all Phase 04 stacks are healthy before continuing.
  ci-runner-01 must also be online — redeploy if the runner registration was lost:
    source .env && source .env.pve-test
    cd terraform/lxc/stacks/ci-runner-01 && terragrunt apply
    cd /home/steve/git/proxmox-homelab
    ansible-playbook -i "10.57.0.63," terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

STEP 1 — Read existing workflows:
  ls -1 .github/workflows/
  # Read the relevant build workflow to understand existing job structure

STEP 2 — Add trivy-image-scan job.
  Full spec is in docs/plan/phase-05-supply-chain.md (Part A).
  Key requirements:
  - runs-on: [self-hosted, pve-test, build]
  - needs: [build-image]  (or the actual build job name)
  - Docker login to 10.57.3.10 using HARBOR_ROBOT_USER / HARBOR_ROBOT_PASSWORD secrets
  - aquasecurity/trivy-action@<pin> with:
      scan-type: image
      image-ref: "10.57.3.10/<project>/<image>:<tag>"
      format: sarif
      output: trivy-image.sarif
      severity: CRITICAL,HIGH
      exit-code: "1"
  - github/codeql-action/upload-sarif@<pin> with sarif_file: trivy-image.sarif, if: always()

  NOTE: If no image build job exists yet (Phase 06 produces the first real builds), add the job
  with a comment noting it activates fully in Phase 06, and guard with:
    if: ${{ github.event_name != 'pull_request' }}
  so it can be tested without a real image.

STEP 3 — Commit:
  git checkout baseline/teardown-validated && git pull
  git checkout -b feat/trivy-image-scan
  git add .github/workflows/
  git commit -m "feat(ci): add Trivy image scan job with SARIF upload"
  git push origin feat/trivy-image-scan

SECURITY SCAN (run before merging — stop and present options if new issues are found):
  cd /home/steve/git/proxmox-homelab && source .env && sonar-scanner

  git checkout baseline/teardown-validated && git merge feat/trivy-image-scan
  git push origin baseline/teardown-validated

DONE WHEN: Job present in workflow file, HARBOR_ROBOT_* secret usage confirmed, scan clean, commit merged.
```
