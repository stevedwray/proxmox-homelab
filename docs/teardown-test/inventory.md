# Teardown Test Inventory (OP-02)

This document freezes the in-scope stack inventory, dependencies, and execution
order for the `pve-test` teardown/deploy rehearsal.

This is a planning artifact only. It does not approve destructive execution.

## Baseline

| Item | Value |
|---|---|
| Target environment | `pve-test` only |
| Planning branch | `docs/teardown-test-execution-variables` |
| Baseline source branch | `dev/pve-test` |
| Baseline commit (from OP-00) | `d95324aeed1832fafa30af3354e75e044e3f08a3` |
| Inventory freeze date | `2026-04-21` |

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
| `portainer-stack` | Stage 3b platform | 120 | `10.57.1.20/24` | `mgmt_seg` | `[]` | `deploy-portainer-stack` |
| `apt-cacher-stack` | Stage 1/2 foundation | 142 | `10.57.3.11/24` | `infra_seg` | `[]` | `deploy-apt-cacher-stack` |
| `harbor-stack` | Stage 1/2 foundation | 121 | `10.57.3.10/24` | `infra_seg` | `[]` | `deploy-harbor-stack` |
| `ci-runner-01` | Stage 1/2 foundation | 141 | `10.57.0.63/24` | `build_seg` | `harbor-stack`, `apt-cacher-stack` | `deploy-ci-runner` |
| `dns-stack` | Stage 3a edge foundation | 151 | `10.57.1.13/24` | `mgmt_seg` | none declared | `deploy-coredns` |
| `proxy-stack` | Stage 3a edge foundation | 153 | `10.57.2.10/24` | `edge_seg` | `harbor-stack`, `apt-cacher-stack` | `deploy-proxy-stack` |
| `step-ca-stack` | Stage 3a edge foundation | 152 | `10.57.1.11/24` | `mgmt_seg` | `apt-cacher-stack` | `deploy-step-ca` |
| `authentik-stack` | Stage 3a edge foundation | 150 | `10.57.1.10/24` | `mgmt_seg` | `harbor-stack` | `deploy-authentik-stack` |
| `monitoring-stack` | Stage 3b platform | 154 | `10.57.1.12/24` | `mgmt_seg` | `harbor-stack`, `apt-cacher-stack`, `authentik-stack`, `proxy-stack`, `step-ca-stack` | `deploy-monitoring-stack` |
| `netbox-stack` | Stage 3b platform | 143 | `10.57.3.12/24` | `infra_seg` | `harbor-stack` | `deploy-netbox-stack` |

## Resolver And Zone Contract

| Component | Value |
|---|---|
| CoreDNS authoritative service | `dns-stack` (`10.57.1.13`) |
| Delegated resolver | `10.57.1.1` |
| Browser ingress target | `proxy-stack` (`10.57.2.10`) |
| Seed zone owner | `dns-stack` for `lab.gibbsgreatly.xyz` |
| Edge publication handoff | reconcile + publish after Stage 3a |

## Dependency/Bootstrap Consistency Check

| Check | Result |
|---|---|
| `proxy-stack` does not depend on `authentik-stack` | pass |
| Stage 3a order can be run as `dns -> proxy -> step-ca -> authentik` | pass |
| Stage 3b `monitoring-stack` waits for Stage 3a services | pass (`depends_on` includes `authentik-stack`, `proxy-stack`, `step-ca-stack`) |
| `headscale-stack` remains out of default scope | pass |

No dependency conflict requiring source code change was found in the in-scope
`stack.yaml` files during OP-02 freeze.

## Approved Deploy Order

1. `apt-cacher-stack`
2. `harbor-stack`
3. `ci-runner-01`
4. `dns-stack`
5. `proxy-stack`
6. `step-ca-stack`
7. `authentik-stack`
8. edge reconciliation activation  <!-- not in backticks: excluded from inventory parser; handled by activate-edge phase -->
9. `monitoring-stack`
10. `netbox-stack`
11. `portainer-stack`

## Approved Destroy Order

1. `netbox-stack`
2. `monitoring-stack`
3. `authentik-stack`
4. `step-ca-stack`
5. `proxy-stack`
6. `dns-stack`
7. `ci-runner-01`
8. `harbor-stack`
9. `apt-cacher-stack`
10. `portainer-stack`
