# Task 07: Incremental Migration Plan

## Goal

Define the real service migration order and per-service cutover strategy for
moving workloads from `pve-test` to `pve`.

## Objective

Turn the broad productionization strategy into a service-by-service migration
plan that can be executed gradually.

## Deliverables

- ranked service migration order
- per-service dependency notes
- collision and coexistence notes
- rollback guidance per service
- pre-cutover checks for reused IPs, hostnames, and live counterpart state
- explicit statement of whether each service is:
  - parallel-first
  - cutover-first
  - adopt-in-place

## Suggested Ordering Principles

Move earlier:

- least stateful
- least identity-sensitive
- least dependency-heavy

Move later:

- ingress and auth
- services with production name collisions already present
- services that many others depend on

## Candidate Ordering

Early:

- disposable test LXC
- `apt-cacher-stack`
- `dns-stack`

Middle:

- `step-ca-stack`
- `monitoring-stack`
- `portainer-stack`

Late:

- `proxy-stack`
- `authentik-stack`
- `netbox-stack`
- `harbor-stack`

## Collision-Aware Notes

Task 06 proved that production provisioning on `pve` works, but it also exposed
an operational cutover risk:

- `apt-cacher-stack` reused `192.168.40.11` on both `pve-test` and `pve`
- the `pve-test` counterpart was still running when the `pve` canary came up
- future migrations must stop or destroy the `pve-test` counterpart before
  reusing the same service IP on `pve`

Known existing production role/name overlaps:

- `harbor-stack`
- `netbox-stack`
- `management-stack`

These need explicit cutover treatment and should not be treated like empty-slot
deployments.

## Files Likely Involved

- this refactor doc set
- service stack docs under `terraform/lxc/stacks/*`
- environment manifests once they exist

## Dependencies

- task 06 canary validation has completed and should inform the migration rules

## Validation

- migration order reflects actual canary findings
- every service has a clear entry in the migration sheet
- each service has explicit collision checks before cutover
- dependencies and rollback assumptions are documented before execution begins

## Risks

- planning migration order too early before the network gate is proven
- underestimating service identity collisions
- starting with a central service and increasing recovery complexity

## Suggested Branch

- `work/productionize-07-migration-plan`
