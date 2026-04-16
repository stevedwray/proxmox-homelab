# 03d-secrets-03 — Create `with-secrets` wrapper and test all consumers

## Status

PENDING

## Phase

Phase 03d — Secrets Delivery Hardening

## GitHub Issue

Not assigned yet.

## Prerequisites

- Task 03d-02 complete — `secrets.enc.yaml` has all required keys, correctly named
- `sops --version` works
- `tofu` (OpenTofu) available locally
- `ansible-playbook` available locally
- At least one Terragrunt stack has been previously applied (pve-test must be reachable for
  a `tofu plan` to produce meaningful output — a `plan` without a running Proxmox target
  will still validate credential injection even if it cannot contact the API)
- **Do not remove `sync-secrets.sh` or `.env` before this task is complete and signed off.**
  The old approach must remain intact as a fallback throughout this task.

## Objective

A `with-secrets` script exists at the repo root, passes shellcheck, and successfully injects
credentials into every consumer that previously relied on `source .env`. Each consumer is
tested explicitly. The old `.env` approach is not yet removed — this task is pure
addition and verification.

## Scope

- Create `with-secrets` at repo root
- Test: `./with-secrets tofu plan` in a Terragrunt stack (credential injection verified)
- Test: `./with-secrets ansible-playbook` against pve-test (SSH + API auth verified)
- Test: `./with-secrets sonar-scanner` (SONAR_TOKEN injection verified)
- Test: `./with-secrets snyk` if snyk is used locally (SNYK_TOKEN injection verified)

## Out of Scope

- Removing `sync-secrets.sh`, `.env.template`, or any other files (Task 04)
- Updating documentation other than the wrapper script itself (Task 04)
- Running `tofu apply` — `tofu plan` is sufficient to verify credential injection

## Inputs

- `docs/plan/tasks/03d-secrets-01-gap-analysis.md` — confirms what each consumer expects
- `terraform/secrets.enc.yaml` — must be complete and correctly named (Task 02 output)
- `terraform/lxc/variables.tf` — confirms TF_VAR_* variable names

## Expected Outputs

- `with-secrets` (executable script at repo root)

## The `with-secrets` script

```bash
#!/bin/bash
# with-secrets — run a command with infrastructure secrets injected from SOPS.
#
# Decrypts terraform/secrets.enc.yaml in memory and injects its key-value pairs
# as environment variables into the named subprocess. Nothing is written to disk.
#
# Usage:
#   ./with-secrets tofu plan
#   ./with-secrets ansible-playbook -i inventory/dev.yml playbook.yml
#   ./with-secrets sonar-scanner
#
# The age private key is read from ~/.config/sops/age/keys.txt automatically.
# Ensure the key exists before running this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_FILE="${SCRIPT_DIR}/terraform/secrets.enc.yaml"
AGE_KEY_FILE="${HOME}/.config/sops/age/keys.txt"

if [[ ! -f "${AGE_KEY_FILE}" ]]; then
    echo "ERROR: age private key not found at ${AGE_KEY_FILE}" >&2
    echo "Retrieve from Bitwarden: 'proxmox-homelab age private key'" >&2
    echo "Then: mkdir -p ~/.config/sops/age && install -m 600 /dev/stdin ${AGE_KEY_FILE}" >&2
    exit 1
fi

if [[ ! -f "${SECRETS_FILE}" ]]; then
    echo "ERROR: secrets file not found at ${SECRETS_FILE}" >&2
    exit 1
fi

if [[ $# -eq 0 ]]; then
    echo "Usage: $(basename "${BASH_SOURCE[0]}") <command> [args...]" >&2
    exit 1
fi

exec env SOPS_AGE_KEY_FILE="${AGE_KEY_FILE}" \
    sops exec-env "${SECRETS_FILE}" -- "$@"
```

Key properties of this script:
- `exec` replaces the wrapper process with the child — no lingering wrapper PID
- `SOPS_AGE_KEY_FILE` is set automatically — the operator does not need it in their shell
- Explicit error messages guide recovery if the age key is missing
- Passes shellcheck cleanly

## Test procedure

Run each test without `.env` sourced. If `.env` is currently sourced in the active shell,
open a new terminal before testing.

### Test 1 — Terraform credential injection

```bash
# Choose any stack that has been previously initialised
cd terraform/lxc/stacks/ci-runner-01

# Run plan via the wrapper — should authenticate to Proxmox and list planned changes
# (or produce a permissions error from Proxmox, not a "variable not set" error)
../../with-secrets tofu plan -var-file=../../ci-validate.tfvars 2>&1 | head -40

# Confirm TF_VAR_pm_api_token_secret was received (look for auth attempt, not "missing variable"):
# - PASS: output contains "Planning..." or a Proxmox API error (credentials were read)
# - FAIL: output contains "No value for required variable" or "variable not provided"
```

### Test 2 — Ansible authentication

```bash
# Ping pve-test using the wrapper to inject credentials
./with-secrets ansible-playbook \
  -i ansible/inventory/dev.yml \
  ansible/00-initial-setup/proxmox-initial-tests.yml \
  --limit pve-test \
  --check 2>&1 | head -20

# PASS: playbook runs and reaches pve-test (even if tasks fail due to missing services)
# FAIL: authentication errors or "variable undefined" before any task runs
```

### Test 3 — sonar-scanner token injection

```bash
# Verify SONAR_TOKEN is injected (use --dry-run or check auth only — do not run full scan)
./with-secrets env | grep SONAR_TOKEN
# PASS: shows SONAR_TOKEN=<value>
# FAIL: SONAR_TOKEN is absent from output

# Full scan is not required here — token presence is sufficient for this test
```

### Test 4 — snyk token injection (if snyk is used locally)

```bash
./with-secrets env | grep SNYK_TOKEN
# PASS: shows SNYK_TOKEN=<value>
```

### Test 5 — No secrets in parent shell after subprocess exits

```bash
# Confirm the parent shell is not modified
./with-secrets env | grep TF_VAR_ | wc -l   # shows count (non-zero)
env | grep TF_VAR_ | wc -l                   # should be 0 — parent shell is unmodified
```

## Constraints and Conventions

- Do not source `.env` before running any test. The entire point is that the wrapper works
  without `.env`.
- If a test fails because a `CHANGEME_*` placeholder value is present in the SOPS file for
  a secret that has a real value in the current `.env`, update `secrets.enc.yaml` with the
  real value (via `sops terraform/secrets.enc.yaml`) and re-run the test. Do not add the
  real value to the `.env.template` or any other file.
- If a test passes for some consumers but fails for others, stop and record which consumers
  failed — do not proceed to Task 04 until all consumers pass.
- `shellcheck with-secrets` must pass with zero errors.

## Acceptance Criteria

- [ ] `with-secrets` exists at repo root, mode 0755
- [ ] `shellcheck with-secrets` passes with zero errors
- [ ] Test 1 passes: `./with-secrets tofu plan` reaches Proxmox API authentication
      (no "variable not provided" errors)
- [ ] Test 2 passes: `./with-secrets ansible-playbook` reaches pve-test without
      authentication errors from missing credentials
- [ ] Test 3 passes: `./with-secrets env | grep SONAR_TOKEN` shows a non-empty value
- [ ] Test 5 passes: parent shell has no `TF_VAR_*` vars after subprocess exits
- [ ] No `.env` was sourced during any test

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.
Branch: feat/secrets-hardening (already exists from Task 01)

TASK: Create the with-secrets wrapper script and verify it works for every secret consumer.
Do NOT remove any existing files in this task. Do NOT modify sync-secrets.sh or .env.template.

READ THESE FILES FIRST:
  docs/plan/tasks/03d-secrets-03-wrapper-and-test.md   (this task — full test procedure)
  docs/plan/tasks/03d-secrets-01-gap-analysis.md        (confirms consumer expectations)
  terraform/lxc/variables.tf                             (TF_VAR_* names)

CREATE THE WRAPPER:
  Write with-secrets at the repo root using the exact script content in this task document.
  chmod +x with-secrets
  shellcheck with-secrets   # must pass with zero errors

RUN TESTS 1–5 IN ORDER:
  For each test, open a fresh shell (or unset all TF_VAR_* and sourced .env vars) before
  running. Record the result (PASS/FAIL) for each test.

  If any test fails because a CHANGEME_* placeholder is in secrets.enc.yaml:
    SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml
    Replace the CHANGEME_* value with the real credential.
    Re-run the failing test.

  If any test fails for any other reason: STOP. Do not proceed to Task 04.
  Report the failure clearly — which consumer, what error, what was expected.

COMMIT ONCE ALL TESTS PASS:
  git add with-secrets
  git commit -m "feat(secrets): add with-secrets wrapper for sops exec-env delivery

Replaces source .env workflow. Decrypts terraform/secrets.enc.yaml in
memory and injects secrets into subprocesses only. Nothing written to disk."
  git push origin feat/secrets-hardening

DONE WHEN:
  All five tests pass.
  with-secrets is committed.
  No .env was sourced at any point during testing.
```
