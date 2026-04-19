# Task 04: Implement DNS Zone Renderer

## Type

Development

## Objective

Generate CoreDNS lab-zone records from edge manifests and validate MikroTik
delegation.

## Scope

- CoreDNS is the record authority for `lab.gibbsgreatly.xyz`.
- MikroTik static records are not the target store for these browser records.
- Do not deploy or reload CoreDNS in this task unless explicitly scoped.

## Steps

1. Read valid manifests after Task 02 validation.
2. Extract DNS records for browser routes.
3. Render deterministic CoreDNS zone content or an include file.
4. Preserve required SOA, NS, and non-browser records.
5. Make browser host records point to Traefik edge IP `10.57.2.10`.
6. Add dry-run diff output.
7. Add validation that MikroTik has conditional forwarding for
   `lab.gibbsgreatly.xyz`.
8. Add tests for:
   - new records
   - changed records
   - no-op render
   - duplicate host rejection via validator

## Validation

- Generated zone file parses with CoreDNS tooling or a DNS-zone parser if
  available.
- `traefik.lab.gibbsgreatly.xyz` remains resolvable.
- Browser records all target `10.57.2.10`.

## Done When

- DNS state is derivable from stack manifests without ad-hoc MikroTik static
  record edits.

## Stop Conditions

- Stop if the current runtime still depends on MikroTik static records for a
  hostname being migrated. Document the observed conflict before changing DNS.
