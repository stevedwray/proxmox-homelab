# 03-code-quality-05 — Cognitive complexity refactor (issue #28)

## Status

COMPLETE

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/94

## Phase

Phase 03 — Code Quality and Bug Fixes

## Prerequisites

- Task 03-04 complete (or do this task first and fold dedup into the refactor)
- Python 3.12 available locally
- NetBox running at `192.168.1.30` for idempotency verification

## Objective

The three high-complexity functions in the NetBox integration scripts are refactored to ≤20 cognitive complexity each, NetBox integration remains idempotent (second `populate.py` run creates 0 objects), and issue #28 is closed.

This task is already reflected in the codebase and issue #28 has been closed.

## Scope

- `terraform/lxc/stacks/netbox-stack/integrations/discover.py` — `build_full_topology()` (complexity ~70) extracted into sub-functions
- `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py` — large function (complexity ~53) extracted into helpers
- `terraform/lxc/stacks/netbox-stack/integrations/populate.py` — most complex function (complexity ~20) extracted if needed

## Out of Scope

- Changing the external interface of `discover.py` or `populate.py` (callers must not need to change)
- Altering NetBox data model or schema
- Tests/test framework setup (out of scope for this repo currently)

## Inputs

- Read all three files in full before refactoring
- `docs/plan/phase-03-code-quality.md` — Batch 5 for sub-function naming guidance
- Understand the data flow: `proxmox_client.py` → `discover.py` → `populate.py`

## Expected Outputs

- `discover.py` — `build_full_topology()` extracted into at least `_discover_proxmox_vms()`, `_enrich_from_portainer()`, `_enrich_from_stack_yaml()`, `_dedup_services()`, `_build_topology()`
- `proxmox_client.py` — nested conditionals extracted into private helper methods
- `populate.py` — most complex sub-section extracted if complexity > 20

## Constraints and Conventions

- Public function signatures must not change (callers outside the module must keep working)
- Each new helper must have a docstring explaining its single responsibility
- `_dedup_services()` from task 03-04 may be absorbed here — avoid duplicating it
- Idempotency is the primary correctness criterion
- Do not add unit test files (not in scope for this repo currently)

## Acceptance Criteria

- [ ] `build_full_topology()` in `discover.py` has cognitive complexity ≤20 (verify by reading or running a complexity checker)
- [ ] Large function in `proxmox_client.py` has cognitive complexity ≤20
- [ ] `populate.py` most complex function has cognitive complexity ≤20
- [ ] `python populate.py` against live NetBox exits 0
- [ ] Second `python populate.py` run creates 0 objects (idempotency preserved)
- [ ] `ansible-lint terraform/lxc/ansible/` still passes at 0 violations
- [ ] Issue #28 closed on GitHub

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Refactor three high-complexity functions in the NetBox integration scripts to reduce
their cognitive complexity below 20. This is a pure refactor — external behavior must not change.

BEFORE EDITING, READ THESE FILES IN FULL:
  terraform/lxc/stacks/netbox-stack/integrations/discover.py
  terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py
  terraform/lxc/stacks/netbox-stack/integrations/populate.py
  terraform/lxc/stacks/netbox-stack/integrations/client.py     (understand NetBoxClient API)
  docs/plan/phase-03-code-quality.md                           (Batch 5 — sub-function naming guidance)

DATA FLOW:
  proxmox_client.py → discover.py → populate.py
  proxmox_client.py queries Proxmox API for VMs/LXCs
  discover.py builds a merged topology (Proxmox + Portainer + stack.yaml metadata)
  populate.py writes the topology to NetBox via client.py

TACKLE IN THIS ORDER:

1. discover.py — build_full_topology() (highest complexity ~70)
   Extract into these sub-functions (adjust names if the code structure differs):
   - _discover_proxmox_vms()         — query Proxmox for all VMs/LXCs
   - _enrich_from_portainer()        — merge Portainer service data into VM records
   - _enrich_from_stack_yaml()       — merge stack.yaml metadata into VM records
   - _dedup_services()               — deduplicate services on (vm_id, name, port, protocol)
                                       (absorb from task 03-04 if already done, else add here)
   - build_full_topology()           — orchestrate the above and return merged result
   Each sub-function should be ≤20 complexity and have a single clear responsibility.

2. proxmox_client.py — large function (~complexity 53)
   Find the function around line 123. Extract nested conditionals into private methods.
   Common patterns: building a network interface dict, parsing VM config fields.
   Name helpers descriptively: _parse_network_config(), _build_vm_record(), etc.

3. populate.py — if any function exceeds complexity 20, extract its most complex sub-section.

VERIFY:
  source .env
  cd terraform/lxc/stacks/netbox-stack/integrations

  python populate.py
  # Must exit 0

  python populate.py   # run TWICE
  # Second run must create 0 new objects

COMMIT:
  git add terraform/lxc/stacks/netbox-stack/integrations/
  git commit -m "refactor(netbox): reduce cognitive complexity in integration scripts (Closes #28)

discover.py: build_full_topology split into 5 focused sub-functions (70 → <15)
proxmox_client.py: extract nested conditionals to helpers (53 → <20)
populate.py: extract complex sub-section if needed (20 → <20)

Idempotency verified: populate → re-run yields 0 new objects."

SECURITY SCAN (run before pushing — stop and present options if new issues are found):
  cd /home/steve/git/proxmox-homelab && source .env && sonar-scanner

  git push origin dev/pve-test
  gh issue close 28 --comment "Refactored. Complexity reduced in all three files. Idempotency preserved."

DONE WHEN: All functions ≤20 complexity, populate.py idempotent, issue #28 closed.
```
