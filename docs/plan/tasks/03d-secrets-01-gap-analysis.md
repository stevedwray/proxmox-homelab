# 03d-secrets-01 — Gap Analysis: secrets.enc.yaml vs all consumers

> Historical task packet.
> This document reflects the earlier secrets-hardening migration workflow.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

COMPLETE

## Phase

Phase 03d — Secrets Delivery Hardening

## Produced by

Automated audit against:
- `sync-secrets.sh` ENV_VARS list (Bitwarden inventory)
- `terraform/secrets.enc.yaml` top-level keys (decrypted, key names only)
- `terraform/lxc/variables.tf` `sensitive = true` variables
- `terraform/lxc/main.tf` Proxmox provider block
- `.env.pve-test` (reveals mapping layer between Bitwarden names and TF_VAR_* names)
- `.env.template` (full secret inventory including Phase 04 placeholders)
- `docs/plan/tasks/04-core-services-*.md` prerequisites sections

---

## Section 1 — SOPS file inventory

Keys currently in `terraform/secrets.enc.yaml` (key names only, no values):

```
proxmox_token_secret
lxc_password
portainer_admin_password
netbox_db_password
netbox_redis_password
netbox_redis_cache_password
netbox_secret_key
netbox_api_token_pepper
netbox_superuser_password
netbox_superuser_api_token
mikrotik_user
mikrotik_password
```

Total: 12 keys present.

---

## Section 2 — Consumer mapping

`sops exec-env terraform/secrets.enc.yaml -- <cmd>` injects each top-level YAML key as an
environment variable with that exact key name. Consumers must reference the exact name.

### 2a — Terraform (reads `TF_VAR_<variable_name>`)

| Consumer | Expects env var | SOPS key | Status |
|---|---|---|---|
| `var.pm_api_token_secret` | `TF_VAR_pm_api_token_secret` | `proxmox_token_secret` | **Mismatch** |
| `var.lxc_password` | `TF_VAR_lxc_password` | `lxc_password` | **Mismatch** (missing `TF_VAR_` prefix) |
| `var.portainer_admin_password` | `TF_VAR_portainer_admin_password` | `portainer_admin_password` | **Mismatch** (missing `TF_VAR_` prefix) |

Note: Non-sensitive Terraform vars (`proxmox_api_url`, `pm_api_token_id`, `proxmox_node`,
`proxmox_host`, `portainer_server_ip`, `registry_host`, `apt_cacher_host`) are not secrets
and should be supplied via tfvars or environment outside SOPS.

### 2b — Ansible (reads env vars directly via `lookup('env', ...)`)

| Consumer | Expects env var | SOPS key | Status |
|---|---|---|---|
| MikroTik playbook | `MIKROTIK_USER` | `mikrotik_user` | **Mismatch** (case) |
| MikroTik playbook | `MIKROTIK_PASSWORD` | `mikrotik_password` | **Mismatch** (case) |

### 2c — Docker Compose (reads env vars directly)

| Consumer | Expects env var | SOPS key | Status |
|---|---|---|---|
| netbox | `NETBOX_DB_PASSWORD` | `netbox_db_password` | **Mismatch** (case) |
| netbox | `NETBOX_REDIS_PASSWORD` | `netbox_redis_password` | **Mismatch** (case) |
| netbox | `NETBOX_REDIS_CACHE_PASSWORD` | `netbox_redis_cache_password` | **Mismatch** (case) |
| netbox | `NETBOX_SECRET_KEY` | `netbox_secret_key` | **Mismatch** (case) |
| netbox | `NETBOX_API_TOKEN_PEPPER` | `netbox_api_token_pepper` | **Mismatch** (case) |
| netbox | `NETBOX_SUPERUSER_PASSWORD` | `netbox_superuser_password` | **Mismatch** (case) |
| netbox | `NETBOX_SUPERUSER_API_TOKEN` | `netbox_superuser_api_token` | **Mismatch** (case) |
| harbor | `HARBOR_ADMIN_PASSWORD` | _(none)_ | **Missing** |
| harbor | `HARBOR_DB_PASSWORD` | _(none)_ | **Missing** |

### 2d — CLI tools (read env vars directly)

| Consumer | Expects env var | SOPS key | Status |
|---|---|---|---|
| sonar-scanner | `SONAR_TOKEN` | _(none)_ | **Missing** |
| snyk | `SNYK_TOKEN` | _(none)_ | **Missing** |
| sops itself | `SOPS_AGE_KEY_FILE` (via `with-secrets` wrapper) | N/A — set by wrapper | **OK** |

Note: `SOPS_AGE_KEY` (full key content) was in `sync-secrets.sh` as a Bitwarden item name
but is not an infrastructure secret consumed by Terraform or Ansible in this repo. The
`with-secrets` wrapper wires `SOPS_AGE_KEY_FILE` automatically. Do not add `SOPS_AGE_KEY`
to `secrets.enc.yaml`.

Note: `ANTHROPIC_API_KEY` was in `sync-secrets.sh` but is not a secret consumed by any
infrastructure component in this repo. Leave it in Bitwarden only — do not add to
`secrets.enc.yaml`.

### 2e — Phase 04 secrets (all currently missing from secrets.enc.yaml)

| Consumer | Expects env var | SOPS key | Status |
|---|---|---|---|
| Authentik (deploy-authentik-stack.yml) | `AUTHENTIK_SECRET_KEY` | _(none)_ | **Missing** |
| Authentik | `AUTHENTIK_POSTGRES_PASSWORD` | _(none)_ | **Missing** |
| Authentik | `AUTHENTIK_SUPERUSER_PASSWORD` | _(none)_ | **Missing** |
| Authentik | `AUTHENTIK_SUPERUSER_API_TOKEN` | _(none)_ | **Missing** |
| Traefik (Cloudflare DNS-01) | `CF_DNS_API_TOKEN` | _(none)_ | **Missing** |
| step-ca | `STEP_CA_PASSWORD` | _(none)_ | **Missing** |
| step-ca | `STEP_CA_PROVISIONER_PASSWORD` | _(none)_ | **Missing** |
| Grafana | `GRAFANA_ADMIN_PASSWORD` | _(none)_ | **Missing** |
| Grafana (Authentik OIDC) | `GRAFANA_OAUTH_CLIENT_SECRET` | _(none)_ | **Missing** |

---

## Section 3 — Gaps (missing from secrets.enc.yaml)

### 3a — Currently consumed, missing entirely

These secrets are consumed by Phase 03 or earlier services but are absent from
`secrets.enc.yaml`. They must be added in Task 02 and should receive real values.

| Key to add | Consumer | Value source |
|---|---|---|
| `SONAR_TOKEN` | sonar-scanner (local dev + CI) | Available in `.env.pve-test` |
| `SNYK_TOKEN` | snyk CLI | Available in Bitwarden |
| `HARBOR_ADMIN_PASSWORD` | Harbor Docker Compose | Derive from `lxc_password` pattern (same as SERVICE_PASSWORD) |
| `HARBOR_DB_PASSWORD` | Harbor Docker Compose | Derive: `harbor_db_<lxc_password>` |

### 3b — Phase 04 placeholders (not yet deployed; add before Phase 04 begins)

Add these with `CHANGEME_<KEY_NAME>` placeholder values. Real values must be set before
the corresponding Phase 04 task is executed.

| Key to add | Consumer | When to populate |
|---|---|---|
| `AUTHENTIK_SECRET_KEY` | Authentik stack | Before task 04-01 |
| `AUTHENTIK_POSTGRES_PASSWORD` | Authentik stack | Before task 04-01 |
| `AUTHENTIK_SUPERUSER_PASSWORD` | Authentik stack | Before task 04-01 |
| `AUTHENTIK_SUPERUSER_API_TOKEN` | Authentik stack | After first-boot init in task 04-01 |
| `CF_DNS_API_TOKEN` | Traefik DNS-01 challenge | Before task 04-03 |
| `STEP_CA_PASSWORD` | step-ca bootstrap | Before task 04-04 |
| `STEP_CA_PROVISIONER_PASSWORD` | step-ca provisioner | Before task 04-04 |
| `GRAFANA_ADMIN_PASSWORD` | Grafana | Before task 04-05 |
| `GRAFANA_OAUTH_CLIENT_SECRET` | Grafana OIDC | After Authentik config in task 04-05 |

---

## Section 4 — Naming mismatches (present but incorrectly named)

All 12 existing keys are misnamed relative to their consumers. All must be renamed in
Task 02. The two-step process (add new name → verify → remove old name) is required per
the Task 02 constraint to avoid accidental value loss.

### 4a — Terraform TF_VAR_* mismatches

| Current key | Required key | Rename action |
|---|---|---|
| `proxmox_token_secret` | `TF_VAR_pm_api_token_secret` | Rename (name AND prefix change) |
| `lxc_password` | `TF_VAR_lxc_password` | Rename (add `TF_VAR_` prefix) |
| `portainer_admin_password` | `TF_VAR_portainer_admin_password` | Rename (add `TF_VAR_` prefix) |

### 4b — Uppercase convention mismatches (Ansible + Docker Compose)

| Current key | Required key | Rename action |
|---|---|---|
| `netbox_db_password` | `NETBOX_DB_PASSWORD` | Rename (uppercase) |
| `netbox_redis_password` | `NETBOX_REDIS_PASSWORD` | Rename (uppercase) |
| `netbox_redis_cache_password` | `NETBOX_REDIS_CACHE_PASSWORD` | Rename (uppercase) |
| `netbox_secret_key` | `NETBOX_SECRET_KEY` | Rename (uppercase) |
| `netbox_api_token_pepper` | `NETBOX_API_TOKEN_PEPPER` | Rename (uppercase) |
| `netbox_superuser_password` | `NETBOX_SUPERUSER_PASSWORD` | Rename (uppercase) |
| `netbox_superuser_api_token` | `NETBOX_SUPERUSER_API_TOKEN` | Rename (uppercase) |
| `mikrotik_user` | `MIKROTIK_USER` | Rename (uppercase) |
| `mikrotik_password` | `MIKROTIK_PASSWORD` | Rename (uppercase) |

---

## Section 5 — Expected final key list (post-Task 02)

After Task 02 completes, `terraform/secrets.enc.yaml` should contain exactly these keys:

```
# Terraform credentials (TF_VAR_* prefix)
TF_VAR_pm_api_token_secret
TF_VAR_lxc_password
TF_VAR_portainer_admin_password

# NetBox stack (Docker Compose)
NETBOX_DB_PASSWORD
NETBOX_REDIS_PASSWORD
NETBOX_REDIS_CACHE_PASSWORD
NETBOX_SECRET_KEY
NETBOX_API_TOKEN_PEPPER
NETBOX_SUPERUSER_PASSWORD
NETBOX_SUPERUSER_API_TOKEN

# MikroTik (Ansible)
MIKROTIK_USER
MIKROTIK_PASSWORD

# Harbor stack (Docker Compose)
HARBOR_ADMIN_PASSWORD
HARBOR_DB_PASSWORD

# CLI tools
SONAR_TOKEN
SNYK_TOKEN

# Phase 04 placeholders (CHANGEME_ values until deployment)
AUTHENTIK_SECRET_KEY
AUTHENTIK_POSTGRES_PASSWORD
AUTHENTIK_SUPERUSER_PASSWORD
AUTHENTIK_SUPERUSER_API_TOKEN
CF_DNS_API_TOKEN
STEP_CA_PASSWORD
STEP_CA_PROVISIONER_PASSWORD
GRAFANA_ADMIN_PASSWORD
GRAFANA_OAUTH_CLIENT_SECRET
```

Total: 28 keys.

---

## Section 6 — Files to audit in docs/reference/secrets-management.md

`docs/reference/secrets-management.md` currently lists the old lowercase key names in its
table. This file must be rewritten in Task 04 to:
- Reflect the new key names
- Remove the Bitwarden CLI / `sync-secrets.sh` workflow
- Document the `with-secrets` wrapper usage
- Remove the local decrypt-to-file pattern

## Section 7 — Files referencing .env that must be updated in Task 04

Found via grep (active docs and scripts; done/ not included):

| File | References |
|---|---|
| `docs/plan/README.md` line 114 | `source .env && sonar-scanner` in security scan table |
| `docs/plan/tasks/04-core-services-01-deploy-authentik.md` | prerequisites: `exist in .env` |
| `docs/plan/tasks/04-core-services-03-deploy-traefik.md` | prerequisites: `CF_DNS_API_TOKEN set in .env` |
| `docs/plan/tasks/04-core-services-04-deploy-step-ca.md` | prerequisites: `STEP_CA_PASSWORD ... set in .env` |
| `docs/plan/tasks/04-core-services-05-deploy-monitoring.md` | `Add GRAFANA_ADMIN_PASSWORD ... to .env.template` |
| `scripts/setup-dev-env.sh` | `setup_environment()` and `show_completion()` reference `.env.template` |
| `docs/reference/secrets-management.md` | full rewrite required |
