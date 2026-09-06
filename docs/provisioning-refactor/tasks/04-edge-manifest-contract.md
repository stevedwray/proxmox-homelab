# Task 04: EdgeManifest Contract

## Type

Documentation and fixtures

## Objective

Define the `EdgeManifest` v1alpha1 contract before validation, rendering, or
reconciliation code is written.

## Files

- `docs/provisioning-refactor/edge-manifest-v1alpha1.md`
- `docs/provisioning-refactor/fixtures/valid/*.yaml`
- `docs/provisioning-refactor/fixtures/invalid/*.yaml`
- `docs/provisioning-refactor/fixtures/error-catalog.md`

## Preconditions

- Tasks 00 through 03 complete.

## Operations

1. Define `apiVersion`, `kind`, `metadata.name`, `metadata.stack`, and
   `spec.routes[]`.
2. Define backend types `url` and `traefikService`.
3. Define auth modes `none`, `forwardAuth`, `native`, and `oidc`.
4. Define DNS target, TLS resolver, validation expectations, and compatibility
   rules.
5. Add valid fixtures for Authentik, Harbor, Grafana, Portainer, NetBox, and
   Traefik dashboard.
6. Add invalid fixtures for duplicate host, bad domain, missing backend, bad
   auth mode, Authentik self-forward-auth, Harbor forward-auth, bad URL scheme,
   and invalid `traefikService` use.

## Postconditions

- Another agent can implement the validator without inventing fields.

## Validation

- Fixture YAML parses.
- Contract explicitly says browser DNS records target `192.168.30.10`.

## Stop Conditions

- Stop if a current browser service cannot be represented without an
  undocumented field.
