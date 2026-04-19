# Task 05: Manifest Validator

## Type

Development

## Objective

Implement side-effect-free validation of
`terraform/lxc/stacks/*/edge.yaml`.

## Files

- `terraform/lxc/edge_manifest.py`
- `terraform/lxc/validate-edge-manifests.py`
- `terraform/lxc/test_edge_manifest.py`

## Preconditions

- Task 04 complete.

## Operations

1. Discover manifests under `terraform/lxc/stacks/*/edge.yaml`.
2. Parse YAML using structured validation.
3. Validate required fields, allowed values, backend/auth/TLS/DNS policy, and
   pve-test host suffix.
4. Validate cross-manifest uniqueness for hostnames and router names.
5. Emit human-readable and machine-readable output.
6. Add tests using valid and invalid fixtures.

## Postconditions

- Validator has no deployment, rendering, or runtime side effects.

## Validation

- `python3 -m unittest terraform/lxc/test_edge_manifest.py`
- Valid fixtures pass; invalid fixtures fail with stable error codes.

## Stop Conditions

- Stop if Task 04 is ambiguous.
