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

## Open Items

- exact commands and evidence format per stack
- what counts as acceptable non-idempotent output for bootstrap-heavy stacks
- which checks are global vs stack-specific
