# 05-supply-chain-05 — Add Harbor-only image policy enforcement to CI

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/112

## Phase

Phase 05 — Supply Chain Security

## Prerequisites

- Phase 03b complete — Harbor proxy cache projects configured
- Phase 01 complete — ci-runner-01 online
- Task 05-01 through 05-04 complete (or in progress) — this task can be done in parallel after 05-01

## Objective

A `harbor-image-policy` CI job fails whenever any compose file in the repo references `docker.io`, `ghcr.io`, `quay.io`, or `registry.k8s.io` directly instead of using the Harbor proxy address `192.168.1.10/...`.

## Scope

- Add `harbor-image-policy` job to `.github/workflows/validate.yml` (the lint/validate workflow)
- Job runs `grep` over all `*.yml` and `*.yaml` under `terraform/lxc/stacks/` for direct upstream registry references
- Fix any existing violations found in the grep before committing

## Out of Scope

- Policy enforcement at Harbor (Harbor content trust / Cosign verify — configured separately)
- Enforcing which specific version tags are pinned (a separate Renovate/Dependabot concern)
- Scanning `ansible/` or root-level YAML files (scope limited to `terraform/lxc/stacks/`)

## Inputs

- `.github/workflows/validate.yml` — extend with new job
- `terraform/lxc/stacks/**/*.yml` — grep these for violations
- `docs/plan/phase-05-supply-chain.md` — Part E for exact grep command and job YAML

## Expected Outputs

- New `harbor-image-policy` job in `validate.yml`
- Any existing violations in `terraform/lxc/stacks/` fixed to use `192.168.1.10/...`

## Constraints and Conventions

- Job runs on `ubuntu-latest` (not self-hosted) — it is a file-lint check requiring no network access
- Pattern to reject: `image:` lines containing `docker.io`, `ghcr.io`, `quay.io`, or `registry.k8s.io`
- Exception: the grep should not flag commented-out lines
- The job must emit a clear error message naming the offending file and line, not just `exit 1`

## Acceptance Criteria

- [ ] `harbor-image-policy` job present in `validate.yml`
- [ ] Job runs on `ubuntu-latest`
- [ ] Job fails on any `image:` line with direct upstream registry reference
- [ ] All existing compose files in `terraform/lxc/stacks/` pass the check clean
- [ ] Commit pushed to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Add a harbor-image-policy lint check to the CI validate workflow that fails whenever
any Docker Compose file in terraform/lxc/stacks/ references an upstream registry directly
instead of the Harbor proxy at 192.168.1.10.

STEP 1 — Read the existing validate workflow:
  cat .github/workflows/validate.yml

STEP 2 — Scan for existing violations:
  grep -rn "image:.*\(docker\.io\|ghcr\.io\|quay\.io\|registry\.k8s\.io\)" \
    terraform/lxc/stacks/ --include="*.yml" --include="*.yaml"
  # If any results, fix them to use 192.168.1.10/<project>/<image>:<tag> before continuing.

STEP 3 — Add harbor-image-policy job to .github/workflows/validate.yml:
  Full spec in docs/plan/phase-05-supply-chain.md (Part E).
  The job should:
  - runs-on: ubuntu-latest
  - uses: actions/checkout@v4
  - Run a grep that covers docker.io, ghcr.io, quay.io, registry.k8s.io
  - On violation: print the file path and line, then exit 1
  - On clean: print "OK — all image references use Harbor proxy."

  Example script for the check:
    if grep -rn "^\s*image:\s*.*\(docker\.io\|ghcr\.io\|quay\.io\|registry\.k8s\.io\)" \
         terraform/lxc/stacks/ --include="*.yml" --include="*.yaml"; then
      echo "ERROR: Direct upstream registry references found. Use 192.168.1.10/... instead."
      exit 1
    fi
    echo "OK — all image references use Harbor proxy."

STEP 4 — Test the check locally (it should pass clean):
  bash -c 'if grep -rn "image:.*\(docker\.io\|ghcr\.io\|quay\.io\|registry\.k8s\.io\)" \
    terraform/lxc/stacks/ --include="*.yml" --include="*.yaml"; then echo FAIL; exit 1; fi; echo PASS'

STEP 5 — Commit:
  git checkout dev/pve-test && git pull
  git checkout -b feat/harbor-image-policy
  git add .github/workflows/validate.yml
  # Include any fixed compose files if violations were found in step 2
  git commit -m "feat(ci): add harbor-only image policy lint check to validate workflow"
  git checkout dev/pve-test && git merge feat/harbor-image-policy
  git push origin dev/pve-test

DONE WHEN: harbor-image-policy job in validate.yml, local grep check passes clean, commit pushed.
Phase 05 is complete. Phase 06 app stack migration is now unblocked.
```
