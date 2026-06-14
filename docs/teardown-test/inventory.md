# Teardown Test Inventory (OP-02)

This document freezes the in-scope stack inventory, dependencies, and execution
order for the `pve-test` teardown/deploy rehearsal.

This is a planning artifact only. It does not approve destructive execution.

## Baseline

| Item | Value |
|---|---|
| Target environment | `pve-test` only |
| Planning branch | REQUIRES_OPERATOR_INPUT |
| Baseline source branch | `baseline/teardown-validated` |
| Baseline commit (from OP-00) | REQUIRES_OPERATOR_INPUT |
| Inventory freeze date | REQUIRES_OPERATOR_INPUT |

## Scope Freeze

### In Scope (platform rehearsal)

- `portainer-stack`
- `apt-cacher-stack`
- `harbor-stack`
- `ci-runner-01`
- `dns-stack`
- `proxy-stack`
- `step-ca-stack`
- `authentik-stack`
- `monitoring-stack`
- `netbox-stack`
- edge reconciliation activation (non-Terraform handoff)

### Out Of Scope (unless explicitly re-approved)

- disposable `net-*` validation stacks
- `test-docker`
- `test-lxc`
- `.hold/` stacks
- `headscale-stack` inventory/state without active `stack.yaml`

## Stack Inventory

| Stack | Stage | VMID | IP | Zone | depends_on | ansible_playbook |
|---|---|---:|---|---|---|---|
| `portainer-stack` | Stage 3b platform | 20020 | `192.168.20.20/24` | `mgmt_seg` | `[]` | `deploy-portainer-stack` |
| `apt-cacher-stack` | Stage 1/2 foundation | 40011 | `192.168.40.11/24` | `infra_seg` | `[]` | `deploy-apt-cacher-stack` |
| `harbor-stack` | Stage 3b platform | 40010 | `192.168.40.10/24` | `infra_seg` | `dns-stack`, `step-ca-stack`, `proxy-stack`, `authentik-stack` | `deploy-harbor-stack` |
| `ci-runner-01` | Stage 1/2 foundation | 10063 | `192.168.10.63/24` | `build_seg` | `apt-cacher-stack` | `deploy-ci-runner` |
| `dns-stack` | Stage 3a edge foundation | 20013 | `192.168.20.13/24` | `mgmt_seg` | none declared | `deploy-coredns` |
| `proxy-stack` | Stage 3a edge foundation | 30010 | `192.168.30.10/24` | `edge_seg` | `step-ca-stack`, `apt-cacher-stack` | `deploy-proxy-stack` |
| `step-ca-stack` | Stage 3a edge foundation | 20011 | `192.168.20.11/24` | `mgmt_seg` | `apt-cacher-stack` | `deploy-step-ca` |
| `authentik-stack` | Stage 3a edge foundation | 20010 | `192.168.20.10/24` | `mgmt_seg` | `dns-stack` | `deploy-authentik-stack` |
| `monitoring-stack` | Stage 3b platform | 20012 | `192.168.20.12/24` | `mgmt_seg` | `harbor-stack`, `apt-cacher-stack`, `authentik-stack`, `proxy-stack`, `step-ca-stack` | `deploy-monitoring-stack` |
| `netbox-stack` | Stage 3b platform | 40012 | `192.168.40.12/24` | `infra_seg` | `harbor-stack` | `deploy-netbox-stack` |

## Resolver And Zone Contract

| Component | Value |
|---|---|
| CoreDNS authoritative service | `dns-stack` (`${lab_ip_dns}`) |
| Delegated resolver | `${lab_gw_mgmt}` |
| Browser ingress target | `proxy-stack` (`${lab_ip_proxy}`) |
| Seed zone owner | `dns-stack` for `lab.gibbsgreatly.xyz` |
| Edge publication handoff | reconcile + publish after Stage 3a |

## Dependency/Bootstrap Consistency Check

| Check | Result |
|---|---|
| `proxy-stack` does not depend on `authentik-stack` | pass |
| `proxy-stack` provision requires `step-ca` homelab root CA | corrected: order now `dns -> step-ca -> proxy -> authentik` |
| Stage 3b `monitoring-stack` waits for Stage 3a services | pass (`depends_on` includes `authentik-stack`, `proxy-stack`, `step-ca-stack`) |
| `headscale-stack` remains out of default scope | pass |

**Updated during OP-06+:** `proxy-stack` provisioning requires the homelab root CA
from `step-ca`, introduced by Traefik + OIDC + proxy middleware wiring. Ordering
corrected in Stage 3a: `step-ca` must precede `proxy-stack`.

## Approved Deploy Order

1. `apt-cacher-stack`
2. `ci-runner-01`
3. `dns-stack`
4. `step-ca-stack`
5. `proxy-stack`
6. `authentik-stack`
7. edge reconciliation activation  <!-- not in backticks: excluded from inventory parser; handled by activate-edge phase -->
8. `harbor-stack`
9. `monitoring-stack`
10. `netbox-stack`
11. `portainer-stack`

## Approved Destroy Order

1. `portainer-stack`
2. `netbox-stack`
3. `monitoring-stack`
4. `harbor-stack`
5. `authentik-stack`
6. `step-ca-stack`
7. `proxy-stack`
8. `dns-stack`
9. `ci-runner-01`
10. `apt-cacher-stack`
