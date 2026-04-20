# Task 02: Inventory Scope And Dependency Order

## Type

Documentation

## Objective

Produce the exact stack scope and rebuild order for the rehearsal.

## Files

- `docs/teardown-test/variables.md`
- `docs/teardown-test/runbook.md`
- `terraform/lxc/stacks/*/stack.yaml`
- `docs/design/bootstrap.md` (read-only)

## Preconditions

- Task 01 complete.

## Operations

1. List selected stacks, VMIDs, IPs, zones, and `depends_on` entries.
2. Classify each stack as Stage 1/2 foundation, Stage 3a edge foundation, or
   Stage 3b remaining platform.
3. Verify `proxy-stack` remains independent of `authentik-stack` so Traefik can
   bootstrap before Authentik.
4. Identify any other dependency that conflicts with the documented bootstrap
   order.
5. Decide whether each conflict is code to fix, an execution override, or a
   documentation correction.
6. Write the final approved deploy order into `variables.md`.

## Postconditions

- Destroy order and deploy order are explicit.
- Stage 3a bootstrap conflicts are resolved before teardown.

## Validation

- `rg -n "depends_on|vmid|ip_address|ansible_playbook" terraform/lxc/stacks/*/stack.yaml`

## Stop Conditions

- Stop if `proxy-stack`, `authentik-stack`, CoreDNS, or step-ca ordering cannot
  be made consistent with the bootstrap model.
- Stop if `headscale-stack` is moved into scope without an active `stack.yaml`
  and a state plan.
