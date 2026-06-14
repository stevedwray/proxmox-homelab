# pve Infra-Only Input Parity Audit Handback

Date: 2026-05-23
Branch: work/productionize-06-canary-validation

## Scope And Goal

This handback audits production `pve` infra-only redeploy input parity against
the known-good `pve-test` model, focused only on stacks listed in
`docs/productionize-refactor/pve-infra-teardown-inventory.md`.

Reference model:

- pve-test wrapper path: `./with-secrets` => `.env` + `.env.pve-test` + `terraform/secrets.enc.yaml`
- pve production path: `./with-secrets-prod` => `.env.pve` + `terraform/secrets.pve.enc.yaml`

This is an audit only. No secret/env mutations were performed.

## Stacks Audited

1. `apt-cacher-stack`
2. `ci-runner-01`
3. `dns-stack`
4. `step-ca-stack`
5. `proxy-stack`
6. `authentik-stack`
7. `harbor-stack`
8. `monitoring-stack`
9. `netbox-stack`
10. `portainer-stack`

## Required Input Surface (Infra-Only)

## Non-Secret Inputs (effective)

- Common network and host inputs used across infra stack manifests/playbooks:
  - `LAB_IP_*` service IPs for all infra stacks in scope
  - `LAB_GW_*` segmented gateways
  - `LAB_DOMAIN` and selected `LAB_FQDN_*`
  - `TF_VAR_proxmox_node=pve` in production wrapper path
- Stack-specific mandatory non-secret inputs:
  - `proxy-stack`: `TRAEFIK_DNS_RESOLVER_PRIMARY`, `TRAEFIK_DNS_RESOLVER_SECONDARY`, `LAB_IP_STEP_CA`
  - `harbor-stack`: `HARBOR_HOSTNAME` (OIDC non-secret tuning keys also consumed)
  - `monitoring-stack`: optional-but-impactful Grafana OAuth tuning vars (defaults exist)
  - `dns-stack`: `LAB_GW_MGMT` and full `LAB_IP_*` mapping for zone rendering
  - `ci-runner-01`: no static secret required for registration token, but requires operator GitHub CLI auth context

## Secret Inputs (effective)

- Mandatory redeploy secrets are present in `terraform/secrets.pve.enc.yaml` for infra stack provisioning:
  - Core Terraform/auth: `TF_VAR_lxc_password`, `TF_VAR_pm_api_token_secret`
  - PKI: `STEP_CA_PASSWORD`, `STEP_CA_PROVISIONER_PASSWORD`
  - Proxy: `CF_DNS_API_TOKEN`
  - Authentik: `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_POSTGRES_PASSWORD`, `AUTHENTIK_SUPERUSER_PASSWORD`, `AUTHENTIK_SUPERUSER_API_TOKEN`, `AUTHENTIK_STEVE_PASSWORD`
  - Harbor: `HARBOR_ADMIN_PASSWORD`, `HARBOR_DB_PASSWORD`, `HARBOR_OIDC_CLIENT_SECRET`
  - Monitoring: `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_OAUTH_CLIENT_SECRET`, `AUTHENTIK_SUPERUSER_API_TOKEN`, `BREAKGLASS_PASSWORD`
  - NetBox: `NETBOX_DB_PASSWORD`, `NETBOX_REDIS_PASSWORD`, `NETBOX_REDIS_CACHE_PASSWORD`, `NETBOX_SECRET_KEY`, `NETBOX_API_TOKEN_PEPPER`, `NETBOX_SUPERUSER_PASSWORD`, `NETBOX_SUPERUSER_API_TOKEN`, `BREAKGLASS_PASSWORD`
  - Portainer: `TF_VAR_portainer_admin_password`, `PORTAINER_ADMIN_PASSWORD`, `PORTAINER_OAUTH_CLIENT_SECRET`

## Parity Findings And Classification

## A) Missing On pve And Should Be Copied From Test-Side Source

1. `GRAFANA_OAUTH_SCOPES` (non-secret; currently only in `.env`)
   - Why: pve-test currently gets customized scopes from `.env`; production path falls back to playbook default if unset.
   - Classification: Copy to `.env.pve` if the intent is exact parity of Grafana OIDC claim scope behavior.
   - Severity: Medium (behavioral drift risk, not immediate deploy blocker).

2. `GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH` (non-secret; currently only in `.env`)
   - Why: pve-test uses explicit role mapping expression from `.env`; production path falls back to different default mapping.
   - Classification: Copy to `.env.pve` if role mapping parity is required for teardown/redeploy validation fidelity.
   - Severity: Medium (post-deploy authz behavior drift risk).

## B) Missing On pve And Should Be Newly Generated

1. `ci-runner-01` ephemeral registration token
   - Why: deployment now generates token via `gh api` at run time rather than reading static `GITHUB_RUNNER_*` secrets.
   - Classification: Newly generated each run (do not pre-store as static SOPS key for this flow).
   - Severity: Medium.

## C) Present But Divergent (Review Required)

1. `GRAFANA_OAUTH_CLIENT_ID`
   - State: Present in `terraform/secrets.enc.yaml`, absent from `terraform/secrets.pve.enc.yaml`.
   - Runtime effect: monitoring playbook defaults to `grafana` when missing.
   - Classification: Review; copy only if production must match non-default pve-test OIDC client id.

2. `PORTAINER_ADMIN_PASSWORD` keying strategy
   - State: present in prod SOPS; pve-test path typically relies on `TF_VAR_portainer_admin_password`/legacy aliases.
   - Runtime effect: not currently blocking because playbook accepts both.
   - Classification: Review for canonical single-source key naming, not a teardown blocker.

3. `HARBOR_OIDC_PRIMARY_AUTH_MODE` dual-source ambiguity
   - State: defined in both `.env.pve` (non-secret) and `terraform/secrets.pve.enc.yaml` (secret file key present).
   - Runtime effect: `sops exec-env` overlay can override `.env.pve` value if both are set.
   - Classification: Review ownership (env vs SOPS) to avoid hidden precedence drift.

## D) External / Operator-Managed / Should Not Be Rotated As Part Of This Audit

1. `ci-runner-01` GitHub CLI auth session (`gh auth status` prerequisite)
   - Required for token minting with current playbook path.
   - Keep external/operator-managed; do not attempt static secret replication from old docs.

2. `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD`
   - Present in test SOPS, absent in prod SOPS.
   - These are runtime consumer credentials and not required to stand up infra stack containers.
   - Keep external to infra redeploy blocker set; treat as downstream consumer integration secret.

3. Legacy aliases not in active infra redeploy path:
   - `GRAFANA_ADMIN`, `HARBOR_ADMIN`, `NPM_DB_PASSWORD`
   - Classification: out-of-scope/legacy; do not copy for infra-only teardown readiness.

## Base `.env` Reliance Risk (pve-test vs pve)

Because `./with-secrets` loads `.env` while `./with-secrets-prod` does not, any
key that exists only in `.env` is silently available on pve-test but absent on pve.

Current infra-only path callouts:

1. `GRAFANA_OAUTH_SCOPES` and `GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH`
   - pve-test effective behavior currently depends on `.env` values.
   - pve uses playbook defaults unless those keys are duplicated into `.env.pve`.

2. `COREDNS_LOOPBACK_IP`
   - currently only in `.env`; pve falls back to playbook default `127.0.0.1`.
   - low risk, but still a base-env dependency difference.

## Missing pve Inputs Summary

For infra-only stack redeploy essentials, production inputs are largely present.
No hard missing mandatory redeploy secret was identified for the audited stack set.

Remaining misses are mostly:

- behavior-parity misses (Grafana OIDC tuning vars)
- operator-context prerequisites (GitHub CLI auth for runner token generation)
- naming/ownership ambiguities (duplicate/legacy key surfaces)

## Divergent pve Inputs Summary

- Secret keyset drift exists but is mostly non-blocking for infra redeploy:
  - missing in prod compared to test: `GRAFANA_ADMIN`, `GRAFANA_OAUTH_CLIENT_ID`, `HARBOR_ADMIN`, `HARBOR_ROBOT_USER`, `HARBOR_ROBOT_PASSWORD`, `NPM_DB_PASSWORD`
  - prod-only extra key: `PORTAINER_ADMIN_PASSWORD`
- Highest-value review item from this drift: `GRAFANA_OAUTH_CLIENT_ID` (if exact OIDC app parity is required).

## Specific Blockers Before Sensible pve Infra Teardown/Re-Deploy Test

1. Runner registration prerequisite is not wrapper-contained
   - `ci-runner-01` depends on valid operator `gh` auth state for token generation.
   - Without explicit preflight, rerun may fail mid-cycle.

2. Grafana OAuth behavior parity is not guaranteed between pve-test and pve
   - pve-test currently derives important OAuth tuning from `.env`; pve may use defaults.
   - This can pass infra deploy but fail expected post-redeploy auth/role behavior checks.

3. Key ownership precedence ambiguity exists for select Harbor/Portainer inputs
   - Dual-source or legacy alias usage can mask which value is authoritative during production runs.
   - This raises reproducibility risk during teardown/redeploy validation.

## Recommended Follow-Up Tasks (Separate Handback Items)

1. Add a small read-only preflight check for infra deploy phases that verifies `gh auth status` when `ci-runner-01` is in scope.
2. Decide and document canonical ownership for OIDC tuning keys (env vs SOPS) for Grafana and Harbor (no redesign; explicit precedence only).
3. If strict parity is desired, duplicate the selected non-secret Grafana OAuth tuning keys from `.env` into `.env.pve` and document as intentional production overlay values.
4. Optionally prune/label legacy secret aliases in docs so future audits do not treat them as active blockers.

## Final Audit Verdict

`pve` infra-only redeploy input surface is **mostly complete**, but not yet
fully deterministic for a production teardown/redeploy rehearsal without a small
set of parity and preflight clarifications.
