# Task 01: Production Credential Controls

## Goal

Design and implement tight controls around any production credential exposure
to an AI-operated environment.

## Why This Comes First

Productionization will eventually require the repo and its automation paths to
understand `pve`. That is useful, but it increases risk if production secrets
can be loaded through the same casual path used for `pve-test`.

This task exists to ensure production access becomes more deliberate before it
becomes more convenient.

## Desired Outcome

- production credentials are not loaded by default
- production read-only access is separated from production mutation access
- production mutation access requires explicit additional approval
- the operator can still use AI for planning and read-only investigation
  without opening the door to accidental destructive changes

## Scope

In scope:

- design of production secret separation
- design of a separate production wrapper or equivalent gate
- read-only vs mutating command policy
- approval and evidence requirements

Out of scope:

- actual production service migration
- network or storage manifest authoring

## Recommended Design Direction

1. Keep `./with-secrets` dev-oriented and `pve-test`-safe.
2. Do not broaden the normal wrapper to load production secrets.
3. Create a separate production access path, likely `./with-secrets-prod`.
4. Use separate encrypted secret storage for production.
5. Require extra approval material for mutating production commands.

## Concrete Deliverables

- documented production secret separation model
- documented production wrapper behavior
- allowlist or command-class model for production operations
- required approval phrase, packet, or operator token design
- evidence/logging requirements for every production invocation

## Candidate Implementation Shape

- `terraform/secrets.pve-test.enc.yaml`
- `terraform/secrets.pve.enc.yaml`
- `with-secrets` remains default-safe for `pve-test`
- `with-secrets-prod` requires:
  - `PVE_ENV=pve`
  - `TF_VAR_proxmox_node=pve`
  - explicit approval token
  - command classification check

## Command Classes To Define

- read-only inventory
- read-only validation
- mutating infrastructure changes
- mutating migration/cutover operations

At minimum, the policy should distinguish:

- safe reads like `pct list`, `qm list`, `pvesm status`, `pvesh get`
- risky mutations like `terragrunt apply`, `pct destroy`, `pct set`,
  SDN writes, or firewall/network changes

## Files Likely Involved

- [with-secrets](/home/steve/git/proxmox-homelab/with-secrets:1)
- `with-secrets-prod` if introduced
- `terraform/secrets*.enc.yaml`
- docs under `docs/reference/` or this refactor directory

## Dependencies

- none for the design phase
- implementation should land before broad production secret usage

## Validation

- production secrets cannot be loaded accidentally via the default dev path
- read-only production access works only through the dedicated production path
- mutating production commands fail without the extra approval gate
- evidence/logging output is generated for production invocations

## Risks

- partial implementation could create a false sense of safety
- mixing prod and dev secrets in one wrapper increases accidental-target risk
- operator convenience pressure may weaken the controls unless the design is
  explicit and tested

## Suggested Branch

- `work/productionize-01-credential-controls`
