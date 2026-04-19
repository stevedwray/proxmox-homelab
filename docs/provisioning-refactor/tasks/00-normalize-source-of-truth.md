# Task 00: Normalize Source Of Truth

## Type

Documentation

## Objective

Make `docs/provisioning-refactor/` the active source of truth for stack-owned
edge provisioning and mark older Phase 04c/MikroTik DNS instructions as legacy
context.

## Files

- `docs/provisioning-refactor/README.md`
- `docs/provisioning-refactor/decisions.md`
- `docs/provisioning-refactor/task-sequence.md`
- `docs/provisioning-refactor/prompts/index.yaml`
- `docs/plan/phase-04c-stack-owned-ingress-auth-dns.md`
- `docs/prompts/index.yaml`

## Preconditions

- None.

## Operations

1. Point future agents at `docs/provisioning-refactor/`.
2. State that CoreDNS, not MikroTik static records, is the long-term lab browser
   record authority.
3. State that apex `*.gibbsgreatly.xyz` pve-test instructions are legacy
   context when they conflict with `*.lab.gibbsgreatly.xyz`.
4. Ensure old prompt indexes reference the new provisioning-refactor prompt
   index rather than their stale Phase 04c task docs.

## Postconditions

- No active refactor instruction points agents at the deprecated MikroTik static
  DNS path for lab browser records.
- The new 22-task sequence is discoverable from the README and prompt index.

## Validation

- `rg -n "LEGACY|superseded_by|docs/provisioning-refactor" docs/plan/phase-04c-stack-owned-ingress-auth-dns.md docs/prompts/index.yaml`
- `rg -n "MikroTik static records as the long-term|MikroTik static DNS path" docs/provisioning-refactor`
- `git diff --name-only`

## Stop Conditions

- Stop if resolving a conflict requires functional Terraform, Ansible, or script
  changes.
