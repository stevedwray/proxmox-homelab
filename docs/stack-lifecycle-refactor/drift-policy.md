# Drift Policy

## Goal

Provide a clear operational model for day-2 drift handling.

## Drift Classes

### Managed

- Ansible is authoritative.
- Drift should be detected and normally corrected by reconcile.
- Unknown drift in these areas should be reported and may require operator approval before overwrite.

### Observed

- Drift should be reported but not automatically corrected.
- Useful for audit-sensitive or transitional areas.

### Adoptable

- Manual changes may be intentionally made and later incorporated into managed configuration.
- The workflow should support operator review before adoption.

## Recommended Default

### Essential Infrastructure Stacks

- default to `managed`
- low tolerance for manual in-container tuning

### Future General Application Stacks

- allow more `adoptable` areas where iterative tuning is likely

## Early Adoption Target

- Docker and compose-level service reconfiguration is the first likely candidate for an adoption workflow.

## Stage 8 Operational Defaults

### Class Mapping Baseline

- Managed (default):
	- `stack.yaml` deployment metadata (zone/IP/gateway/vmid/playbook/dependency declarations)
	- generated inventory and generated edge/traefik artifacts that are rendered from source metadata
	- playbook-managed service/unit/config files under stack deployment paths
- Observed:
	- runtime application state inside persistent data volumes/databases
	- external system state that reconcile probes but does not fully own (for example external auth/API side effects)
- Adoptable (opt-in only):
	- stack-specific runtime tuning paths explicitly documented in the stack contract and promoted to managed only after validation evidence

### Operator Surfacing Rules

- Surface drift through the standard check/live/rerun evidence set (`check.log`, `live.log`, `rerun.log`, `health.log`).
- Treat new unexpected rerun churn as actionable drift unless it matches accepted shared baselines documented in `validation.md`.
- Record accepted baseline drift explicitly in handoff/plan updates when it is intentionally carried forward.

### Enforcement Stance Before Stage 9

- Reporting-first for known shared baseline churn classes already accepted in Stage 6-8 evidence.
- Enforcement for new or stack-specific drift regressions that are not on the accepted baseline list.
- No new drift framework design in Stage 8; only execution-safe documentation and consistency hardening.
