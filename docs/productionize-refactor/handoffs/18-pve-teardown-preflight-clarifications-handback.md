# pve Teardown Preflight Clarifications Handback

Date: 2026-05-23
Branch: work/productionize-06-canary-validation

## Scope

Minimal clarification pass requested by the pve infra-only input parity audit.

- Added a read-only planner preflight for runner auth readiness when `ci-runner-01` is in scope.
- Clarified canonical ownership/precedence for the audited OIDC tuning keys.
- Updated planner/advisory documentation to reinforce advisory-only status and review requirements.

No secret values or environment values were changed.

## Files Changed

- `scripts/plan-pve-infra-teardown.sh`
- `docs/productionize-refactor/15-pve-infra-only-teardown-planner.md`
- `docs/productionize-refactor/16-pve-infra-teardown-advisory-summary.md`
- `docs/productionize-refactor/pve-infra-teardown-inventory.md`
- `docs/productionize-refactor/handoffs/18-pve-teardown-preflight-clarifications-handback.md`

## Preflight Added

In `scripts/plan-pve-infra-teardown.sh`, `source-preflight` now:

1. Detects whether `ci-runner-01` is present in the in-scope inventory rows.
2. If present, verifies `gh` is available on PATH.
3. Runs `gh auth status` as a read-only prerequisite check.
4. Blocks the phase with a clear error if `gh auth status` is not healthy.

This keeps runner token minting prerequisites explicit before later planner phases.

## Ownership / Precedence Clarifications Documented

Documented in planner/advisory docs as canonical review guidance for this pass:

1. Grafana OAuth tuning keys
   - Keys: `GRAFANA_OAUTH_SCOPES`, `GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH`
   - Canonical production owner for parity review: `.env.pve` (non-secret overlay)
   - If absent, playbook defaults are expected and must be treated as a parity review item.

2. Harbor OIDC primary-auth-mode
   - Key: `HARBOR_OIDC_PRIMARY_AUTH_MODE`
   - Canonical production owner for parity review: `.env.pve` (non-secret overlay)
   - Parallel definition in `terraform/secrets.pve.enc.yaml` is documented as precedence ambiguity and should be explicitly reviewed before teardown approval.

## Remaining Unresolved Items Before Human Approval

1. Planner remains advisory-only.
   - It is still not a go/no-go destroy authority and still requires manual destroy-plan log review.

2. Grafana OIDC parity is still a review item.
   - This pass clarifies ownership and review expectations, but does not change env values.

3. Harbor `HARBOR_OIDC_PRIMARY_AUTH_MODE` dual-source ambiguity still exists in runtime input surface.
   - This pass documents canonical ownership; it does not mutate either source.

4. Shared-host blast-radius review remains mandatory.
   - Out-of-scope guests on `pve` still require explicit human confirmation before any teardown approval.

## Follow-Up Requiring Env/Secret Mutation

None in this pass.

Potential future follow-up may require env/secret mutation **only if** operator decides to enforce strict runtime parity by changing overlay/secret content. No such mutations were performed here.
