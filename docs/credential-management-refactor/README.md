# Credential Management Refactor

## Purpose

This document tree defines the credential-management model we want after the
productionization work:

- production and test secrets stay in SOPS as the source of truth
- day-2 stack management can rotate the credentials that are safe to rotate
- unsafe or bootstrap-only credentials are explicitly classified instead of
  being treated as generic passwords
- `pve-test` becomes the proving ground for new credential-management flows
  before they are used on `pve`

This is not just a scripting task. The current repo contains several different
secret lifecycles, and they need different handling.

## Plan Documents

- [Execution Plan](./plan.md)

## Why This Refactor Exists

We now have a working production `pve` stack set and a first day-2 credential
rotation script. That script proved the basic pattern:

1. update the SOPS source of truth
2. rerun the owning stack reconcile
3. verify the live service converges cleanly

That pattern works for a small set of credentials, but it does not generalize
to every secret already stored in SOPS.

The current problems fall into a few recurring classes:

- bootstrap-only or effectively immutable secrets such as crypto keys and CA
  secrets
- secrets where the playbook authenticates with the same value it would be
  changing
- shared secrets consumed by multiple stacks
- external-provider credentials that this repo consumes but does not mint
- service-internal credentials, such as database passwords, that need a
  coordinated migration rather than an env-file rewrite

## Current State

Supported day-2 rotation is documented in
[docs/stack-lifecycle-refactor/day-2-credential-rotation.md](/home/steve/git/proxmox-homelab/docs/stack-lifecycle-refactor/day-2-credential-rotation.md:1).

Today we have a safe scripted path for:

- `AUTHENTIK_STEVE_PASSWORD`
- `NETBOX_SUPERUSER_PASSWORD`
- `GRAFANA_OAUTH_CLIENT_SECRET`
- `HARBOR_OIDC_CLIENT_SECRET`
- `PORTAINER_OAUTH_CLIENT_SECRET`

Everything else should currently be treated as unsupported until we design a
specific reconcile path for it.

## Target End State

We want each SOPS-managed credential to be in one of these categories:

| Category | Meaning | Expected automation |
|---|---|---|
| `rotate-now` | Safe to regenerate and converge through day-2 automation | One command updates SOPS and reconciles the owning stack |
| `rotate-with-current-auth` | Safe to rotate, but requires the old and new credential in one controlled flow | Dedicated rotation command with cutover validation |
| `replace-external` | Minted outside the repo, then injected into SOPS and reconciled | Operator creates replacement first, repo converges consumers second |
| `preserve-only` | Should be backed up and preserved, not casually rotated | No generic rotate workflow |
| `do-not-automate` | Rotation is too risky without a deeper service migration or redesign | Manual, service-specific procedure only |

The important shift is that we stop treating all credentials as equivalent.

## Key Design Rules

- SOPS remains the source of truth.
- Rotation logic must be stack-aware, not generic string replacement.
- A credential is not "supported" until the reconcile path is proven on
  `pve-test`.
- Any flow that changes a live admin password must model both the current and
  desired credential.
- Shared credentials should be split per service where that reduces coupling.
- Database, Redis, CA, and application crypto secrets need service-specific
  procedures and should not be mixed into the easy path.

## Planned Workstreams

### 1. Classification Pass

Create and maintain an inventory of all SOPS-managed credentials and assign
each one to an automation class.

Expected first-pass outcomes:

- easy candidates: OAuth client secrets and externally issued tokens with a
  clean reconcile path
- medium candidates: admin passwords where the playbook can be taught a
  current-versus-desired flow
- hard candidates: DB/Redis passwords and shared breakglass credentials
- preserve-only / do-not-automate: `AUTHENTIK_SECRET_KEY`, step-ca bootstrap
  secrets, and similar identity-bearing values

### 2. Safe Rotation Framework

Extend the current script model into a framework that can:

- plan before execute
- show the owning stack and expected blast radius
- require an explicit stack-specific reconcile
- refuse unsupported credentials by default

### 3. Current-vs-Desired Credential Support

Add targeted playbook support for services where day-2 password rotation is
possible but currently blocked by a chicken-and-egg authentication problem.

Likely early candidates:

- `GRAFANA_ADMIN_PASSWORD`
- `HARBOR_ADMIN_PASSWORD`
- `TF_VAR_portainer_admin_password`

### 4. External Replacement Flows

Document and automate the "consume but do not mint" class of credentials.

Likely candidates:

- `CF_DNS_API_TOKEN`
- `TF_VAR_pm_api_token_secret`
- Docker Hub and CI-scanner credentials

### 5. Service-Internal Migration Flows

Treat DB, Redis, and other service-internal passwords as a later dedicated
project, with explicit sequencing and rollback.

## Relationship To Branching

This work should not start by extending production-only flows on `pve`.

The prerequisite is to make `baseline/teardown-validated` consistent enough
with `prod/pve-infra` that new credential-management logic can be developed and
validated on `pve-test`, then promoted with confidence.

See
[docs/baseline-merge/README.md](/home/steve/git/proxmox-homelab/docs/baseline-merge/README.md:1).

## Suggested Delivery Sequence

1. Complete the baseline/prod convergence work.
2. Build a credential inventory and classification table.
3. Prove one additional "easy" rotation on `pve-test`.
4. Add one current-vs-desired admin-password flow.
5. Decide which remaining credentials are preserve-only or do-not-automate.

## Initial Success Criteria

- every SOPS-managed credential has an explicit lifecycle class
- supported rotations are runnable and repeatable on `pve-test`
- unsupported credentials fail closed with a clear explanation
- production `pve` is not the first place a new rotation workflow is tested
