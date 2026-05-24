# pve Infra-Only Proof Rerun Handback

Date: 2026-05-24
Branch: work/productionize-06-canary-validation
HEAD: `860df0a` `fix(prod): recover netbox bootstrap on pve`
Task approval: `pve-infra-proof-rerun-20260524`
Scope: fresh full infra-only teardown/rebuild proof on production `pve`, limited to the 10 approved infrastructure stacks from the execution packet.

## Starting State Used

This run started from the current repaired branch state exactly as requested:

- branch `work/productionize-06-canary-validation`
- HEAD `860df0a` `fix(prod): recover netbox bootstrap on pve`
- no stash was applied
- no scope was broadened beyond the 10 approved infrastructure stacks on `pve`

Accepted starting condition carried into this run:

- `portainer-stack` was absent on `pve` from the previously stopped proof attempt

## Controlling Procedure

The run followed:

- `docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md`

Inputs used:

- `TASK_APPROVAL=pve-infra-proof-rerun-20260524`
- `NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true`
- `NETWORK_SDN_EXPECTED_TARGET=pve`
- `NETWORK_SDN_EXPECTED_PVE_HOST=pve.gibbsgreatly.xyz`

## Evidence Paths

Planner/preflight evidence:

- `docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260524-015437/`

Execution evidence:

- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/`

Key preflight and review artifacts:

- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/target-node.txt`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/gh-auth-status.txt`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/pre-destroy-human-review.txt`
- `docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260524-015437/summary.md`

Key stop-state artifacts:

- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/stack-outcome-summary.tsv`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/provision-portainer-stack.log`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/post-failure-pct-list-ssh.log`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/post-failure-qm-list-ssh.log`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/post-failure-pvesm-status.log`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/post-failure-portainer-ct.log`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/operator-summary.txt`

## Preflight Result

Preflight passed for the intended target:

- `TF_VAR_proxmox_node=pve`
- GitHub CLI auth healthy
- fresh planner stamp `20260524-015437` generated successfully

Advisory review result before destroy:

- no planner blocker surfaced
- no unexpected broadening beyond the approved 10-stack scope was identified
- `portainer-stack` was the only missing in-scope guest at start, which matched the expected starting condition
- the reviewed out-of-scope guest inventory matched the packet's protected set in intent, including `pve-test` remaining out of scope

## Destroy Outcomes

Destroy phase completed for all 10 approved stacks in packet order.

Per-stack destroy outcome:

- `portainer-stack`: ok
- `netbox-stack`: ok
- `monitoring-stack`: ok
- `harbor-stack`: ok
- `authentik-stack`: ok
- `proxy-stack`: ok
- `step-ca-stack`: ok
- `dns-stack`: ok
- `ci-runner-01`: ok
- `apt-cacher-stack`: ok

Destroy evidence is captured in the per-stack logs under:

- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/destroy-*.log`

## Apply And Provision Outcomes

Apply phase completed for all 10 approved stacks.

Provision phase succeeded for 9 of 10 approved stacks.

Per-stack outcomes:

| Stack | Destroy | Apply | Provision |
|---|---|---|---|
| `portainer-stack` | ok | ok | failed |
| `netbox-stack` | ok | ok | ok |
| `monitoring-stack` | ok | ok | ok |
| `harbor-stack` | ok | ok | ok |
| `authentik-stack` | ok | ok | ok |
| `proxy-stack` | ok | ok | ok |
| `step-ca-stack` | ok | ok | ok |
| `dns-stack` | ok | ok | ok |
| `ci-runner-01` | ok | ok | ok |
| `apt-cacher-stack` | ok | ok | ok |

Authoritative per-stack summary:

- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/stack-outcome-summary.tsv`

## Portainer Failure Details

The proof stopped at `portainer-stack` provision.

`portainer-stack` infrastructure apply succeeded and recreated CT `20020`, but `./scripts/provision.sh --stack portainer-stack` failed during the edge reconcile/apply step.

Captured failure indicators from `provision-portainer-stack.log`:

- `EGR200`: target preflight command failed because `./with-secrets` refused `PVE_ENV=pve` and still expected `pve-test`
- `EGR211`: Authentik discovery reported drift/issues
- the Portainer route discovery reported the owned Authentik application/provider as missing
- reconcile mode remained `dry-run`, and the overall reconcile result ended with `"status": "failed"`

This was treated as the packet stop condition. No additional repair-in-place work was attempted after the failure.

## Post-Redeploy Validation Result

Packet post-redeploy validation did not run.

Reason:

- the run stopped at `portainer-stack` provision failure before the packet could proceed to post-redeploy `pct`/`qm`/`pvesm` validation and the per-stack post-plan drift checks

Result:

- post-redeploy validation outcome: not reached because the proof stopped on a redeploy-phase blocker

## Was Portainer Restored?

Yes, partially.

`portainer-stack` was restored at the infrastructure/container level:

- CT `20020` exists again on `pve`
- CT `20020` is `running`
- hostname is `portainer-stack`
- memory is `512`
- network is `192.168.20.20/24` on `tvmgmt`

Evidence:

- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/apply-portainer-stack.log`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/post-failure-portainer-ct.log`

However, stack provisioning did not converge, so Portainer restoration was not complete at the service/integration layer.

## Were Out-Of-Scope Guests Untouched?

Yes, based on the authoritative post-failure `ssh pve` inventory snapshots.

Observed protected out-of-scope CTs remained present:

- `100` `torrent-stack`
- `101` `management-stack`
- `102` `media-stack`
- `103` `gaming-stack`
- `104` `cloud-stack`
- `105` `proxmox-backup-server`
- `107` `wazuh`
- `109` `security-stack`
- `110` `analysis-stack`
- `112` `elastic-stack`
- `114` `omada-controller`
- `115` `scanning-stack`
- `116` `ai-stack`
- `131` `test-docker`
- `910` `debian13-template-builder`

Observed protected out-of-scope VMs remained present:

- `106` `securityonion`
- `108` `securityonion-idh`
- `111` `wifi-analysis`
- `113` `pve-test`
- `120` `metasploitable`

No evidence from the run indicates mutation against those protected out-of-scope guests.

## Overall Result

Overall result: failed.

What was proven:

- the run started from the repaired NetBox branch state
- the full approved destroy phase succeeded
- the full approved apply phase succeeded
- 9 of 10 approved provisions succeeded
- `netbox-stack` again applied and provisioned successfully during the full proof run
- `portainer-stack` CT infrastructure was recreated on `pve`
- out-of-scope guests remained present and untouched in the authoritative post-failure inventory

What was not proven:

- full end-to-end infra-only proof success on `pve`
- packet post-redeploy validation completion
- complete Portainer service/integration restoration

## Remaining Blockers

Primary blocker:

- `portainer-stack` provision fails because the edge reconcile path still contains production-incompatible targeting/preflight behavior and reports Authentik-owned route objects missing

Next operator action:

- fix the `portainer-stack` provision/reconcile-edge production targeting and Authentik route-object creation path in source
- then rerun the full infra-only proof packet from a fresh execution stamp rather than continuing from this stopped state
