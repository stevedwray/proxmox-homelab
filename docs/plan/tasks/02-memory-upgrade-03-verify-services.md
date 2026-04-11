# 02-memory-upgrade-03 — Verify services healthy after pve-test restart

## Status

PENDING

## Phase

Phase 02 — pve-test Memory Upgrade (32 GB)

## Prerequisites

- Task 02-02 complete: pve-test VM is at 32 GB and LXCs have been restarted

## Objective

Harbor, NetBox, and ci-runner-01 are all confirmed healthy after the pve-test memory resize, issue #67 is closed, and the phase is complete.

## Scope

- Health-check Harbor API (`/api/v2.0/ping`)
- Health-check NetBox API
- Verify GitHub Actions runner is online
- Close issue #67

## Out of Scope

- Any code changes or Terraform modifications
- Phase 04 deployment planning (blocked until this phase is complete)

## Inputs

- `HARBOR_ADMIN_PASSWORD` from `.env`
- `NETBOX_SUPERUSER_API_TOKEN` from `.env`
- GitHub CLI (`gh`) authenticated

## Expected Outputs

- Issue #67 closed
- No file changes

## Constraints and Conventions

- Do not proceed to Phase 04 until all health checks here pass
- If any service fails to start, check container logs via `pct exec <vmid> -- docker logs <container>` before escalating

## Acceptance Criteria

- [ ] `curl -k https://192.168.1.10/api/v2.0/ping` returns `"Pong"`
- [ ] `curl http://192.168.1.30/api/` returns JSON with API version info
- [ ] `gh api repos/stevedwray/proxmox-homelab/actions/runners --jq '.runners[] | {name, status}'` shows `ci-runner-pve-test` as online
- [ ] Issue #67 closed with a comment referencing the resize

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Verify that Harbor, NetBox, and the CI runner are all healthy after the pve-test
memory upgrade. Then close issue #67.

This is a verification-only task — no code changes are needed.

STEP 1 — Source environment:
  source .env

STEP 2 — Harbor health check:
  curl -k https://192.168.1.10/api/v2.0/ping
  # Expected: "Pong"
  # If this fails, check Harbor LXC (VMID 121) on pve-test:
  #   ssh root@pve-test.gibbsgreatly.xyz "pct exec 121 -- docker ps"

STEP 3 — NetBox health check:
  curl http://192.168.1.30/api/
  # Expected: JSON response with API version field

STEP 4 — CI runner health check:
  gh api repos/stevedwray/proxmox-homelab/actions/runners \
    --jq '.runners[] | {name, status}'
  # Expected: ci-runner-pve-test with status: online

STEP 5 — Close issue #67:
  gh issue close 67 --comment "pve-test VM resized to 32 GB. Harbor, NetBox, and CI runner all
healthy post-restart. Observed working sets documented in prior commit (task 02-01)."

TROUBLESHOOTING:
  If a service is not healthy after ~5 minutes:
  - Check LXC running: ssh root@pve-test.gibbsgreatly.xyz "pct list"
  - Check Docker: ssh root@pve-test.gibbsgreatly.xyz "pct exec <vmid> -- docker ps"
  - Check logs: ssh root@pve-test.gibbsgreatly.xyz "pct exec <vmid> -- docker logs <container>"

DONE WHEN: All three health checks pass and issue #67 is closed.
Phase 02 is now complete. Phase 04 deployment is unblocked.
```
