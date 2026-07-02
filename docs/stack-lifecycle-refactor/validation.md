# Validation

This file defines the recommended validation model for the stack lifecycle refactor.

## Validation Classes

### Infrastructure-Only Changes

Recommended mandatory checks:

- Terraform plan/apply succeeds as expected
- container exists and is reachable
- CPU, memory, disk, mounts, IP, network attachment, and firewall state are correct
- no unexpected replacement occurred

Recommended optional checks:

- if the operator approves it, run day-2 reconcile for affected stacks
- targeted service health checks if infra changes may affect runtime behavior

### Configuration-Only Changes

Recommended mandatory checks:

- Ansible run completes successfully
- rerun behavior is acceptable for the declared management mode
- managed files and services converge as expected
- service-specific health checks pass

Recommended optional checks:

- drift report recorded when manual change adoption is involved

### Coordinated Changes

Recommended mandatory checks:

- all infrastructure-only required checks
- all configuration-only required checks
- cross-stack dependency checks
- relevant endpoint, DNS, trust, or registration checks

## Design Intent

- infra-only changes verify shape and reachability
- config-only changes verify convergence and service health
- coordinated changes verify integration

## Operator Workflow Baseline (Stage 8 Hardened)

Use this execution order for bounded stack validation before Stage 9:

1. Target guard (required before infra/apply or reconcile commands):
	- `./with-secrets bash -c 'echo "$TF_VAR_proxmox_node"'` must return `pve-test-vm`.
2. Check mode reconcile (post-infra when inventory exists):
	- `./with-secrets ./scripts/provision.sh --stack <stack-name> --check`
3. Live reconcile:
	- `./with-secrets ./scripts/provision.sh --stack <stack-name>`
4. Idempotent rerun:
	- repeat the live reconcile command once and compare changed/failed summary.
5. Stack-specific health probe:
	- systemd service stacks: verify service active status and stack-specific endpoint/query where applicable.
	- compose stacks: verify container/service health endpoint and expected auth/route behavior where applicable.

## Evidence Format (Stage 8 Baseline)

For each bounded stack validation slice, capture at least:

- `check.log`
- `live.log`
- `rerun.log`
- `health.log`
- optional infra logs (`terraform-plan.log`, `terraform-apply.log`) when infra apply is in-scope
- optional summary file (`EVIDENCE.md`) when multiple logs need a concise findings index

Evidence should be stored in an ignored evidence directory, not in tracked docs.

## Accepted Non-Idempotent Baseline Behavior (Carry Forward)

Reruns are considered acceptable when all fatal failures remain at zero and observed churn is limited to known shared baseline tasks such as:

- `lxc_base` DNS resolver rewrites/fallback interactions
- temporary public DNS fallback rewrites to `/etc/resolv.conf`
- proxy CA bundle rebuild tasks intentionally marked changed on each run
- trust-install tasks that report changed due to shared base-role behavior

Any new rerun churn outside these known classes should be treated as a hardening candidate and documented with evidence before Stage 9.

## Check Scope Guidance

- Global checks: target guard, check/live/rerun command flow, evidence capture format.
- Stack-specific checks: service health probe details, auth integration assertions, and dependency-path validations.
- Do not add new design or rollout-order work in this phase; keep fixes bounded to operational clarity and safe consistency corrections.
