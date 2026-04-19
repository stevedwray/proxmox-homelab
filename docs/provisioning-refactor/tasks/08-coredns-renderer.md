# Task 08: CoreDNS Renderer

## Type

Development

## Objective

Render deterministic CoreDNS lab-zone output from seed records plus validated
browser manifests.

## Files

- `terraform/lxc/render-edge-coredns.py`
- focused renderer tests

## Preconditions

- Task 05 complete.

## Operations

1. Read the seed zone file and validated manifests.
2. Preserve SOA, NS, and non-browser records.
3. Render browser records from manifests to `10.57.2.10`.
4. Reject duplicate generated records.
5. Produce dry-run diff output.
6. Validate MikroTik conditional forwarding only in live validation mode.

## Postconditions

- Browser DNS state is derivable from stack manifests without MikroTik static
  record edits.

## Validation

- Renderer tests pass.
- Generated zone parses with available DNS tooling or a structured parser.

## Stop Conditions

- Stop if a browser hostname still needs a direct backend record and no
  exception is documented.
