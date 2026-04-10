# Phase 01 — CI Runner Deployment and Actions Pinning

## Goal

1. Actually deploy the `ci-runner-01` LXC on pve-test so that the self-hosted GitHub Actions runner comes online (the Terraform stack and Ansible playbook already exist in code — this phase applies them).
2. Pin all remaining GitHub Actions to release tags to reduce supply-chain risk. *(Note: release-tag pins such as `@v4` are mutable and do not fully prevent supply-chain attacks; commit-SHA pinning is required for that guarantee. This phase pins to stable release tags, which is an improvement over unpinned or `@master` refs.)*

## Repository context

The following already exist in the repo and are ready to apply:

- `terraform/lxc/stacks/ci-runner-01/stack.yaml` — LXC spec: 2 vCPU, 4 GB RAM, VMID 141, IP `10.57.0.63/24`, `build_seg` zone
- `terraform/lxc/stacks/ci-runner-01/terragrunt.hcl` — Terragrunt config
- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml` — Ansible playbook to install and register the runner

The `validate.yml` CI workflow already has `terraform-validate` and `ansible-lint` jobs pointing at `runs-on: [self-hosted, pve-test, build]`.

## Current status (2026-04-11) — COMPLETE

- `ci-runner-01` LXC is running on pve-test (VMID 141, IP `10.57.0.63`)
- Runner `ci-runner-pve-test` is **online** with labels `self-hosted`, `pve-test`, `build`, `linux`, `x64`
- `terraform-validate` and `ansible-lint` jobs are executing on the self-hosted runner
- `Validate` workflow was restored to green in commit `49663c8` (`fix(ci): satisfy validate lint checks`)
- SDN egress on `build_seg` is now codified in Terraform + Ansible automation for pve-test
- Issue [#66](https://github.com/stevedwray/proxmox-homelab/issues/66) closed

> **Historical:** As of 2026-04-10, no runner was registered and Validate jobs were queuing indefinitely. The LXC was deployed via Terragrunt and the playbook run that same session. Several bootstrap failures were encountered and resolved; see [`phase-01-ci-runner-problems.md`](phase-01-ci-runner-problems.md) for detail.

## Prerequisites

- Phase 00 (housekeeping) complete
- pve-test Proxmox node is reachable
- `build_seg` SDN zone is live (confirmed in commit `e898386`, issue #52 closed)
- Terragrunt and Ansible are installed on the workstation
- `.env` is sourced (contains `PM_API_TOKEN_ID`, `PM_API_TOKEN_SECRET`, `PM_API_URL`, `LXC_PASSWORD`)
- `gh` CLI is authenticated

## Related issues

- **#66** — feat: deploy self-hosted GitHub Actions runner in build_seg zone *(primary)*
- **#71** — chore(ci): harden and pin GitHub Actions versions *(secondary)*

---

## Part A — Deploy the CI runner LXC

### Step A1 — Apply Terraform via Terragrunt

```bash
cd /home/steve/git/proxmox-homelab
source .env

cd terraform/lxc/stacks/ci-runner-01
terragrunt apply
```

Confirm the plan shows: 1 LXC resource to create, VMID 141, hostname `ci-runner-01`, memory 4096.

### Step A2 — Optional: generate a runner registration token manually

The playbook now generates a token automatically when one is not provided.
Only use this step if you want to override the automatic behavior.
If you do generate one manually, remember that tokens expire after 1 hour and
should be created immediately before running the playbook.

```bash
RUNNER_TOKEN=$(gh api \
  --method POST \
  repos/stevedwray/proxmox-homelab/actions/runners/registration-token \
  --jq .token)
echo "Token acquired: ${RUNNER_TOKEN:0:4}..."  # partial print only
```

### Step A3 — Get the runner LXC IP and run the playbook

The LXC IP is `10.57.0.63`. Run the playbook directly; it will mint a runner
registration token automatically unless you pass one explicitly:

```bash
cd /home/steve/git/proxmox-homelab

# Pin the runner version — check https://github.com/actions/runner/releases for latest stable
RUNNER_VERSION="2.323.0"   # update to latest stable at time of deployment

ansible-playbook \
  -i "10.57.0.63," \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml \
  --extra-vars "runner_version=${RUNNER_VERSION}"
```

To override the automatic token generation, add
`runner_registration_token=${RUNNER_TOKEN}` to `--extra-vars`.

`no_log: true` is set on the configure task — the token will not appear in output.

### Step A4 — Verify runner registration

```bash
gh api repos/stevedwray/proxmox-homelab/actions/runners \
  --jq '.runners[] | {name, status, labels: [.labels[].name]}'
```

Expected output includes:
```json
{
  "name": "ci-runner-pve-test",
  "status": "online",
  "labels": ["self-hosted", "pve-test", "build", "linux", "x64"]
}
```

Also verify at: **GitHub → repo → Settings → Actions → Runners**

### Step A5 — Verify CI jobs run on the self-hosted runner

Push a trivial commit to `dev/pve-test` and check the Actions tab. The `terraform-validate` and `ansible-lint` jobs should show `ci-runner-pve-test` in their run header, not `ubuntu-latest`.

```bash
git commit --allow-empty -m "ci: verify self-hosted runner picks up jobs"
git push origin dev/pve-test
```

Check GitHub Actions — the Validate workflow should complete with both self-hosted jobs green.

### Step A6 — Verify runner survives reboot

```bash
# SSH into the LXC
ssh root@10.57.0.63

# Inside the LXC:
systemctl status "actions.runner.*"
reboot
```

After reboot, confirm runner comes back online in GitHub Settings.

---

## Part B — Pin remaining GitHub Actions (issue #71)

### Current state audit

Check `.github/workflows/security-scan.yml` and `validate.yml` for any unpinned or partially pinned refs:

| Action | Current pin | Status |
|---|---|---|
| `actions/checkout` | `@v4` | ✓ Release-tag pinned |
| `hashicorp/setup-terraform` | `@v3` | ✓ Release-tag pinned |
| `actions/setup-python` | `@v5` | ✓ Release-tag pinned |
| `actions/cache` | `@v4` | ✓ Release-tag pinned |
| `aquasecurity/trivy-action` | `@v0.35.0` | ✓ Release-tag pinned |
| `github/codeql-action/upload-sarif` | `@v3` | ✓ Release-tag pinned |
| `snyk/actions/iac` | `@v1.0.0` | ✓ Release-tag pinned |
| `trufflesecurity/trufflehog` | `@v3.94.3` | ✓ Release-tag pinned |

> **Supply-chain note:** Release tags (`@v4`, `@v3`, etc.) are mutable — a tag can be force-pushed to a different commit. For full supply-chain hardening, pins should be commit SHAs (e.g. `uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2`). The current state is an improvement over `@master` or unpinned refs but does not meet full SHA-pinning standards.

If all are already pinned, this step is verification-only. If any `@master` or unpinned refs are found, pin them to the latest stable tag in a commit on a short-lived branch.

### Verification command

```bash
grep -r 'uses:' .github/workflows/ | grep -v '@' | grep -v '#'
# Expected: no output (all actions have pins)

grep -r 'uses:' .github/workflows/ | grep '@master'
# Expected: no output
```

If findings exist, create a branch `fix/pin-github-actions-<date>`, update the workflow files, and merge to `dev/pve-test`.

---

## Commit and close

```bash
cd /home/steve/git/proxmox-homelab
# (No files changed by the deployment steps — they are infra apply operations)
# If workflow files were updated for pinning, commit only when there are staged changes:
git add .github/workflows/
if git diff --cached --quiet; then
  echo "No workflow changes staged — verification-only path, skipping commit"
else
  git commit -m "chore(ci): verify and pin all GitHub Actions versions (Closes #71)"
  git push origin dev/pve-test
fi
gh issue close 66 --comment "ci-runner-01 deployed and online. Runner picked up terraform-validate and ansible-lint jobs."
gh issue close 71 --comment "All GitHub Actions verified pinned to stable tags. No unpinned refs found."
```

---

## Acceptance criteria

- [x] VMID 141 (`ci-runner-01`) exists on pve-test and is reachable via SSH at `10.57.0.63`
- [x] `systemctl status actions.runner.*` shows active/running inside the LXC
- [x] Runner appears as **online** in GitHub repo Settings → Actions → Runners with labels `self-hosted, pve-test, build`
- [x] `terraform-validate` CI job log header shows `ci-runner-pve-test`
- [x] `ansible-lint` CI job log header shows `ci-runner-pve-test`
- [x] `sast-scan`, `trufflehog`, `snyk-iac` still run on `ubuntu-latest`
- [ ] Runner comes back online after LXC reboot *(not yet verified)*
- [x] No `@master` or unpinned action refs exist in any workflow file
- [x] Issue #66 closed
- [x] Issue #71 closed
- [ ] SDN egress codified in automation — tracked in issue [#77](https://github.com/stevedwray/proxmox-homelab/issues/77)
