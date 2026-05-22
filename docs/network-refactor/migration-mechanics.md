# Migration Mechanics (Session 3 Decisions)

## Purpose

This document captures the Session 3 design decisions that unblock Session 4
implementation. It defines one recommended migration path from default
`ProxyJump` behavior to direct SSH for router-reachable SDN-backed guests.

Scope note:

1. This is a design contract only.
2. It does not change current Terraform or Ansible behavior by itself.

## Recommended Inventory Contract

For router-reachable SDN-backed stacks, generated inventory should follow this
contract:

1. `ansible_host` is the guest IP address.
2. `ansible_user` remains `root` unless stack-specific auth requirements say
   otherwise.
3. `ansible_ssh_common_args` for default SDN path does not include `ProxyJump`.
4. `pve_host` is compatibility metadata only for temporary fallback mode.
5. Inventory metadata should clearly state effective access mode (`direct` or
   `proxyjump_compat`) so operators can audit behavior quickly.

## Recommended `pve_host` Migration Logic

### Decision

Use attachment-type defaults with explicit per-stack compatibility override.

### Defaults

1. `sdn_vnet` attachment: default to direct SSH.
2. `bridge` attachment: preserve existing behavior during migration.

### Explicit compatibility control

Session 4 should introduce one stack-level selector:

```yaml
network:
  access_path: direct | proxyjump_compat
```

Rules:

1. For `sdn_vnet`, default is `direct` when `access_path` is absent.
2. `ProxyJump` is rendered only when `access_path: proxyjump_compat`.
3. `pve_host` presence alone is not enough to force ProxyJump for SDN-backed
   stacks after migration wiring.
4. For `bridge`, default behavior remains unchanged unless explicitly set to
   `access_path: direct`.

## Preflight Placement Decision

### Decision

Use a combination model with one validator implementation.

### Placement

1. Standalone validator is the source of truth for router reachability checks.
2. Validator is required before Terraform apply workflows.
3. Validator is re-used before Ansible provisioning for stacks marked
   `access_path: direct`.

### Why this model

1. One validator avoids duplicated check logic.
2. Pre-apply execution catches global readiness issues early.
3. Pre-provision execution catches per-stack access-path mismatch right before
   SSH-dependent work.

## Temporary Fallback Policy (`ProxyJump`)

### When fallback is allowed

1. Only when stack is explicitly labeled `access_path: proxyjump_compat`.
2. Only when a blocking direct-path issue is documented.

### Required labeling

Each fallback stack must carry migration labeling in adjacent docs or stack
comments with:

1. reason
2. owner
3. review date or remove-by target

### New stack policy

1. New SDN-backed stacks should not start in `proxyjump_compat` by default.
2. Any exception must include a documented blocker and removal plan.

### Removal criteria per stack

A stack can leave fallback mode only after all are true:

1. router preflight passes for that stack zone
2. one successful provisioning run with `access_path: direct`
3. no dependency on `prime_sdn_host_route` in that path

### Global gate condition

Default or unlabeled `ProxyJump` behavior must be removed before the
`pve-test` refactor validation gate can pass.

## Session 4 Implementation Targets

1. Update Terraform locals to parse and validate `network.access_path`.
2. Update inventory template logic to gate ProxyJump by effective access mode,
   not by non-empty `pve_host` alone.
3. Keep bridge-path compatibility as default during migration.
4. Surface effective access mode in generated inventory metadata.
5. Session 5 removed `prime_sdn_host_route`; do not add host-side route
   priming back into the compatibility path.

## Session 5 Outcome

1. Host-side `.254` route priming is no longer part of the Terraform apply
   flow.
2. The only remaining compatibility mechanism in the inventory contract is the
   explicit `proxyjump_compat` access path.
3. Any future direct-access failure should be handled by preflight evidence and
   stack-level labeling, not by reintroducing Proxmox host mutation.
