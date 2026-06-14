# Portainer Production Targeting Fix Handback

Date: 2026-05-24
Branch: `work/productionize-06-canary-validation`
HEAD at start of task: `860df0a` `fix(prod): recover netbox bootstrap on pve`
Task approval: `portainer-prod-targeting-fix-20260524`
Scope: narrow source fix for the remaining `portainer-stack` production provision blocker, followed by a single targeted rerun on `pve`.

## Inputs Used

Started from the requested artifacts:

- `docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md`
- `docs/productionize-refactor/handoffs/31-portainer-prod-targeting-fix.md`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/provision-portainer-stack.log`

Fresh execution evidence for this repair is under:

- `docs/productionize-refactor/evidence/portainer-prod-targeting-fix-20260524-150822/`

Key logs:

- `docs/productionize-refactor/evidence/portainer-prod-targeting-fix-20260524-150822/logs/target-node.txt`
- `docs/productionize-refactor/evidence/portainer-prod-targeting-fix-20260524-150822/logs/provision-portainer-stack.log`
- `docs/productionize-refactor/evidence/portainer-prod-targeting-fix-20260524-150822/logs/provision-exit-code.txt`
- `docs/productionize-refactor/evidence/portainer-prod-targeting-fix-20260524-150822/logs/post-run-portainer-ct.log`

## Actual Proven Root Cause

The actual proven blocker was the target-preflight implementation in `terraform/lxc/reconcile-edge.py`, not the Authentik create path.

Specifically:

- apply-mode reconcile always validated the target by shelling out through `./with-secrets`
- that wrapper is intentionally `pve-test`-oriented and refused production `PVE_ENV=pve`
- the Portainer rerun therefore failed with `EGR200` before the Authentik create/apply path was allowed to execute
- the previously observed missing Portainer Authentik objects were real drift, but they were not the first proven blocker because reconcile had remained blocked before live apply

## Files Changed

Source change:

- `terraform/lxc/reconcile-edge.py`

Tracked handback added:

- `docs/productionize-refactor/handoffs/31-portainer-prod-targeting-fix-handback.md`

Evidence captured:

- `docs/productionize-refactor/evidence/portainer-prod-targeting-fix-20260524-150822/`

## Source Fix Applied

`terraform/lxc/reconcile-edge.py` now resolves the target preflight wrapper from the requested target instead of hardcoding the dev wrapper.

Behavior after the change:

- expected target `pve-test` uses `with-secrets`
- expected target `pve` uses `with-secrets-prod`
- optional `EDGE_TARGET_PREFLIGHT_COMMAND` override remains available
- the reconcile JSON now reports the resolved preflight command actually used

No broader stack logic was changed.

## Validation Performed

Local focused validation before production rerun:

- imported `terraform/lxc/reconcile-edge.py` with a Python 3.14-safe loader and verified wrapper resolution for both `pve-test` and `pve`

Production target confirmation:

- `TASK_APPROVAL=portainer-prod-targeting-fix-20260524 ./with-secrets-prod bash -lc 'echo $TF_VAR_proxmox_node'`
- result: `pve`

Targeted production rerun only:

- `TASK_APPROVAL=portainer-prod-targeting-fix-20260524 ./with-secrets-prod ./scripts/provision.sh --stack portainer-stack`

Post-run live-state confirmation:

- `TASK_APPROVAL=portainer-prod-targeting-fix-20260524 ./with-secrets-prod ssh -F /dev/null root@pve 'pct status 20020 && pct config 20020 | egrep "^(hostname|memory|net0):"'`

## Outcome

### Is `EGR200` resolved?

Yes.

The rerun log shows:

- preflight targeting command resolved to `/home/steve/git/proxmox-homelab/with-secrets-prod bash -c echo $TF_VAR_proxmox_node`
- preflight detail: `target preflight passed (pve)`
- no top-level issues remained in reconcile output

### Did reconcile reach apply mode on `pve`?

Yes.

The rerun log shows:

- `"mode": "apply"`
- `"status": "passed"`
- Authentik reconcile request methods included `POST`
- `"write_count": 2`

### Were missing Authentik-owned Portainer route objects created?

Yes.

The targeted rerun created both previously missing objects:

- application: `edge-portainer-stack-portainer-app`
- provider: `edge-portainer-stack-portainer-provider`

Post-apply discovery then reported the Portainer route as `matching` with identifiers:

- application id `4e21d9b5-1669-4426-a968-dc1db575b57c`
- provider id `2`

### Does `portainer-stack` provision now succeed?

Yes.

Evidence:

- `provision-exit-code.txt` contains `0`
- `provision-portainer-stack.log` ends with `Completed provision orchestration`
- the Portainer Ansible play recap finished with `failed=0`

### Resulting live state on `pve`

Confirmed after the rerun:

- CT `20020` status: `running`
- hostname: `portainer-stack`
- memory: `512`
- network: `192.168.20.20/24` on `tvmgmt`

## Ready For Another Fresh Full Proof Rerun?

Yes, with the narrow blocker resolved.

What is now proven:

- the production-target preflight path no longer blocks Portainer with `EGR200`
- Portainer reconcile reached real apply mode on `pve`
- the missing Authentik-owned Portainer route objects were created successfully
- the isolated `portainer-stack` provision rerun converged successfully

What is not claimed here:

- this handback does not itself re-prove the full infra-only packet from a fresh destroy/apply cycle

Based on the isolated rerun, the repository is ready for the next fresh full proof rerun when requested.
