# 05-supply-chain-02 — Install Syft on ci-runner-01 and add SBOM generation to CI

> Historical task packet.
> This document reflects the earlier `pve-test` CI and branch workflow.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/109

## Phase

Phase 05 — Supply Chain Security

## Prerequisites

- Phase 01 complete — ci-runner-01 running at `10.57.0.63`
- Phase 04 complete — full Phase 04 stack running (Authentik, Traefik, step-ca, Monitoring)
- Task 05-01 complete (or in parallel) — Trivy image scan job exists so SBOM job can follow it

## Network placement

This task does not deploy a new container. All work runs on ci-runner-01 (VMID 141, `10.57.0.63`) in `build_seg` (`10.57.0.0/24`). No new network configuration is required.

## Objective

Syft is installed on ci-runner-01 at a pinned version, a `generate-sbom` CI job runs after image builds, and the SBOM (SPDX-JSON) is uploaded as a GitHub Actions artifact with 90-day retention.

## Scope

- Add a `syft` install task to `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`
- Re-run the playbook against ci-runner-01 to install Syft
- Add `generate-sbom` job to the CI workflow

## Out of Scope

- Attaching the SBOM to an external attestation system, if reintroduced in a future phase
- Uploading SBOM to Harbor as an OCI artifact (future enhancement — not in scope for this phase)

## Inputs

- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml` — add Syft install task
- `.github/workflows/` — add `generate-sbom` job
- `docs/plan/phase-05-supply-chain.md` — Part B for exact YAML

## Expected Outputs

- `deploy-ci-runner.yml` updated with Syft install task
- New `generate-sbom` job in CI workflow
- Syft binary at `/usr/local/bin/syft` on ci-runner-01

## Constraints and Conventions

- Pin Syft version — check [github.com/anchore/syft/releases](https://github.com/anchore/syft/releases) for current stable (e.g., `v1.19.0`)
- Install via the official install script: `curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin v<VERSION>`
- Use `args: creates: /usr/local/bin/syft` for idempotency
- SBOM format: `spdx-json` (not cyclonedx)
- Artifact retention: 90 days

## Acceptance Criteria

- [ ] `syft --version` succeeds on ci-runner-01 and shows the pinned version
- [ ] `deploy-ci-runner.yml` has Syft install task with pinned version
- [ ] `generate-sbom` job present in CI workflow
- [ ] SBOM artifact uploaded with name `sbom-${{ github.sha }}` and 90-day retention
- [ ] Commit pushed to `baseline/teardown-validated`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Install Syft on ci-runner-01 and add SBOM generation to the CI workflow.

PREREQUISITES BRING-UP (pve-test is wiped between passes — bring up Phase 04 first):
  Follow the full Phase 04 bring-up sequence documented in the session prompt of
  docs/plan/tasks/04-core-services-05-deploy-monitoring.md (Steps 0 through 0f),
  then verify all Phase 04 stacks are healthy before continuing.
  ci-runner-01 must also be online:
    source .env && source .env.pve-test
    cd terraform/lxc/stacks/ci-runner-01 && terragrunt apply
    cd /home/steve/git/proxmox-homelab
    ansible-playbook -i "10.57.0.63," terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

STEP 1 — Read the existing ci-runner playbook:
  cat terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

STEP 2 — Add Syft install task to deploy-ci-runner.yml:
  Check https://github.com/anchore/syft/releases for the latest stable version.
  Add a task to install Syft (after Cosign install if it exists, or before the runner registration step):

    - name: Install Syft
      ansible.builtin.shell: |
        curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | \
          sh -s -- -b /usr/local/bin v<SYFT_VERSION>
      args:
        creates: /usr/local/bin/syft

  Pin to the specific version. Do not use 'latest'.

STEP 3 — Re-run playbook to install Syft on ci-runner-01:
  source .env && source .env.pve-test
  ansible-playbook -i "10.57.0.63," \
    terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

  Verify:
  ssh root@10.57.0.63 "syft --version"

STEP 4 — Add generate-sbom job to the CI workflow (.github/workflows/):
  Read docs/plan/phase-05-supply-chain.md (Part B) for the job YAML.
  The job should:
  - runs-on: [self-hosted, pve-test, build]
  - needs: [build-image] (or the actual build job name)
  - syft <harbor-image-ref> --output spdx-json=sbom.spdx.json
  - actions/upload-artifact@v4 with name sbom-${{ github.sha }}, retention-days: 90

STEP 5 — Commit:
  git checkout baseline/teardown-validated && git pull
  git checkout -b feat/syft-sbom
  git add terraform/lxc/ansible/playbooks/deploy-ci-runner.yml .github/workflows/
  git commit -m "feat(ci): install Syft on ci-runner and add SBOM generation job"
  git checkout baseline/teardown-validated && git merge feat/syft-sbom
  git push origin baseline/teardown-validated

DONE WHEN: syft binary confirmed on ci-runner-01, generate-sbom job in workflow, commit pushed.
```
