# Task 02: Production Environment Model

## Goal

Define how production-specific non-secret configuration is represented and
loaded, so `pve` becomes a first-class environment without contaminating the
default dev workflow.

## Objective

Create a production environment model that clearly defines:

- host targeting
- stack IP allocations
- gateway and subnet inputs
- environment-specific service endpoints
- load order and override rules

## Key Design Constraint

Environment modeling must support:

- `pve-test` remaining the default AI and developer target
- `pve` becoming explicitly selectable
- future canary and one-stack-at-a-time migration workflows

## Deliverables

- documented `.env` layering model
- production env overlay design, likely `.env.pve`
- inventory of required production `LAB_IP_*`, `LAB_GW_*`, and
  `LAB_SUBNET_*` values
- explicit statement of which values remain non-secret and which belong only in
  encrypted secret storage

## Environment Layering Model (Task 02 Decision)

Define non-secret configuration by wrapper path:

### Dev path (`./with-secrets`)

1. `.env` (default-safe baseline non-secret values)
2. `.env.<PVE_ENV>` (environment-specific non-secret overrides; defaults to `.env.pve-test`)

### Production path (`./with-secrets-prod`)

1. `.env.pve` only (intentional production non-secret context)

Load/override behavior:

- `./with-secrets` sources `.env` first, then `.env.<PVE_ENV>`
- caller-supplied `PVE_ENV` must take precedence over values loaded from `.env`
- `./with-secrets-prod` sources `.env.pve` only, then enforces production targeting
- secrets loaded from SOPS always override plaintext env values

Default-safe behavior:

- `./with-secrets` defaults to `PVE_ENV=pve-test`
- `./with-secrets` expects effective `TF_VAR_proxmox_node=pve-test`
- production targeting is explicit and non-default

Production-explicit behavior:

- `./with-secrets-prod` is the preferred production path
- `./with-secrets-prod` enforces `PVE_ENV=pve` and `TF_VAR_proxmox_node=pve`
- `.env.pve` carries non-secret production endpoint/network/service values

## Questions This Task Must Answer

- what should live in `.env`
- what should live in `.env.pve-test`
- what should live in `.env.pve`
- what should never live outside SOPS-encrypted secret material
- how should `PVE_ENV`, `TF_VAR_proxmox_node`, and `TF_WORKSPACE` behave for
  production

## Variable Ownership (Non-Secret vs Secret)

### `.env` baseline (shared, non-secret only)

- default-safe non-secret baseline used by existing automation
- currently includes many pve-test-oriented service/network defaults
- should not include production secret material
- production-specific non-secret overrides should live in `.env.pve`

### `.env.pve-test` overlay (non-secret)

- test host selection (`PROXMOX_HOST`, `TF_VAR_proxmox_api_url`)
- `PVE_ENV=pve-test`
- `TF_VAR_proxmox_node=pve-test`
- `TF_WORKSPACE=pve-test`
- pve-test-specific `LAB_IP_*`, `LAB_GW_*`, `LAB_SUBNET_*` where needed

### `.env.pve` overlay (non-secret)

- production host selection (`PROXMOX_HOST`, `TF_VAR_proxmox_api_url`)
- `PVE_ENV=pve`
- `TF_VAR_proxmox_node=pve`
- `TF_WORKSPACE=pve`
- production-specific `LAB_IP_*`, `LAB_GW_*`, `LAB_SUBNET_*`, and service endpoints

### Never in plaintext env files

- any passwords
- any API token secrets
- any private keys
- any breakglass secret material
- any provider credential secrets

Those values belong only in SOPS-encrypted files:

- `terraform/secrets.enc.yaml` (dev)
- `terraform/secrets.pve.enc.yaml` (prod)

## Files Likely Involved

- [.env.template](/home/steve/git/proxmox-homelab/.env.template:1)
- `.env.pve-test`
- new `.env.pve`
- [with-secrets](/home/steve/git/proxmox-homelab/with-secrets:1)

## Dependencies

- task 01 design should inform how production env material is accessed

## Current Planning Note

As of May 22, 2026, production credential validation is ahead of production
environment modeling:

- the production Proxmox token has already been validated successfully
- there is still no finalized `.env.pve` overlay in the repo
- the read-only production auth check required explicit non-secret overrides for
  the production API URL and host because local defaults were still
  `pve-test`-oriented

This means Task 02 should treat `.env.pve` and production non-secret targeting
as an active gap, not a solved prerequisite.

## Explicit Target Selection Rules

To avoid accidental production targeting while still enabling production work:

- `.env` must remain default-safe (`pve-test` expectations)
- production targeting must require explicit selection via one of:
  - `./with-secrets-prod ...` (preferred)
  - `ALLOW_PVE=true PVE_ENV=pve ./with-secrets ...` (exception path)
- `.env.pve` must exist before production non-secret overlays are considered complete
- `TF_VAR_proxmox_node` and `TF_WORKSPACE` must align with `PVE_ENV`
  (`pve-test` with `pve-test`, `pve` with `pve`)

## Validation

- a production env overlay can be sourced or injected without overwriting dev
  defaults accidentally
- the effective target node resolves to `pve` when intended
- the effective target node still resolves to `pve-test` by default
- environment overlays contain no secrets

## Risks

- mixing secret and non-secret values in the env model
- allowing `.env` defaults to drift toward production accidentally
- stale variable names causing network or service mis-targeting

## Suggested Branch

- `work/productionize-02-production-env-model`
