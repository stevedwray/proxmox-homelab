# pve Infra-Only Teardown Inventory

## Purpose

Freeze the intended in-scope infrastructure stack inventory for a future
`pve` infra-only teardown dry run.

This is a planning artifact only. It does not approve destructive execution.

## Baseline

| Item | Value |
|---|---|
| Target environment | `pve` only |
| Target node | `pve` |
| Execution wrapper | `./with-secrets-prod` |
| Scope type | infrastructure services only |
| Source of truth | current `terraform/lxc/stacks/*/stack.yaml` plus this inventory freeze |

## Scope Freeze

### In Scope

- `apt-cacher-stack`
- `ci-runner-01`
- `dns-stack`
- `step-ca-stack`
- `proxy-stack`
- `authentik-stack`
- `harbor-stack`
- `monitoring-stack`
- `netbox-stack`
- `portainer-stack`

### Out Of Scope

- validation and disposable network stacks:
  `net-app-01`, `net-artifacts-01`, `net-build-01`, `net-client-01`,
  `net-client-02`, `net-isolated-01`, `net-service-01`, `net-service-02`,
  `net-svc-01`
- `test-docker`
- `test-lxc`
- any CT or VM on `pve` whose VMID is not explicitly listed in the in-scope
  inventory table below
- host-level Proxmox networking, SDN, bridges, VLAN trunks, or firewall rules
- storage pools, templates, ISO stores, backups, and snapshots not owned by an
  in-scope stack
- `pve-test` counterpart disposal flows
- application services outside the platform stack catalog

## Stack Inventory

| Stack | Stage | VMID | IP | Zone | Service type | depends_on | ansible_playbook |
|---|---|---:|---|---|---|---|---|
| `apt-cacher-stack` | foundation | 40011 | `192.168.40.11/24` | `infra_seg` | systemd | `[]` | `deploy-apt-cacher-stack` |
| `ci-runner-01` | foundation | 10063 | `192.168.10.63/24` | `build_seg` | systemd | `apt-cacher-stack` | `deploy-ci-runner` |
| `dns-stack` | edge foundation | 20013 | `192.168.20.13/24` | `mgmt_seg` | systemd | `[]` | `deploy-coredns` |
| `step-ca-stack` | edge foundation | 20011 | `192.168.20.11/24` | `mgmt_seg` | systemd | `apt-cacher-stack` | `deploy-step-ca` |
| `proxy-stack` | edge foundation | 30010 | `192.168.30.10/24` | `edge_seg` | Docker Compose | `step-ca-stack`, `apt-cacher-stack` | `deploy-proxy-stack` |
| `authentik-stack` | edge foundation | 20010 | `192.168.20.10/24` | `mgmt_seg` | Docker Compose | `dns-stack` | `deploy-authentik-stack` |
| `harbor-stack` | platform | 40010 | `192.168.40.10/24` | `infra_seg` | Docker Compose | `dns-stack`, `step-ca-stack`, `proxy-stack`, `authentik-stack` | `deploy-harbor-stack` |
| `monitoring-stack` | platform | 20012 | `192.168.20.12/24` | `mgmt_seg` | Docker Compose | `harbor-stack`, `apt-cacher-stack`, `authentik-stack`, `proxy-stack`, `step-ca-stack` | `deploy-monitoring-stack` |
| `netbox-stack` | platform | 40012 | `192.168.40.12/24` | `infra_seg` | Docker Compose | `harbor-stack` | `deploy-netbox-stack` |
| `portainer-stack` | platform | 20020 | `192.168.20.20/24` | `mgmt_seg` | Docker Compose | `[]` | `deploy-portainer-stack` |

## Candidate Deploy Order

This mirrors the current known-good stack sequencing used in the `pve-test`
rehearsal and production canaries.

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

## Candidate Destroy Order

This is the reverse dependency-oriented candidate order for the future
infra-only teardown planner. It intentionally destroys consumers before the
services they depend on.

1. `portainer-stack`
2. `netbox-stack`
3. `monitoring-stack`
4. `harbor-stack`
5. `authentik-stack`
6. `proxy-stack`
7. `step-ca-stack`
8. `dns-stack`
9. `ci-runner-01`
10. `apt-cacher-stack`

## Dry-Run Safety Contract

Any future `pve` infra-only teardown planner must prove all of the following
before a destructive execution path can even be proposed:

1. The target node is exactly `pve`.
2. The plan scope is limited to the ten stack directories and ten VMIDs listed
   above.
3. No destroy or replace action is proposed for any CT or VM outside that
   VMID set.
4. No storage action is proposed outside stack-owned resources attached to the
   in-scope stack directories.
5. No `pve-test` resource is referenced.
6. Live `pct list` / `qm list` output is captured so out-of-scope guests on
   `pve` are explicitly named in the approval packet as untouched.

## Live Inventory Refresh Requirement

The earlier `pvesh` evidence file at
`docs/productionize-refactor/evidence/step-ca-canary-20260523-093959/02-pvesh-node-pve.json`
is empty, so it must not be treated as a reliable current-production inventory
snapshot.

Before any real destroy approval packet is prepared, refresh live read-only
evidence from `pve` for:

- `pct list`
- `qm list`
- `pvesm status`
- per-stack `terragrunt plan -destroy`

## Notes

- This inventory is intentionally narrower than the full `docs/teardown-test`
  rehearsal inventory because the goal here is production infrastructure only,
  not generic validation guests.
- The future planner should consume this file or a mechanically equivalent
  source instead of hardcoding `docs/teardown-test/inventory.md`.
