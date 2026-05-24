# Credential Management Execution Plan

## Goal

Develop a stack-aware credential-management model that keeps SOPS as the source
of truth and expands day-2 rotation only where the live service behavior makes
it safe.

The immediate objective is not "rotate everything." It is to classify every
credential, normalize the current schema, and prove safe rotation flows on
`pve-test` before promoting them toward `pve`.

## Preconditions

This plan should start only after the baseline convergence stream is complete
enough that `pve-test` exercises the same relevant code paths as `pve`.

See [docs/baseline-merge/plan.md](/home/steve/git/proxmox-homelab/docs/baseline-merge/plan.md:1).

## Phase 0: Schema Normalization

Before adding more automation, fix the current secrets schema drift between
environments and consumers.

### Known schema issues

| Issue | Why it matters | Required action |
|---|---|---|
| `TF_VAR_portainer_admin_password` versus `PORTAINER_ADMIN_PASSWORD` | Mixed naming makes rotation and inventory ambiguous | Choose one canonical key and map legacy names explicitly if needed |
| `PORTAINER_ADMIN` / `GRAFANA_ADMIN` / `HARBOR_ADMIN` username keys mixed with password keys | Inventory currently mixes usernames, passwords, and flags in the same mental bucket | Distinguish secret versus non-secret identity inputs |
| `HARBOR_OIDC_PRIMARY_AUTH_MODE` stored in secrets | This is a runtime mode flag, not a secret | Move to non-secret env/config if still present |
| Production and test SOPS files are not guaranteed to stay schema-identical | Branch convergence and test-to-prod confidence suffer | Add a parity check for key presence and intended differences |

### Deliverables

- one canonical inventory of SOPS-managed keys
- a documented list of which entries are true secrets versus runtime settings
- an explicit policy for aliases and deprecated key names

## Phase 1: Full Credential Inventory And Classification

Classify every currently visible SOPS key into an automation class.

### Class Definitions

| Class | Meaning |
|---|---|
| `rotate-now` | Safe to regenerate and converge with the current or near-current day-2 model |
| `rotate-with-current-auth` | Rotatable, but only if the flow uses current and desired credentials together |
| `replace-external` | Minted outside this repo; the repo only distributes the replacement |
| `preserve-only` | Preserve and back up, do not casually rotate |
| `do-not-automate-yet` | Too risky or incomplete for near-term automation |

### Initial Inventory

#### `rotate-now`

| Key | Owning stack / system | Current state | Next action |
|---|---|---|---|
| `AUTHENTIK_STEVE_PASSWORD` | `authentik-stack` | Already supported by `rotate-stack-credentials.py` | Validate on `pve-test` after baseline convergence |
| `NETBOX_SUPERUSER_PASSWORD` | `netbox-stack` | Already supported | Validate on `pve-test` |
| `GRAFANA_OAUTH_CLIENT_SECRET` | `monitoring-stack` | Already supported | Validate on `pve-test` |
| `HARBOR_OIDC_CLIENT_SECRET` | `harbor-stack` | Already supported | Validate on `pve-test` |
| `PORTAINER_OAUTH_CLIENT_SECRET` | `portainer-stack` | Already supported | Validate on `pve-test` |

#### `rotate-with-current-auth`

| Key | Owning stack / system | Blocker | Planned approach |
|---|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` | `monitoring-stack` | Playbook later authenticates to Grafana using the same credential | Add current-versus-desired admin-password flow |
| `HARBOR_ADMIN_PASSWORD` | `harbor-stack` | Harbor API tasks use the current admin credential | Add API-driven password change then SOPS cutover |
| `TF_VAR_portainer_admin_password` | `portainer-stack` | Portainer login bootstrap uses the same password it would rotate | Add login with old password, set new password, verify, then update SOPS |
| `AUTHENTIK_SUPERUSER_PASSWORD` | `authentik-stack` | Current use is bootstrap-oriented and not a proven day-2 path | Decide whether to support true day-2 rotation or reclassify |

#### `replace-external`

| Key | Owning stack / system | Replacement minted where | Planned approach |
|---|---|---|---|
| `CF_DNS_API_TOKEN` | Cloudflare / `proxy-stack` consumers | Cloudflare | Operator mints new token, repo updates SOPS, reconcile consumers |
| `TF_VAR_pm_api_token_secret` | Proxmox API | Proxmox | Manual token replacement plus wrapper validation |
| `HARBOR_DOCKERHUB_USERNAME` | Docker Hub mirror access | Docker Hub | Mostly inventory-only; usually rotate pair together |
| `HARBOR_DOCKERHUB_PASSWORD` | Docker Hub mirror access | Docker Hub | External replacement plus Harbor reconcile |
| `SONAR_TOKEN` | Sonar | SonarQube / SonarCloud | Replace in SOPS and CI consumers |
| `SNYK_TOKEN` | Snyk | Snyk | Replace in SOPS and CI consumers |
| `MIKROTIK_USER` | MikroTik | MikroTik | Decide whether this belongs in SOPS long-term |
| `MIKROTIK_PASSWORD` | MikroTik | MikroTik | External replacement only |
| `MIKROTIK_ADMIN` | MikroTik | MikroTik | Identity input, not rotation target |
| `MIKROTIK_ADMIN_PASSWORD` | MikroTik | MikroTik | External replacement only |
| `OMADA_CLIENT_ID` | Omada | Omada | External replacement only |
| `OMADA_CLIENT_SECRET` | Omada | Omada | External replacement only |
| `OMADA_ID` | Omada | Omada | Runtime identifier, not a rotation target |
| `OMADA_INTERFACE` | Omada | Omada | Runtime identifier, not a rotation target |

#### `preserve-only`

| Key | Why preserve-only |
|---|---|
| `AUTHENTIK_SECRET_KEY` | App crypto anchor; changing it is service identity impact, not routine password rotation |
| `STEP_CA_PASSWORD` | Root CA bootstrap / key-protection material |
| `STEP_CA_PROVISIONER_PASSWORD` | CA bootstrap credential with trust-chain implications |

#### `do-not-automate-yet`

| Key | Owning stack / system | Why not yet |
|---|---|---|
| `AUTHENTIK_POSTGRES_PASSWORD` | `authentik-stack` | Needs coordinated DB credential migration |
| `HARBOR_DB_PASSWORD` | `harbor-stack` | Internal DB credential migration required |
| `NETBOX_DB_PASSWORD` | `netbox-stack` | Internal DB credential migration required |
| `NETBOX_REDIS_PASSWORD` | `netbox-stack` | Redis password migration required |
| `NETBOX_REDIS_CACHE_PASSWORD` | `netbox-stack` | Redis password migration required |
| `NETBOX_SECRET_KEY` | `netbox-stack` | App crypto setting, not a routine live password |
| `NETBOX_API_TOKEN_PEPPER` | `netbox-stack` | Token/crypto behavior impact |
| `NETBOX_SUPERUSER_API_TOKEN` | `netbox-stack` | Current playbook creates when missing, does not replace safely |
| `AUTHENTIK_SUPERUSER_API_TOKEN` | `authentik-stack` | Token fans out to reconcilers and clients; needs replacement choreography |
| `BREAKGLASS_PASSWORD` | multi-stack | Shared secret across services; should be split before rotation |
| `HARBOR_ROBOT_USER` | Harbor / CI consumers | Robot identity and secret are cross-system, not pure repo-owned |
| `HARBOR_ROBOT_PASSWORD` | Harbor / CI consumers | Secret is shown once and then consumed elsewhere |
| `NPM_DB_PASSWORD` | legacy / unclear | Needs owner verification before any automation |

### Identity / non-rotation inputs to keep out of the rotation backlog

| Key |
|---|
| `AUTHENTIK_SUPERUSER` |
| `GRAFANA_ADMIN` |
| `HARBOR_ADMIN` |
| `PORTAINER_ADMIN` |

## Phase 2: Extend The Rotation Framework

Enhance `scripts/rotate-stack-credentials.py` only after the inventory is
agreed.

### Required framework behaviors

- plan-first default
- explicit capability registry
- refusal for unsupported keys
- stack ownership in output
- `pve-test` versus `pve` targeting awareness
- optional "SOPS only" mode for external-replacement flows
- audit-friendly output showing exactly what stack reconcile will run

### Out of scope for the first extension

- a generic "rotate any key" flag
- automatic rotation of CA or DB credentials
- silent alias resolution that hides schema drift

## Phase 3: Easy Rotation Expansion

After baseline convergence, extend the supported set in this order:

1. validate the existing five supported capabilities on `pve-test`
2. add one external-replacement flow:
   - recommended first target: `CF_DNS_API_TOKEN`
3. add one current-vs-desired admin-password flow:
   - recommended first target: `GRAFANA_ADMIN_PASSWORD`

This phase should optimize for learning, not breadth.

## Phase 4: Shared-Secret Reduction

Before attempting to automate shared breakglass rotation, split shared secrets
where possible.

### Initial target

Replace the single `BREAKGLASS_PASSWORD` model with per-service breakglass
values for:

- NetBox
- Grafana
- Harbor

Only after the split should any breakglass password become a candidate for
day-2 automation.

## Phase 5: Token Replacement Flows

Design service-specific replacement procedures for tokens that cannot safely be
treated like passwords.

### Priority order

1. `NETBOX_SUPERUSER_API_TOKEN`
2. `AUTHENTIK_SUPERUSER_API_TOKEN`
3. `HARBOR_ROBOT_PASSWORD`

Each flow should specify:

- how the replacement is minted
- who/what currently consumes the old token
- whether dual-token overlap is possible
- how rollback works

## Phase 6: Explicit Non-Automation Decisions

Close the loop by documenting the credentials we will not automate in the near
term.

At minimum, record explicit "manual only" or "preserve-only" decisions for:

- `AUTHENTIK_SECRET_KEY`
- `STEP_CA_PASSWORD`
- `STEP_CA_PROVISIONER_PASSWORD`
- DB and Redis passwords across Authentik, Harbor, and NetBox

## Validation Model

Each newly supported capability must pass:

1. dry-run output review
2. SOPS update on `pve-test`
3. owning stack reconcile on `pve-test`
4. post-rotation login / API validation using the new credential
5. negative validation that the old credential no longer works, where safe
6. documentation update to move the key into the supported class

## Rollback Model

Every supported rotation must define one rollback path:

- restore the old SOPS value and reconcile
- or mint a second replacement if the service invalidates the first immediately

If rollback cannot be defined clearly, the credential is not ready for
automation.

## Done When

This plan is successful when:

- every SOPS-managed key has an agreed lifecycle class
- schema drift between test and production secrets is under control
- the rotation script supports more than the initial five capabilities
- at least one admin-password flow and one external-replacement flow are proven
  on `pve-test`
- the remaining dangerous credentials are explicitly documented as preserve-only
  or not-yet-automated
