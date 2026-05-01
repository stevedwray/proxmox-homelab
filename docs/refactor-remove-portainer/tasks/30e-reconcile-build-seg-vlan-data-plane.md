# Task 30e: Reconcile `build_seg` VLAN/data-plane path between Proxmox and the active MikroTik

## Type

Development

## Objective

Prove and, if needed, restore the L2/L3 carriage path for `build_seg` between
`pve-test` Proxmox SDN and the active MikroTik so that VMID `141` can reach its
gateway `10.57.0.1`.

This is a narrow network-plane task. It is not another `ci-runner-01`
functional retry. The immediate success criterion is gateway reachability on
`build_seg`, not full runner provisioning.

## Files

- `docs/refactor-remove-portainer/decisions.md`
- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/30e-reconcile-build-seg-vlan-data-plane.md`
- `docs/refactor-remove-portainer/prompts/30e-reconcile-build-seg-vlan-data-plane.yaml`
- `docs/refactor-remove-portainer/reports/30c-restore-ci-runner-apt-cacher-reachability-report.md`
- `docs/refactor-remove-portainer/reports/30d-reconcile-active-mikrotik-baseline-and-build-seg-carriage-report.md`
- `terraform/lxc/network/pve-test.yaml`
- `terraform/lxc/network/NETWORK_CONTRACT.md`
- `ansible/00-initial-setup/proxmox-sdn-setup.yml`
- any scoped Proxmox or MikroTik automation needed to make the VLAN path repeatable

## Preconditions

- Task 30d is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/30d-reconcile-active-mikrotik-baseline-and-build-seg-carriage-report.md`
  - that report must explicitly show `Status: complete`
- Treat the active runtime baseline as:
  - active MikroTik management IP `192.168.1.251`
  - `ci-runner-01` exists as VMID `141`
  - the current known failure is CT `141` cannot reach gateway `10.57.0.1`
- The fix must be repeatable in repo-managed code or clearly reported as
  outside current automation scope.
- Do not run Sonar or Snyk in this task. This is a live exploratory unblocker.

## Operations

1. Cut a clean short-lived branch from the current architecture-approved
   package baseline.
2. Verify `pve-test` targeting and confirm Task 30d evidence is present.
3. Reproduce the current gateway failure from VMID `141`.
4. Inspect the authoritative Proxmox SDN side and the active MikroTik VLAN/trunk
   side for the `build_seg` path.
5. Identify the smallest repo-managed change that reconciles the expected VLAN
   carriage path for `build_seg`.
6. Apply only the affected automation needed to activate that fix.
7. Validate that VMID `141` can reach `10.57.0.1`.
8. If gateway reachability is restored, validate a narrow next hop toward the
   infra segment, such as `10.57.3.11:3142`, without widening into full runner
   provisioning unless the task explicitly reaches clean success and the prompt
   still allows it.
9. Write the task report and stop. Do not start Task 31 automatically.

## Postconditions

- The `build_seg` gateway path is either restored repeatably in code, or the
  first remaining blocker is isolated precisely.
- The package gains authoritative evidence about whether the Proxmox↔MikroTik
  VLAN/data-plane path is now correct.
