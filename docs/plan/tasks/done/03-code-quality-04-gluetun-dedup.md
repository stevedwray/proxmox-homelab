# 03-code-quality-04 — gluetun service deduplication (issue #49)

> Historical archived task. Useful for implementation history only.
> Do not use this as the current deployment procedure.
> Current workflow and environment rules live under `docs/workflow/`.

## Status

COMPLETE

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/93

## Phase

Phase 03 — Code Quality and Bug Fixes

## Prerequisites

- Phase 00 complete — branch is clean
- NetBox running at `192.168.1.30` (for verification)
- Python 3.12 available locally

## Objective

`populate.py` no longer registers `gluetun-6881` twice; running it against a clean NetBox produces exactly one service entry per (vm_id, name, port, protocol) tuple, and issue #49 is closed.

This task is already reflected in the codebase and issue #49 has been closed.

## Scope

- `terraform/lxc/stacks/netbox-stack/integrations/discover.py` — add `_dedup_services()` helper and call it before passing services downstream
- Possibly `populate.py` if deduplication is better placed there (read both files to decide)

## Out of Scope

- Changes to `proxmox_client.py` or `client.py`
- The cognitive complexity refactor (task 03-05) — if dedup naturally fits inside the refactored `build_full_topology()`, note that but implement the minimal fix here

## Inputs

- `terraform/lxc/stacks/netbox-stack/integrations/discover.py` — read the service-building function (around line 101)
- `terraform/lxc/stacks/netbox-stack/integrations/populate.py` — read `populate_ipam()` or equivalent
- `docs/plan/phase-03-code-quality.md` — Batch 4 for root cause and fix specification

## Expected Outputs

- `discover.py` — modified with `_dedup_services()` and its call site

## Constraints and Conventions

- Deduplication key is exactly `(vm_id, name, port, protocol)` — no other fields
- The dedup function must be a named helper, not an inline comprehension, so it can be unit-tested
- Running `populate.py` twice against a post-dedup clean NetBox must produce 0 objects on the second run

## Acceptance Criteria

- [ ] `_dedup_services()` function exists in `discover.py` (or `populate.py`)
- [ ] Function deduplicates on `(vm_id, name, port, protocol)`
- [ ] `populate.py` run on a fresh NetBox produces exactly one `gluetun-6881` entry
- [ ] Second `populate.py` run creates 0 objects (idempotency)
- [ ] Issue #49 closed on GitHub

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Fix a bug where the gluetun-6881 service is registered twice in NetBox because
duplicate entries appear in the discovery output before population.

BEFORE EDITING, READ THESE FILES IN FULL:
  terraform/lxc/stacks/netbox-stack/integrations/discover.py
  terraform/lxc/stacks/netbox-stack/integrations/populate.py
  docs/plan/phase-03-code-quality.md   (Batch 4 — root cause and fix spec)

ROOT CAUSE:
  gluetun-6881 appears twice in the services list — likely because port 6881 is listed for
  both TCP and UDP, generating two entries with the same name, or because torrent-stack
  appears in both Proxmox and Portainer discovery and services are merged without deduplication.

FIX: Add a deduplication function in discover.py:

  def _dedup_services(services: list[dict]) -> list[dict]:
      """Remove duplicate service entries by (vm_id, name, port, protocol)."""
      seen = set()
      result = []
      for svc in services:
          key = (svc.get("vm_id"), svc.get("name"), svc.get("port"), svc.get("protocol"))
          if key not in seen:
              seen.add(key)
              result.append(svc)
      return result

  Call _dedup_services() before passing the services list to populate_ipam() (or equivalent).
  The exact call site depends on where the services list is assembled — read the code to find it.

NOTE: If task 03-05 (cognitive complexity refactor) is done first, this dedup should be
placed inside the refactored build_full_topology() or its orchestration layer. If this task
is done before 03-05, add the call site at the most natural point in the current code.

VERIFY:
  source .env
  cd terraform/lxc/stacks/netbox-stack/integrations

  # Optional: wipe NetBox services for a clean test
  # (only if safe — do not wipe in production)

  python populate.py

  # Check that gluetun-6881 appears only once:
  curl -s -H "Authorization: Token ${NETBOX_SUPERUSER_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/services/?name=gluetun-6881" | jq .count
  # Expected: 1

  # Run again for idempotency:
  python populate.py
  # Expected: 0 objects created

COMMIT:
  git add terraform/lxc/stacks/netbox-stack/integrations/discover.py
  git commit -m "fix(netbox): deduplicate services before NetBox population (Closes #49)

gluetun-6881 was registered twice due to merged Proxmox+Portainer discovery.
Added _dedup_services() dedup on (vm_id, name, port, protocol)."

SECURITY SCAN (run before pushing — stop and present options if new issues are found):
  cd /home/steve/git/proxmox-homelab && source .env && sonar-scanner

  git push origin dev/pve-test
  gh issue close 49 --comment "Fixed — services deduplicated on (vm_id, name, port, protocol)."

DONE WHEN: gluetun-6881 has exactly one entry in NetBox and populate.py is idempotent.
```
