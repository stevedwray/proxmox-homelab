# 05-supply-chain-03 — Generate Cosign keys and add image signing to CI

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/110

## Phase

Phase 05 — Supply Chain Security

## Prerequisites

- Task 05-01 complete — Trivy image scan job in CI (signing only happens after scan passes)
- Phase 01 complete — ci-runner-01 running
- Phase 04 complete — full Phase 04 stack running (Authentik, Traefik, step-ca, Monitoring)

## Network placement

This task does not deploy a new container. All work runs on ci-runner-01 (VMID 141, `10.57.0.63`) in `build_seg` (`10.57.0.0/24`). No new network configuration is required.

## Objective

A Cosign signing key pair is generated, `cosign.pub` is committed to the repo, `cosign.key` is stored encrypted as a GitHub Actions secret, images are signed in CI after a successful Trivy scan, and `cosign verify --key cosign.pub` passes for at least one signed image in Harbor.

## Scope

- Generate `cosign.key` + `cosign.pub` on the workstation (NOT in CI)
- Add `cosign.pub` to the repo (safe to commit — public key)
- Store `cosign.key` and `COSIGN_PASSWORD` as GitHub Actions secrets
- Add Cosign install task to `deploy-ci-runner.yml`
- Re-run the ci-runner playbook to install Cosign
- Add `sign-image` CI job that runs after `trivy-image-scan`

## Out of Scope

- Distributing `cosign.pub` to all LXCs for deploy-time verification (add to base role in Phase 06)
- Chainloop integration (task 05-04)
- SOPS/age encryption of `cosign.key` (storing via GitHub Actions secret is sufficient for Phase 05)

## Inputs

- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`
- `.github/workflows/` — add `sign-image` job
- `docs/plan/phase-05-supply-chain.md` — Part C for exact YAML

## Expected Outputs

- `cosign.pub` in repo root (or `certs/cosign.pub`)
- `deploy-ci-runner.yml` updated with Cosign install task
- New `sign-image` CI job
- `COSIGN_KEY` and `COSIGN_PASSWORD` GitHub Actions secrets set

## Constraints and Conventions

- **Never commit `cosign.key` unencrypted** — verify `.gitignore` includes `cosign.key` before any `git add`
- Pin Cosign version — check [github.com/sigstore/cosign/releases](https://github.com/sigstore/cosign/releases)
- Sign images by digest (`@sha256:...`), not by tag, to prevent tag mutation attacks
- `sign-image` job must `needs: [trivy-image-scan]` — do not sign images that failed the scan
- `COSIGN_KEY` secret contains the PEM-encoded private key content (what `cosign generate-key-pair` puts in `cosign.key`)

## Acceptance Criteria

- [ ] `cosign.pub` committed to repo
- [ ] `cosign.key` NOT in repo (confirmed by `git ls-files cosign.key` returning empty)
- [ ] `COSIGN_KEY` and `COSIGN_PASSWORD` set as GitHub Actions secrets
- [ ] Cosign installed on ci-runner-01 at pinned version
- [ ] `sign-image` job in CI workflow with `needs: [trivy-image-scan]`
- [ ] `cosign verify --key cosign.pub <harbor-image-ref>` passes for at least one image
- [ ] Commit pushed to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Generate Cosign signing keys, add image signing to CI.
WARNING: Never commit cosign.key. Verify .gitignore before any git add.

PREREQUISITES BRING-UP (pve-test is wiped between passes — bring up Phase 04 first):
  Follow the full Phase 04 bring-up sequence documented in the session prompt of
  docs/plan/tasks/04-core-services-05-deploy-monitoring.md (Steps 0 through 0f),
  then verify all Phase 04 stacks are healthy before continuing.
  ci-runner-01 must also be online:
    source .env && source .env.pve-test
    cd terraform/lxc/stacks/ci-runner-01 && terragrunt apply
    cd /home/steve/git/proxmox-homelab
    ansible-playbook -i "10.57.0.63," terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

STEP 1 — Add cosign.key to .gitignore (do this FIRST):
  grep -q "cosign.key" .gitignore || echo "cosign.key" >> .gitignore

STEP 2 — Generate key pair (on workstation, not in CI):
  cosign generate-key-pair
  # Enter a strong passphrase — this becomes COSIGN_PASSWORD
  # Creates: cosign.key (private, encrypted) and cosign.pub (public)

STEP 3 — Add cosign.pub to the repo:
  mkdir -p certs/
  cp cosign.pub certs/cosign.pub   # or keep in root if preferred
  git add certs/cosign.pub
  # Verify cosign.key is NOT being added:
  git status | grep cosign.key  # must be empty

STEP 4 — Store secrets in GitHub Actions:
  cat cosign.key | gh secret set COSIGN_KEY -R <owner>/<repo>
  gh secret set COSIGN_PASSWORD -R <owner>/<repo>
  # Enter the passphrase when prompted

STEP 5 — Add Cosign install task to deploy-ci-runner.yml:
  Check https://github.com/sigstore/cosign/releases for latest stable version.
  Add task:
    - name: Install Cosign
      ansible.builtin.shell: |
        curl -sSfL "https://github.com/sigstore/cosign/releases/download/v<VERSION>/cosign-linux-amd64" \
          -o /usr/local/bin/cosign && chmod +x /usr/local/bin/cosign
      args:
        creates: /usr/local/bin/cosign

STEP 6 — Re-run playbook:
  source .env && source .env.pve-test
  ansible-playbook -i "10.57.0.63," terraform/lxc/ansible/playbooks/deploy-ci-runner.yml
  ssh root@10.57.0.63 "cosign version"

STEP 7 — Add sign-image job to CI workflow:
  Read docs/plan/phase-05-supply-chain.md (Part C) for exact YAML.
  Key requirements:
  - needs: [trivy-image-scan]  (only sign AFTER scan passes)
  - runs-on: [self-hosted, pve-test, build]
  - echo "$COSIGN_KEY" > /tmp/cosign.key  (from secret)
  - cosign sign --key /tmp/cosign.key 192.168.1.10/<project>/<image>@<digest>
  - rm /tmp/cosign.key  (clean up private key from disk)

STEP 8 — Verify signing works (once Phase 06 produces a real image):
  cosign verify --key certs/cosign.pub 192.168.1.10/<project>/<image>@<digest>

STEP 9 — Commit:
  git checkout dev/pve-test && git pull
  git checkout -b feat/cosign-signing
  git add certs/cosign.pub terraform/lxc/ansible/playbooks/deploy-ci-runner.yml .github/workflows/
  # Verify cosign.key not staged:
  git status | grep "cosign.key"  # must be empty
  git commit -m "feat(ci): add Cosign image signing — key pair, CI job, runner install"
  git checkout dev/pve-test && git merge feat/cosign-signing
  git push origin dev/pve-test

DONE WHEN: cosign.pub committed, cosign.key NOT in git, sign-image job in workflow,
Cosign installed on runner.
```
