# Task 12: CoreDNS Publish Wiring

## Type

Development

## Objective

Let CoreDNS deployment consume generated zone output, validate it, publish it,
and reload/restart safely.

## Files

- `terraform/lxc/ansible/playbooks/deploy-coredns.yml`
- `terraform/lxc/ansible/files/coredns-lab.zone` if seed cleanup is needed

## Preconditions

- Task 08 complete.

## Operations

1. Add an optional generated zone source path.
2. Validate the selected zone before publishing.
3. Preserve safe default behavior for the seed zone.
4. Reload or restart CoreDNS safely after zone changes.
5. Validate authoritative answers after publish.

## Postconditions

- Generated DNS can be deployed without ad-hoc router or static-record edits.

## Validation

- YAML parses.
- Existing default seed-zone deploy path still works.

## Stop Conditions

- Stop if generated-zone publication would remove required non-browser records.
