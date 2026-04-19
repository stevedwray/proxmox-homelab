# Task 06: Legacy Route Inventory

## Type

Development, read-only

## Objective

Extract central Traefik host rules from the legacy proxy playbook for renderer
collision and intended-replacement checks.

## Files

- `terraform/lxc/edge_manifest.py` or
  `terraform/lxc/extract-legacy-edge-hosts.py`
- `terraform/lxc/test_edge_manifest.py` or matching focused test file

## Preconditions

- Task 05 complete.

## Operations

1. Read `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`.
2. Extract legacy `Host(...)` rules without modifying the playbook.
3. Report host, router name, and source location where possible.
4. Add tests for current central routes and malformed playbook snippets.

## Postconditions

- Tooling can distinguish accidental duplicate hosts from one intended
  migration replacement host.

## Validation

- `python3 -m unittest terraform/lxc/test_edge_manifest.py`
- Extracted host list includes the current six browser hosts.

## Stop Conditions

- Stop if route extraction requires executing Ansible or contacting pve-test.
