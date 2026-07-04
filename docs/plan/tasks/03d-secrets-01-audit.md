# 03d-secrets-01 — Audit: decrypt secrets.enc.yaml and map all consumers

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

- `sops` CLI installed: `sops --version`
- Age private key present at `~/.config/sops/age/keys.txt`
- `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.enc.yaml`
  succeeds without error

## Objective

Produce a written gap analysis document that maps every secret currently in `sync-secrets.sh`
and `secrets.enc.yaml` to its actual consumer (Terraform variable, Ansible var, Docker
Compose env var, CLI tool). Identify every gap (secrets missing from `secrets.enc.yaml`) and
every naming mismatch (key names that will not be found by consumers via `sops exec-env`).

No files are modified in this task. All output is a new document committed to the repo.

## Why this task must come first

`sops exec-env terraform/secrets.enc.yaml -- <command>` injects the top-level YAML keys from
the encrypted file as environment variables into the subprocess. For this to work:

1. Every secret that a consumer needs must be present in `secrets.enc.yaml`.
2. Each key name must exactly match what the consumer looks for in the environment.

For Terraform: `var.pm_api_token_secret` is satisfied by the env var
`TF_VAR_pm_api_token_secret`. If the SOPS file has `PROXMOX_TOKEN_SECRET` instead, Terraform
will not find it. The current `sync-secrets.sh` uses uppercase names that may not align with
Terraform's `TF_VAR_*` convention or with Ansible `vars` references.

Until this mapping is documented, no other task in Phase 03d should begin.

## Scope

- Read `sync-secrets.sh` (list of secrets pulled from Bitwarden)
- Decrypt `terraform/secrets.enc.yaml` and list key names only (do not log values)
- Read `terraform/lxc/variables.tf` to identify all `sensitive = true` Terraform variables
- Read Ansible group_vars and any playbooks that reference `lookup('env', ...)` or `{{ lookup('env', ...) }}`
- Read Phase 04 task docs for all "Secrets required" sections — list every secret that Phase 04 will need
- Read the `docs/plan/README.md` security scanning section for `sonar-scanner` invocation
- Check for any `.env.pve-test` file in the repo root
- Produce a gap analysis document

## Out of Scope

- Modifying `secrets.enc.yaml`
- Creating the `with-secrets` wrapper
- Removing any files
- Modifying any documentation other than creating the output document

## Inputs

- `sync-secrets.sh` — the ENV_VARS list is the current inventory of Bitwarden-held secrets
- `terraform/secrets.enc.yaml` — the SOPS-encrypted file (decrypt to list keys)
- `terraform/lxc/variables.tf` — all `sensitive = true` variables must be satisfied
- `terraform/lxc/main.tf` — provider block shows which vars feed the Proxmox API token
- `docs/plan/phase-04-core-shared-services.md` — all "Secrets required" sections
- `docs/plan/tasks/04-core-services-01-deploy-authentik.md` — prerequisites list
- `docs/plan/tasks/04-core-services-03-deploy-traefik.md` — secrets required
- `docs/plan/tasks/04-core-services-04-deploy-step-ca.md` — secrets required
- `docs/plan/tasks/04-core-services-05-deploy-monitoring.md` — secrets required
- `docs/plan/README.md` — security scanning section
- `.env.pve-test` (if it exists) — may contain mappings not in `secrets.enc.yaml`

## Expected Outputs

A new file: `docs/plan/tasks/03d-secrets-01-gap-analysis.md`

This file must contain four sections:

### Section 1 — SOPS file inventory

List every top-level key name currently in `terraform/secrets.enc.yaml`.
Do not include values. Example format:

```
Keys currently in terraform/secrets.enc.yaml:
  TF_VAR_pm_api_token_secret
  TF_VAR_lxc_password
  ...
```

### Section 2 — Consumer mapping

A table mapping each consumer to the environment variable name it expects, the current SOPS
key name (if present), and whether there is a gap or mismatch:

| Consumer | Expects env var | SOPS key | Status |
|---|---|---|---|
| Terraform `var.pm_api_token_secret` | `TF_VAR_pm_api_token_secret` | (key name from SOPS file) | Match / Mismatch / Missing |
| Terraform `var.lxc_password` | `TF_VAR_lxc_password` | ... | ... |
| Terraform `var.portainer_admin_password` | `TF_VAR_portainer_admin_password` | ... | ... |
| sonar-scanner | `SONAR_TOKEN` | ... | ... |
| snyk | `SNYK_TOKEN` | ... | ... |
| SOPS CLI itself | `SOPS_AGE_KEY` (or `SOPS_AGE_KEY_FILE`) | ... | ... |
| MikroTik Ansible playbook | `MIKROTIK_USER`, `MIKROTIK_PASSWORD` | ... | ... |
| (one row per consumer found in the audit) | | | |

### Section 3 — Gaps (missing from secrets.enc.yaml)

List every secret referenced by a consumer that is not present in `secrets.enc.yaml` at all.
These must be added in Task 02 before Task 03 can succeed.

Also list every Phase 04 secret that does not yet exist in `secrets.enc.yaml` — these will be
new additions required before Phase 04 deployment begins (they do not need to have real values
yet; placeholder structure can be added and values populated before each deploy pass).

### Section 4 — Naming mismatches

List every case where a key exists in `secrets.enc.yaml` but under a name that does not match
what the consumer expects via `sops exec-env`. Include the current name and the required name.
These must be renamed in Task 02.

## Constraints and Conventions

- Do not decrypt to a file. Use `sops --decrypt terraform/secrets.enc.yaml` to view output
  in the terminal only. Close the terminal session or clear the scrollback after the audit.
- Do not include secret values anywhere in the gap analysis document — key names only.
- The gap analysis document is committed to the repo. It must never contain credentials.
- If `.env.pve-test` exists in the repo root, read it carefully — it may reveal mappings
  (e.g. `TF_VAR_pm_api_token_secret=${PROXMOX_TOKEN_SECRET}`) that explain how the current
  approach bridges naming differences. These mappings must be preserved in Task 02.
- If `.env.pve-test` is not present in the working directory, note that in the analysis.

## Acceptance Criteria

- [ ] `docs/plan/tasks/03d-secrets-01-gap-analysis.md` exists and is committed
- [ ] Section 1 lists all SOPS key names (values redacted)
- [ ] Section 2 table covers every `sensitive = true` Terraform variable, every CLI tool
      that reads from the environment (sonar-scanner, snyk, sops), and every Ansible
      lookup of environment variables
- [ ] Section 3 lists every gap (present in sync-secrets.sh or required by a consumer but
      absent from secrets.enc.yaml)
- [ ] Section 3 includes all Phase 04 secrets not yet in secrets.enc.yaml
- [ ] Section 4 lists every naming mismatch with old name → required name
- [ ] No secret values appear anywhere in the committed document

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Audit the current secrets landscape and produce a gap analysis document.
This task makes NO code changes — it only reads files and produces one new document.

READ THESE FILES BEFORE DOING ANYTHING ELSE:
  sync-secrets.sh
  terraform/lxc/variables.tf
  terraform/lxc/main.tf
  docs/plan/phase-03d-secrets-hardening.md
  docs/plan/phase-04-core-shared-services.md
  docs/plan/tasks/04-core-services-01-deploy-authentik.md
  docs/plan/tasks/04-core-services-03-deploy-traefik.md
  docs/plan/tasks/04-core-services-04-deploy-step-ca.md
  docs/plan/tasks/04-core-services-05-deploy-monitoring.md
  docs/plan/README.md   (security scanning section)

CHECK FOR OPTIONAL FILES:
  .env.pve-test (may or may not exist — note its presence and content if found)

DECRYPT AND LIST SOPS KEYS (key names only — do not log values anywhere):
  SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.enc.yaml

  From the decrypted output, record only the key names (left side of each line).
  Do not include any values in the gap analysis document.

SEARCH FOR ANSIBLE ENVIRONMENT LOOKUPS:
  Grep ansible/ for: lookup('env', and lookup("env",
  List every environment variable name that Ansible playbooks read from the environment.

BUILD THE GAP ANALYSIS:
  Produce docs/plan/tasks/03d-secrets-01-gap-analysis.md with the four sections described
  in the task document at docs/plan/tasks/03d-secrets-01-audit.md.

  The document must contain ONLY key names, never values.

COMMIT (no branch needed — this is a documentation commit):
  git checkout -b feat/secrets-hardening baseline/teardown-validated
  git add docs/plan/tasks/03d-secrets-01-gap-analysis.md
  git commit -m "docs(secrets): add Phase 03d gap analysis

Audit of secrets.enc.yaml vs all consumers. Documents gaps and naming
mismatches to be resolved in Task 02 before wrapper creation."
  git push origin feat/secrets-hardening

DONE WHEN:
  docs/plan/tasks/03d-secrets-01-gap-analysis.md is committed and pushed.
  No secret values appear anywhere in the commit.
```
