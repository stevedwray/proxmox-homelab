# Task 01: Define Edge Manifest Contract

## Type

Documentation and fixtures

## Objective

Define the v1alpha1 `EdgeManifest` contract for stack-owned browser provisioning.

## Scope

- Write the contract specification.
- Add valid and invalid fixture examples.
- Do not implement validators or renderers.
- Do not deploy anything.

## Required Contract Decisions

The contract must define:

- `apiVersion: homelab.gibbsgreatly.xyz/v1alpha1`
- `kind: EdgeManifest`
- `metadata.name`
- `metadata.stack`
- `spec.routes[]`
- route hostnames
- route backend target type
- DNS target
- TLS resolver
- auth mode
- validation expectations

## Required Backend Types

The contract must support:

- `url`: standard upstream URL such as `http://10.57.1.20:9000`
- `traefikService`: special Traefik service target such as `api@internal`

## Required Auth Modes

The contract must support:

- `none`
- `forwardAuth`
- `native`
- `oidc`

## Required Valid Fixtures

Create valid fixtures for all current browser services:

- `authentik.lab.gibbsgreatly.xyz`
- `portainer.lab.gibbsgreatly.xyz`
- `harbor.lab.gibbsgreatly.xyz`
- `netbox.lab.gibbsgreatly.xyz`
- `grafana.lab.gibbsgreatly.xyz`
- `traefik.lab.gibbsgreatly.xyz`

## Required Invalid Fixtures

Create invalid fixtures that cover at least:

- duplicate hostnames
- hostname outside `.lab.gibbsgreatly.xyz`
- missing backend
- invalid auth mode
- `forwardAuth` on Authentik itself
- `forwardAuth` on Harbor
- `url` backend missing scheme
- `traefikService` backend used with a non-Traefik service

## Validation Rules

Document rules for:

- unique hostnames across all manifests
- unique Traefik router names across all manifests
- pve-test domain suffix
- allowed TLS resolvers
- DNS target must be Traefik edge IP for browser routes
- auth mode and backend compatibility
- no deletes or runtime actions in contract validation

## Done When

- The spec is unambiguous enough for another agent to implement the validator.
- Fixtures are sufficient for validator unit tests.

## Stop Conditions

- Stop if a required service cannot be represented without inventing an
  undocumented field. Document the gap first.
