# 04c-stack-owned-ingress-06 — Final Cutover and Legacy Central Cleanup

## Phase

Phase 04c — Stack-Owned Ingress, DNS, and Auth Integration

## Objective

Complete migration by removing legacy central route definitions and hardening operational safeguards.

## Scope

- Remove central per-service route blocks from proxy playbook template
- Keep only shared middleware/static platform config centrally
- Add runbook entries and rollback procedure
- Execute full regression checks

## Deliverables

- Clean central proxy template (no per-stack service routes)
- Regression validation report
- Rollback steps documented and tested

## Session boundary

Single-session cutover after all service migrations are complete.

## Implementation checklist

- [ ] Remove legacy router/service stanzas from central template
- [ ] Verify renderer outputs all needed stack files
- [ ] Run end-to-end checks for all browser hosts
- [ ] Confirm no orphan DNS records remain
- [ ] Confirm no manual Authentik steps remain for migrated stacks

## Exit criteria

- [ ] Every browser service reachable at canonical `.lab.gibbsgreatly.xyz` host
- [ ] Expected auth behavior per service still correct
- [ ] No central service route ownership remains
- [ ] Rollback tested with previous generated snapshot restore

## Done when

- Stack ownership model is default path for all future browser services
