# NetBox Memory Rerun Handback

Date: 2026-05-24
Branch: work/productionize-06-canary-validation
Task approval: netbox-memory-rerun-20260524
Scope: Apply the already-prepared NetBox source changes on production `pve`, keep scope limited to `netbox-stack`, confirm the memory increase on CT `40012`, and rerun only `./scripts/provision.sh --stack netbox-stack`.

## Starting Point

This run started from:

- `docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md`
- `docs/productionize-refactor/handoffs/29-netbox-memory-rerun.md`

The branch already contained the required source changes and they were preserved throughout this run:

- `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml` with the bounded unified bootstrap path
- `terraform/lxc/stacks/netbox-stack/stack.yaml` with `memory: 4096`

No stash was applied. Scope was not broadened into Portainer or a full teardown/rebuild.

## Preflight And Before State

Confirmed production targeting:

- `./with-secrets-prod bash -lc 'echo $TF_VAR_proxmox_node'` returned `pve`

Captured before state from production `pve` for CT `40012`:

- config showed `memory = 1024`
- runtime status showed `maxmem = 1.00 GiB`
- runtime usage was `985.72 MiB`
- pressure remained severe:
  - `pressurecpusome = 96.71`
  - `pressurememoryfull = 92.49`
  - `pressurememorysome = 96.43`

Evidence:

- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/preflight-target.log`
- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/pve-netbox-config-before.json`
- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/pve-netbox-status-before.json`

## Targeted Plan And Apply

Executed targeted production plan:

- `TASK_APPROVAL=netbox-memory-rerun-20260524 ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/netbox-stack -no-color`

Plan result:

- exactly one in-place change
- `module.lxc.proxmox_virtual_environment_container.docker_host`
- `memory.dedicated = 1024 -> 4096`

Executed targeted production apply:

- `TASK_APPROVAL=netbox-memory-rerun-20260524 ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/netbox-stack -auto-approve -no-color`

Apply result:

- `Apply complete! Resources: 0 added, 1 changed, 0 destroyed.`
- output confirmed container `40012`, hostname `netbox-stack`, IP `192.168.40.12/24`, target node `pve`

Evidence:

- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/terragrunt-plan-netbox-stack.log`
- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/terragrunt-apply-netbox-stack.log`

## Did The Memory Change Apply?

Yes.

Post-apply production evidence showed:

- CT config `memory = 4096`
- CT runtime `maxmem = 4.00 GiB`
- memory pressure cleared to zero immediately after the change

Direct observations:

- immediate post-apply runtime status showed `mem = 783.63 MiB`
- `pressurememoryfull = 0.00`
- `pressurememorysome = 0.00`
- later final runtime status showed `mem = 1.02 GiB` while still under a `4.00 GiB` ceiling

Evidence:

- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/pve-netbox-config-after-apply.json`
- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/pve-netbox-status-after-apply.json`
- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/pve-netbox-status-final.json`

## Did The CT Need Restart?

No manual restart was needed.

The apply itself resulted in the container coming back with a fresh uptime. Immediately after apply, Proxmox reported uptime of `16s`, and the later final status showed uptime of `1m 12s`. That indicates the CT effectively restarted during the in-place update, so no separate explicit `pct restart 40012` step was required.

## Did SSH Responsiveness Improve?

Yes.

Before this run, the targeted NetBox provision rerun was blocked at gather-facts with SSH banner timeouts.

After the memory change:

- direct SSH to `root@192.168.40.12` succeeded
- Ansible gather-facts succeeded immediately
- the full targeted provision rerun completed with `unreachable=0` and `failed=0`

Notes:

- an initial direct SSH probe hit host key verification failure because the local known-hosts entry did not match the live host state
- a non-interactive probe with relaxed host-key handling succeeded and returned `SSH_OK`

Evidence:

- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/netbox-ssh-probe-after-apply.log`
- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/netbox-ssh-probe-after-apply-relaxed.log`
- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/provision-netbox-stack-rerun.log`

## Did The Patched Bootstrap Path Run?

Yes.

The targeted rerun reached and completed the bounded unified bootstrap path in `deploy-netbox-stack.yml`:

- `Wait for NetBox to be healthy` -> `ok`
- `Wait for NetBox bootstrap shell to respond` -> `ok`
- `Write NetBox bootstrap sync script` -> `changed`
- `Run NetBox bootstrap sync` -> `changed`
- `Display bootstrap status` -> `NetBox bootstrap: changed`

This confirms the rerun exercised the patched day-2/bootstrap path rather than failing earlier at host reachability.

## Does NetBox Provision Now Succeed?

Yes.

Executed:

- `TASK_APPROVAL=netbox-memory-rerun-20260524 ./with-secrets-prod ./scripts/provision.sh --stack netbox-stack`

Result:

- play recap reported `ok=27 changed=5 unreachable=0 failed=0 skipped=12`
- `[provision] Completed provision orchestration`

Evidence:

- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/provision-netbox-stack-rerun.log`

## Resulting Live State

Production NetBox is now in the following observed state:

- CT `40012` is `running`
- CT memory ceiling is `4.00 GiB`
- current CT usage captured at `1.02 GiB`
- memory pressure metrics are `0.00`
- direct SSH to the host responds
- NetBox application container reports `healthy`
- Docker shows the primary NetBox, worker, postgres, redis, and redis-cache containers up

Final container-health evidence also showed transient early health-check failures during startup before the service settled into `healthy`, which is consistent with a post-restart warm-up window rather than a final failure.

One container remains in its known expected pattern:

- `netbox-netbox-housekeeping-1` is `Restarting (0)`

That matches prior repository notes that the housekeeping container restarts by design for this NetBox deployment and is not, by itself, a blocker.

Evidence:

- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/pve-netbox-status-final.json`
- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/netbox-container-health-final.json`
- `docs/productionize-refactor/evidence/netbox-memory-rerun-20260524/logs/netbox-docker-ps-final.log`

## Remaining Blockers

No blocker remains for this narrowly scoped NetBox recovery task.

Items still worth carrying forward as operational notes, not blockers:

- the first strict direct SSH probe failed because of host-key verification, so future direct probes should account for current host-key state
- NetBox health checks can show transient startup failures during restart windows before stabilizing as `healthy`
- the housekeeping container still follows its expected restart pattern

## Conclusion

The combined source fixes were sufficient for targeted production convergence of `netbox-stack` on `pve`.

Specifically:

- the memory change applied cleanly on CT `40012`
- no separate manual CT restart was required
- SSH responsiveness improved enough for Ansible to recover
- the patched bootstrap path ran successfully
- `./with-secrets-prod ./scripts/provision.sh --stack netbox-stack` now succeeds
