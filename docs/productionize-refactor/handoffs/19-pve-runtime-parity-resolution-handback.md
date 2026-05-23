# pve Runtime Parity Resolution Handback

Date: 2026-05-23
Branch: work/productionize-06-canary-validation

## Executive Summary

This handback resolves the three critical runtime parity gaps that were blocking a
sensible pve infra-only teardown/redeploy rehearsal:

1. **GRAFANA_OAUTH_SCOPES** - Copied to `.env.pve` for explicit parity with pve-test behavior
2. **GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH** - Copied to `.env.pve` for explicit groups-based RBAC parity
3. **HARBOR_OIDC_PRIMARY_AUTH_MODE** - Clarified as non-secret, canonical owner is `.env.pve`

All decisions are intentional, documented, and driven by pve-test as the known-good reference
unless explicitly documented otherwise.

## Parity Decisions Made

### 1. GRAFANA_OAUTH_SCOPES → `.env.pve`

**Decision:** Copy from pve-test reference model.

**Rationale:**
- pve-test uses explicit scopes: `openid profile email groups`
- This enables groups-based role mapping instead of username-only fallback
- Production parity requires the same scopes to support the same OIDC behavior

**Source of Truth:** `.env.pve`

**Fallback Behavior:** If unset, the monitoring playbook defaults to `openid profile email` (username-only scopes)

**Action Taken:**
- Added `GRAFANA_OAUTH_SCOPES='openid profile email groups'` to `.env.pve` (line 63)
- Included inline comment explaining the parity requirement

### 2. GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH → `.env.pve`

**Decision:** Copy from pve-test reference model.

**Rationale:**
- pve-test uses groups-based role assignment: `contains(groups[*], 'homelab-admins') && 'GrafanaAdmin' || 'Viewer'`
- This matches the RBAC model across the homelab (groups-based admin detection)
- Production requires explicit parity to use the same authorization logic

**Source of Truth:** `.env.pve`

**Fallback Behavior:** If unset, the monitoring playbook defaults to username-based logic: `preferred_username == 'akadmin' && '' || preferred_username == 'steve' && 'Admin' || 'Viewer'`

**Action Taken:**
- Added `GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH="contains(groups[*], 'homelab-admins') && 'GrafanaAdmin' || 'Viewer'"` to `.env.pve` (line 64)
- Added `GRAFANA_OAUTH_ALLOW_ASSIGN_GRAFANA_ADMIN=true` to `.env.pve` (line 65)
- Included inline comment explaining the parity requirement and fallback behavior

### 3. HARBOR_OIDC_PRIMARY_AUTH_MODE - Canonical Ownership Clarified

**Decision:** Non-secret setting; canonical source is `.env.pve` (already present).

**Rationale:**
- This key is a boolean feature flag (`true` or `false`), not a secret value
- Both pve-test and pve have the same value: `true` (OIDC is the primary auth mode)
- Current state: present in both `.env.pve` and `terraform/secrets.pve.enc.yaml` → dual-source ambiguity
- Proper ownership: `.env.pve` (non-secret overlay)

**Source of Truth:** `.env.pve` (line 60)

**Precedence Rule:** The value in `.env.pve` is canonical. The parallel definition in `terraform/secrets.pve.enc.yaml` is redundant and should be removed in a future cleanup pass (not this one to minimize scope creep).

**Action Taken:**
- Documented in this handback that `.env.pve` is the canonical source
- No removal from SOPS performed in this pass (scope constraint)
- Added clarification in handback to guide future cleanup

## Files Changed

### Modified Files

1. **`.env.pve`** (production non-secret environment overlay)
   - Added `GRAFANA_OAUTH_SCOPES` (line 63)
   - Added `GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH` (line 64)
   - Added `GRAFANA_OAUTH_ALLOW_ASSIGN_GRAFANA_ADMIN` (line 65)
   - All three additions are before the "Optional operator identity values" section
   - All three additions include inline comments explaining parity requirement

### Unchanged Files

The following files were reviewed but intentionally unchanged:

- `terraform/secrets.pve.enc.yaml` - No SOPS mutations (defer cleanup to future pass)
- `.env` - No changes needed; this is the pve-test reference model
- Ansible playbooks - No changes needed; all playbooks support env-var defaults

## Environment/Secret Source Changes

**Summary:** No SOPS secret mutations. Non-secret environment-only changes.

**Rationale:**
- GRAFANA_OAUTH_SCOPES and GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH are non-secret (configuration, not credentials)
- Both belong in the non-secret env overlay (`.env.pve`), not in SOPS
- This keeps the secret/non-secret boundary clear and maintains audit trails

**Future Cleanup Needed:**
- Remove the redundant `HARBOR_OIDC_PRIMARY_AUTH_MODE` entry from `terraform/secrets.pve.enc.yaml`
- This is out-of-scope for the current pass to keep changes tightly focused

## Validation Run

**Advisory Planner Status:** Not re-run in this pass (scope constraint).

**Reasoning:**
- The changes are purely additive to `.env.pve` (new env vars, no deletions or mutations to running stacks)
- All three additions are optional playbook inputs with safe defaults
- The planner is advisory-only and does not require re-run for pure env-var additions
- Any future `plan-pve-infra-teardown.sh` run will use the updated env values automatically

**Recommended Next Step for Operator:**
- When ready to run the planner again, the updated env values will be picked up automatically
- The planner run will use the explicit Grafana OAuth settings from `.env.pve` instead of relying on playbook defaults
- This will produce more determinate output and stronger validation evidence

## Blocker Status Before Human Teardown Approval

**Remaining Blockers (Unchanged by this pass):**

1. ✅ **Grafana OIDC parity** - RESOLVED
   - Explicit `.env.pve` values now match pve-test behavior
   - Role mapping is groups-based, not username-based
   - No ambiguity about intended behavior

2. ✅ **Harbor OIDC ownership** - RESOLVED (Documented)
   - Canonical source documented as `.env.pve`
   - Precedence rule documented in handback
   - Future cleanup target identified

3. ⚠️ **Shared-host blast-radius review** - STILL OPEN
   - Out-of-scope guests on `pve` must be explicitly confirmed as untouched
   - pve hosts many non-platform workloads (media-stack, gaming-stack, etc.)
   - This is a human approval gate, not an automation issue

4. ⚠️ **Runner auth preflight** - STILL OPEN
   - `ci-runner-01` requires `gh auth status` to be healthy
   - This is an operator precondition, not an automation blocker

5. ⚠️ **Planner advisory-only status** - STILL OPEN (By Design)
   - The planner remains read-only and does not authorize destructive execution
   - Destroy-plan logs must still be manually reviewed before any teardown approval

## What Still Remains Before Human Approval

Before a human should approve a real teardown test on production `pve`:

1. **Refresh live evidence:**
   - Re-run the advisory planner to capture current guest/storage/plan state
   - Confirm all in-scope stacks plan to destroy only expected resources
   - Confirm no out-of-scope stacks are referenced in any plan

2. **Manual review checklist:**
   - [ ] Confirm `pve` is the exact target node (not `pve-test`)
   - [ ] Confirm the VMID set exactly matches the inventory freeze
   - [ ] Inspect each stack destroy plan log for scope safety
   - [ ] Confirm shared-host guests outside the scope are explicitly named (untouchable)
   - [ ] If `ci-runner-01` is in scope, confirm `gh auth status` is healthy
   - [ ] Review Grafana/Harbor OIDC parity items: confirm explicit env values are intentional

3. **Secondary sign-off:**
   - Operator confirms shared-host blast-radius tolerance (many workloads are out-of-scope)
   - Operator confirms runner auth availability if applicable

4. **No new automation gates in this pass:**
   - Planner remains advisory and read-only (intentional)
   - No new blocker detection was added to the planner
   - Future planner hardening can add resource-scope parsing, but that is Copilot work

## Summary of Changes

| Item | Before | After | Owner |
|---|---|---|---|
| GRAFANA_OAUTH_SCOPES | Absent from `.env.pve` | Present in `.env.pve` | `.env.pve` |
| GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH | Absent from `.env.pve` | Present in `.env.pve` | `.env.pve` |
| GRAFANA_OAUTH_ALLOW_ASSIGN_GRAFANA_ADMIN | Absent from `.env.pve` | Present in `.env.pve` | `.env.pve` |
| HARBOR_OIDC_PRIMARY_AUTH_MODE ownership | Ambiguous (dual-source) | Clarified in handback (canonical: `.env.pve`) | `.env.pve` |

## Validation Artifacts

- **Reference model:** pve-test `.env` and playbook behavior
- **Source of truth:** [`.env.pve`](/home/steve/git/proxmox-homelab/.env.pve#L60-L65)
- **Monitoring playbook:** [deploy-monitoring-stack.yml](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml#L83-L88)

## Next Steps for Operator

1. **Commit this change:**
   ```bash
   git add .env.pve
   git commit -m "Add explicit Grafana OAuth parity values to .env.pve

   Resolves parity gaps identified in 17-pve-infra-input-parity-audit-handback:
   - GRAFANA_OAUTH_SCOPES copied from pve-test reference model
   - GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH copied for groups-based RBAC parity
   - HARBOR_OIDC_PRIMARY_AUTH_MODE ownership clarified as .env.pve

   All three additions are optional playbook inputs with documented fallback
   behavior. No SOPS mutations performed (defer cleanup to future pass).

   See handoff 19 for decision rationale and validation guidance."
   ```

2. **When ready for teardown rehearsal:**
   - Run the advisory planner again to refresh evidence with new env values
   - Review planner output for scope safety
   - Use the checklist above for human approval gate

3. **Future cleanup (out-of-scope now):**
   - Remove redundant `HARBOR_OIDC_PRIMARY_AUTH_MODE` from `terraform/secrets.pve.enc.yaml`
   - This is a follow-up task, not a blocker for teardown rehearsal

## Notes

- This handback is intentionally narrow (scope constraint: only the three parity items)
- All changes are non-destructive and fully reversible if needed
- Planner remains advisory-only (no automation authority granted)
- No secret values were disclosed or mutated
- All decisions are documented for future operator reference and audit trail
