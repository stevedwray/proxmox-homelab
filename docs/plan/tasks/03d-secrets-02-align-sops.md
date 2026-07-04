# 03d-secrets-02 — Align SOPS file: fill gaps and fix naming

> Historical task packet.
> This document reflects the earlier secrets-hardening migration workflow.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

COMPLETE

## Phase

Phase 03d — Secrets Delivery Hardening

## GitHub Issue

Not assigned yet.

## Prerequisites

- Task 03d-01 complete — `docs/plan/tasks/03d-secrets-01-gap-analysis.md` exists and committed
- Gap analysis reviewed and understood — do not start this task without reading the gap analysis
- Age private key present at `~/.config/sops/age/keys.txt`

## Objective

`terraform/secrets.enc.yaml` contains every secret needed by every consumer (Terraform,
Ansible, CLI tools), and every key is named exactly as the consumer will look for it in
the environment via `TF_VAR_*` convention or direct env var name. After this task, Task 03
can create the wrapper and run a clean `sops exec-env` against the file without any
consumer failing to find its secret.

## Scope

- Add missing secrets identified in Section 3 of the gap analysis
- Rename mismatched keys identified in Section 4 of the gap analysis
- Do not change any key that is already correctly named
- Do not remove any key from the file

## Out of Scope

- Creating the `with-secrets` wrapper (Task 03)
- Testing with actual Terraform or Ansible runs (Task 03)
- Removing `sync-secrets.sh` or any other files (Task 04)

## Inputs

- `docs/plan/tasks/03d-secrets-01-gap-analysis.md` — the authoritative input for this task
- `terraform/secrets.enc.yaml` — the file to be modified via `sops`

## Expected Outputs

- `terraform/secrets.enc.yaml` updated (re-encrypted automatically by sops on save)
- No plaintext secrets written to disk at any point

## Naming convention

Use these naming rules when adding or renaming keys:

**For Terraform variables** (`sensitive = true` in `variables.tf`):
Use the `TF_VAR_` prefix followed by the exact variable name from `variables.tf`:
```
TF_VAR_pm_api_token_secret
TF_VAR_lxc_password
TF_VAR_portainer_admin_password
```

**For CLI tools and Ansible** that read env vars directly:
Use the name the tool expects verbatim:
```
SONAR_TOKEN        (sonar-scanner reads this directly)
SNYK_TOKEN         (snyk reads this directly)
SOPS_AGE_KEY       (sops reads this directly — only needed if not using key file)
MIKROTIK_USER      (Ansible playbooks lookup('env', 'MIKROTIK_USER'))
MIKROTIK_PASSWORD
CF_DNS_API_TOKEN   (Traefik/Cloudflare DNS-01 challenge — Phase 04)
```

**Renaming an existing key** (when a key exists under the wrong name):
Open the file with `sops terraform/secrets.enc.yaml`, add the new correctly-named key with
the same value, verify, save and close. Then open again and delete the old key. Do not
attempt to rename in a single edit — the two-step process avoids accidental value loss.

**Adding a new key without a known value yet** (Phase 04 placeholders):
Add the key with the placeholder value `CHANGEME_<KEY_NAME>`. This allows Task 03 to verify
the file structure is complete without requiring real credentials for services not yet
deployed. These placeholders will be replaced with real values during Phase 04 deployment.

## How to edit a SOPS file safely

```bash
# Open for editing (decrypts, opens $EDITOR, re-encrypts on save):
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml

# Verify the result by listing key names only (never log the full decrypted file):
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops --decrypt terraform/secrets.enc.yaml | grep -o '^[^:]*'
```

SOPS re-encrypts automatically on editor close. The plaintext is never written to disk —
SOPS decrypts into a temp file in `/dev/shm` on Linux (memory-backed filesystem).

If your `$EDITOR` is not set, `EDITOR=nano` works:
```bash
EDITOR=nano SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml
```

## Constraints and Conventions

- Make one change at a time. After each rename or addition, verify the key list with the
  grep command above before proceeding to the next change.
- Never run `sops --decrypt terraform/secrets.enc.yaml > somefile`. If you need to inspect
  a value, decrypt to stdout and scroll — do not redirect.
- If a key rename would leave a consumer broken during the transition (because the same key
  feeds both the old `.env` flow and the new `sops exec-env` flow), add the new name first
  and keep the old name until Task 04 removes the old flow.
- The `sync-secrets.sh` Bitwarden names are the Bitwarden item names, not necessarily the
  env var names. If `.env.pve-test` revealed a mapping layer (e.g.
  `TF_VAR_pm_api_token_secret=${PROXMOX_TOKEN_SECRET}`), replicate that mapping as the
  correct final key name in `secrets.enc.yaml`.
- Do not store `ANTHROPIC_API_KEY` if it appeared in `sync-secrets.sh`. It is not an
  infrastructure secret consumed by Terraform or Ansible in this repository. Leave it in
  Bitwarden only.

## Acceptance Criteria

- [ ] All gaps from Section 3 of the gap analysis are resolved — every consumer has a
      corresponding key in `secrets.enc.yaml`
- [ ] All naming mismatches from Section 4 are resolved — every key is named exactly as
      its consumer expects
- [ ] Phase 04 placeholder keys are present for all secrets listed in Phase 04 "Secrets
      required" sections (values may be `CHANGEME_*` placeholders)
- [ ] Key list verified after each change — no accidental deletions
- [ ] `git diff terraform/secrets.enc.yaml` shows only added/modified encrypted blobs,
      not any plaintext values
- [ ] The updated `secrets.enc.yaml` decrypts successfully:
      `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.enc.yaml`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Update terraform/secrets.enc.yaml to fill gaps and fix naming mismatches identified
in the gap analysis. No other files are modified in this task.

READ THESE FILES FIRST:
  docs/plan/tasks/03d-secrets-01-gap-analysis.md   (the authoritative input)
  docs/plan/tasks/03d-secrets-02-align-sops.md     (naming convention rules)
  terraform/lxc/variables.tf                        (verify TF_VAR_* names)

BEFORE MAKING ANY CHANGES, confirm the current state:
  SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
    sops --decrypt terraform/secrets.enc.yaml | grep -o '^[^:]*'

FOR EACH GAP (Section 3 of gap analysis):
  Open: SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml
  Add the missing key with either its real value (if known) or CHANGEME_<KEY_NAME>.
  Save and close.
  Verify: SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
    sops --decrypt terraform/secrets.enc.yaml | grep -o '^[^:]*'

FOR EACH NAMING MISMATCH (Section 4 of gap analysis):
  Step 1 — Add the correctly-named key:
    Open the file, add the new key name with the same value as the old key.
    Save and close. Verify key list.
  Step 2 — Delete the old key:
    Open the file again, delete the old incorrectly-named key.
    Save and close. Verify key list.

AFTER ALL CHANGES:
  Verify final state — list all key names:
  SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
    sops --decrypt terraform/secrets.enc.yaml | grep -o '^[^:]*'

  Confirm decryption still works cleanly (exit code 0, no errors).

COMMIT on the existing feat/secrets-hardening branch:
  git add terraform/secrets.enc.yaml
  git commit -m "chore(secrets): align secrets.enc.yaml keys for sops exec-env

Fill gaps and rename keys to match TF_VAR_* convention and direct env
var names expected by each consumer. No new plaintext credentials added.
Placeholder values used for Phase 04 secrets not yet deployed."
  git push origin feat/secrets-hardening

DONE WHEN:
  terraform/secrets.enc.yaml key list matches the required list from the gap analysis.
  All placeholder keys are in place for Phase 04.
  Decryption succeeds cleanly.
```
