# Production Canary Execution Checklist: ci-runner-01 on pve

**Task:** Deploy `ci-runner-01` to `pve` as the next production migration for `build_seg`
**Target:** `pve` (production)
**Canary:** `ci-runner-01`, `build_seg`, VMID `10063`
**Date:** [fill at execution time]

This checklist is runner-specific on purpose. Do **not** reuse the earlier
`monitoring-stack`, `step-ca-stack`, or `netbox-stack` checklist text as-is for
this migration. In particular, replace the mgmt/infra service-health checks with
runner registration and systemd service checks.

The runner retains the existing workflow-compatible label set during this rollout so GitHub job routing does not change.

Read-only wrapper usage must stay inside the actual `with-secrets-prod`
allowlist. Use `pvesh get` and `terragrunt plan` through the wrapper, and use
workstation-side `ssh`, `rg`, and `grep` for direct guest validation.

---

## Phase 1: Target Validation, Router Preflight, And Counterpart Disposal

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_CI_RUNNER=%s\nLAB_GW_BUILD=%s\n' "$LAB_IP_CI_RUNNER" "$LAB_GW_BUILD"
if command -v pvesh >/dev/null 2>&1; then
	./with-secrets-prod pvesh get /nodes/pve
else
	echo 'INFO: pvesh not installed on this workstation; rely on terragrunt plan target_node validation in Phase 2.'
fi
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack ci-runner-01 --plan
```

If operator confirms VLAN setup is already validated and unchanged for this
window, you may skip rerunning the MikroTik preflight. In that case, record:

1. prior passing evidence file path
2. date/time of that evidence
3. operator unchanged-network attestation

| Check | Status | Expected |
|---|---|---|
| Wrapper target | ☐ | `.env.pve` values align with `pve`; `./with-secrets-prod pvesh get /nodes/pve` succeeds |
| MikroTik production preflight (or approved skip) | ☐ | `Verdict: PASS` output OR documented skip with prior evidence + unchanged-network attestation |
| Production ci-runner IP resolved | ☐ | Intended `${LAB_IP_CI_RUNNER}` for `build_seg` |
| Production gateway resolved | ☐ | Intended `${LAB_GW_BUILD}` |
| Runner registration path and required inputs present | ☐ | `gh auth status` is healthy; `LAB_IP_HARBOR` (and `LAB_IP_APT_CACHER` if needed) are non-empty |
| `pve-test` counterpart disposed first when IP reused | ☐ | Counterpart absent before cutover |

Run the destroy step only if the production runner IP is the same IP currently
in use on `pve-test`:

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack ci-runner-01 --execute
```

Runner registration and input quick check:

```bash
gh auth status
./with-secrets-prod bash -lc 'for v in LAB_IP_HARBOR LAB_IP_APT_CACHER; do if [ -n "${!v:-}" ]; then printf "PASS %s set\n" "$v"; else printf "FAIL %s missing\n" "$v"; fi; done'
```

---

## Phase 2: Terraform Plan Expectations

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/ci-runner-01 -no-color
```

| Check | Status | Expected |
|---|---|---|
| Plan exits successfully | ☐ | Exit code `0` |
| Plan targets production | ☐ | `target_node = pve` |
| Plan uses `build_seg` | ☐ | `network.zone = build_seg` |
| IP and gateway match intended values | ☐ | `${LAB_IP_CI_RUNNER}/24`, `${LAB_GW_BUILD}` |
| Playbook identity is correct | ☐ | `ansible_playbook = deploy-ci-runner` |
| Runner labels preserved | ☐ | `RUNNER_LABELS` remains the existing workflow-compatible set |
| No unrelated stack actions | ☐ | Only `ci-runner-01` changes or refresh |

**Stop if:** the plan references `pve-test`, a non-`build_seg` zone, or an unexpected destroy.

---

## Phase 3: Evidence Directory Setup (Before Apply)

```bash
export EVIDENCE_DIR="docs/productionize-refactor/evidence/ci-runner-canary-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$EVIDENCE_DIR"
echo "$EVIDENCE_DIR"
```

| Check | Status | Expected |
|---|---|---|
| Evidence directory exists | ☐ | `$EVIDENCE_DIR` path printed and created |
| Plan output captured | ☐ | Plan command output saved under `$EVIDENCE_DIR` |

Suggested capture form:

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/ci-runner-01 -no-color | tee "$EVIDENCE_DIR/01-plan.txt"
```

---

## Phase 4: Apply

These commands are production mutations. Run them only after operator approval
and after exporting `TASK_APPROVAL` in the current shell.

```bash
export TASK_APPROVAL="canary-ci-runner-pve-$(date +%Y%m%d)"
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/ci-runner-01 -auto-approve -no-color
```

| Check | Status | Expected |
|---|---|---|
| Apply completed | ☐ | Exit code `0` |
| Target remained `pve` | ☐ | No `pve-test` targeting in output |
| `build_seg` addressing applied | ☐ | Intended `${LAB_IP_CI_RUNNER}/24`, `${LAB_GW_BUILD}` |
| Stack inventory rendered | ☐ | `terraform/lxc/stacks/ci-runner-01/inventory.yml` present |

---

## Phase 5: Post-Apply Inventory Expectations

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host|dns_server|contract_dns_server|ansible_playbook|vmid|stack_name|runner' terraform/lxc/stacks/ci-runner-01/inventory.yml
rg -n 'ci-runner-01|ansible_host|ssh_access_mode|ProxyJump|dns_server|contract_dns_server|ansible_playbook' terraform/lxc/.generated/inventory.pve.yml || true
```

| Check | Status | Expected |
|---|---|---|
| Stack inventory exists | ☐ | `terraform/lxc/stacks/ci-runner-01/inventory.yml` present |
| Direct host path | ☐ | `ansible_host` is the guest IP |
| SSH mode | ☐ | `ssh_access_mode: direct` |
| ProxyJump removed | ☐ | No `ProxyJump` and no `pve_host` fallback |
| Playbook identity | ☐ | `ansible_playbook: deploy-ci-runner` |
| VMID | ☐ | `vmid: 10063` |

---

## Phase 6: Provisioning Checks

These two commands are approval-gated in practice because `./with-secrets-prod`
classifies `./scripts/provision.sh` as a production command. Run them only after
the operator has approved the migration, `TASK_APPROVAL` is exported, and the apply
step above has completed.

```bash
./with-secrets-prod ./scripts/provision.sh --stack ci-runner-01 --check
./with-secrets-prod ./scripts/provision.sh --stack ci-runner-01
```

| Check | Status | Expected |
|---|---|---|
| Check mode clean | ☐ | `unreachable=0 failed=0` |
| Live provisioning clean | ☐ | `unreachable=0 failed=0` |
| Runner registration verified | ☐ | GitHub API reports runner online |
| No default ProxyJump used during provisioning | ☐ | Direct inventory path only |
| No host-route priming dependency remains | ☐ | Direct inventory path only; no default ProxyJump |

Evidence command for the last check:

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host' terraform/lxc/stacks/ci-runner-01/inventory.yml
```

---

## Phase 7: Post-Apply Health Evidence

```bash
if command -v pct >/dev/null 2>&1; then
	./with-secrets-prod pct list | grep -E '(ci-runner-01|10063)'
else
	echo 'INFO: pct not installed on this workstation; skipping local pct list check.'
fi
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_CI_RUNNER" "ip -4 addr show dev eth0 && echo '---' && ip route show default && echo '---' && ping -c 1 '$LAB_GW_BUILD'"
ssh -G root@"$LAB_IP_CI_RUNNER" | rg '^proxyjump ' || echo 'proxyjump=none'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_CI_RUNNER" 'systemctl status actions.runner.*.service --no-pager'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_CI_RUNNER" 'systemctl is-active actions.runner.*.service'
```

| Check | Status | Expected |
|---|---|---|
| Intended IP assigned | ☐ | `${LAB_IP_CI_RUNNER}/24` on `eth0` |
| Intended gateway assigned | ☐ | default via `${LAB_GW_BUILD}` |
| Gateway reachable | ☐ | ping success |
| Direct SSH works | ☐ | guest IP reachable, `proxyjump=none` |
| Runner service present | ☐ | `actions.runner.*.service` exists |
| Runner service active | ☐ | service is `active` |
| GitHub registration verified | ☐ | runner online |

---

## Phase 8: Counterpart Safety Recheck

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack ci-runner-01 --plan
```

| Check | Status | Expected |
|---|---|---|
| No lingering disposable counterpart | ☐ | Plan output shows no managed `pve-test` counterpart resources |

---

## Gate Decision

The ci-runner migration passes only if all of the following are true:

1. The `pve` target and intended `build_seg` IP/gateway were validated before apply.
2. The `pve-test` counterpart was destroyed first if the same service IP was being reused.
3. The plan and generated inventory showed direct-access behavior with no default ProxyJump.
4. Provisioning succeeded in both check mode and live mode.
5. The runner service is active and GitHub registration is verified.
6. No host-route priming workaround is required in the documented flow or observed provisioning path.
