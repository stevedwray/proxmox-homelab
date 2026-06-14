# pve Infra-Only Teardown Test Execution Packet

Date: 2026-05-24
Branch: work/productionize-06-canary-validation

This packet defines the controlled operator procedure for a real infra-only
teardown test on production `pve`.

This packet is execution guidance only. It is not an authorization to broaden
scope.

## 1) Purpose And Scope

Purpose:

- execute an infra-only destroy and redeploy test on `pve`
- destroy only the approved in-scope infra guests
- preserve all out-of-scope guests/VMs/CTs/storage on the shared host
- capture evidence sufficient for post-run review

Scope boundary:

- target node must be exactly `pve`
- scope is limited to the 10 stacks in Section 2
- no host/network/storage admin changes are authorized in this packet

Reference evidence (advisory, not authority):

- `docs/productionize-refactor/15-pve-infra-only-teardown-planner.md`
- `docs/productionize-refactor/16-pve-infra-teardown-advisory-summary.md`
- `docs/productionize-refactor/17-pve-infra-teardown-review-summary.md`
- `docs/productionize-refactor/pve-infra-teardown-inventory.md`
- `docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-173500/summary.md`

## 2) Exact In-Scope Stack List

Destroy/redeploy scope is exactly these stacks and VMIDs:

| Stack | VMID | IP |
|---|---:|---|
| `portainer-stack` | 20020 | `192.168.20.20` |
| `netbox-stack` | 40012 | `192.168.40.12` |
| `monitoring-stack` | 20012 | `192.168.20.12` |
| `harbor-stack` | 40010 | `192.168.40.10` |
| `authentik-stack` | 20010 | `192.168.20.10` |
| `proxy-stack` | 30010 | `192.168.30.10` |
| `step-ca-stack` | 20011 | `192.168.20.11` |
| `dns-stack` | 20013 | `192.168.20.13` |
| `ci-runner-01` | 10063 | `192.168.10.63` |
| `apt-cacher-stack` | 40011 | `192.168.40.11` |

No other stack or VMID is in scope for this packet.

## 3) Explicit Out-Of-Scope Protection Statement

Out-of-scope guests observed in the reviewed planner evidence must remain
untouched, including:

- VMID 100 `torrent-stack`
- VMID 101 `management-stack`
- VMID 102 `media-stack`
- VMID 103 `gaming-stack`
- VMID 104 `cloud-stack`
- VMID 105 `proxmox-backup-server`
- VMID 106 `securityonion`
- VMID 107 `wazuh`
- VMID 108 `securityonion-idh`
- VMID 109 `security-stack`
- VMID 110 `analysis-stack`
- VMID 111 `wifi-analysis`
- VMID 112 `elastic-stack`
- VMID 113 `pve-test`
- VMID 114 `omada-controller`
- VMID 115 `scanning-stack`
- VMID 116 `ai-stack`
- VMID 120 `metasploitable`
- VMID 131 `test-docker`
- VMID 910 `debian13-template-builder`

Protection rule:

- if any command output indicates action against an out-of-scope VMID/guest,
  stop immediately and execute Section 11

## 4) Preconditions

All must be true before any destroy command:

1. Human approval is granted for this infra-only teardown test on `pve`.
2. Operator understands this is a shared host and out-of-scope workloads must
	remain untouched.
3. Current branch is `work/productionize-06-canary-validation`.
4. Production wrapper is used for all production commands: `./with-secrets-prod`.
5. `terraform/secrets.pve.enc.yaml` and age key are available locally.
6. `gh auth status` is healthy (required because `ci-runner-01` is in scope).
7. Operator sets a single approval token for this run window:
	`export TASK_APPROVAL="pve-infra-teardown-test-$(date +%Y%m%d)"`.
8. Operator has a fresh, writable evidence directory for this run.

## 5) Preflight Commands

Run from repo root.

### 5.1 Initialize run evidence location

```bash
set -euo pipefail
export PACKET_STAMP="$(date -u +%Y%m%d-%H%M%S)"
export EVIDENCE_DIR="docs/productionize-refactor/evidence/pve-infra-teardown-exec-${PACKET_STAMP}"
mkdir -p "${EVIDENCE_DIR}" "${EVIDENCE_DIR}/logs"

run_logged() {
  local logfile="$1"
  shift
  "$@" | tee "${logfile}"
}

capture_pve_read_only() {
  local logfile="$1"
  shift
  local command_name="$1"
  shift

  if command -v "${command_name}" >/dev/null 2>&1; then
    run_logged "${logfile}" ./with-secrets-prod "${command_name}" "$@"
    return 0
  fi

  local ssh_target="${PVE_INFRA_SSH_TARGET:-root@${PROXMOX_HOST:-pve.gibbsgreatly.xyz}}"
  local remote_cmd=""

  remote_cmd="$(printf '%q ' "${command_name}" "$@")"
  remote_cmd="${remote_cmd% }"

  run_logged "${logfile}" \
    ssh -F /dev/null \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=accept-new \
    "${ssh_target}" "${remote_cmd}"
}
```

### 5.2 Validate target context and auth

```bash
set -a
source .env
source .env.pve
set +a

./with-secrets-prod bash -c 'echo "TF_VAR_proxmox_node=$TF_VAR_proxmox_node"' | tee "${EVIDENCE_DIR}/logs/target-node.txt"
run_logged "${EVIDENCE_DIR}/logs/gh-auth-status.txt" gh auth status
```

Expected: `TF_VAR_proxmox_node=pve` and healthy GitHub CLI auth.

### 5.3 Refresh advisory planning evidence for this execution window

```bash
./scripts/plan-pve-infra-teardown.sh source-preflight --stamp "${PACKET_STAMP}"
./scripts/plan-pve-infra-teardown.sh platform-status --stamp "${PACKET_STAMP}"
./scripts/plan-pve-infra-teardown.sh plan --stamp "${PACKET_STAMP}"
./scripts/plan-pve-infra-teardown.sh summary --stamp "${PACKET_STAMP}"
```

### 5.4 Mandatory human log review before destroy

Review and confirm all are true:

1. No blocker appears in `plan-destroy-*.log`.
2. No plan mentions `pve-test`.
3. No out-of-scope VMID appears in any plan.
4. Out-of-scope guest list is explicit and unchanged in intent.
5. Storage output (`pvesm status`) shows no unintended shared-storage action
	implication.

Record sign-off note:

```bash
printf 'Reviewed advisory logs for stamp %s; scope remains infra-only and out-of-scope guests remain protected.\n' "${PACKET_STAMP}" > "${EVIDENCE_DIR}/logs/pre-destroy-human-review.txt"
```

## 6) Stop Conditions

Stop immediately if any occur:

1. `TF_VAR_proxmox_node` resolves to anything except `pve`.
2. `gh auth status` fails while `ci-runner-01` remains in scope.
3. Planner output shows `BLOCKER` for any stack.
4. Any destroy/apply/provision output references out-of-scope VMIDs/guests.
5. Any command indicates shared storage action outside in-scope stack ownership.
6. Any stack command fails unexpectedly or partially applies.
7. Operator cannot confidently determine scope safety from command output.

No compensating command is authorized while stop conditions are unresolved.

## 7) Destroy Sequence

Approval-gated phase. Do not begin unless Sections 4-6 are satisfied.

```bash
export TASK_APPROVAL="pve-infra-teardown-test-$(date +%Y%m%d)"
```

Execute destroy in exact order:

```bash
run_logged "${EVIDENCE_DIR}/logs/destroy-portainer-stack.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/portainer-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/destroy-netbox-stack.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/netbox-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/destroy-monitoring-stack.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/monitoring-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/destroy-harbor-stack.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/harbor-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/destroy-authentik-stack.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/authentik-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/destroy-proxy-stack.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/proxy-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/destroy-step-ca-stack.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/step-ca-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/destroy-dns-stack.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/dns-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/destroy-ci-runner-01.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/ci-runner-01 -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/destroy-apt-cacher-stack.log" ./with-secrets-prod terragrunt destroy --working-dir terraform/lxc/stacks/apt-cacher-stack -auto-approve -no-color
```

After the destroy phase, capture host state:

```bash
capture_pve_read_only "${EVIDENCE_DIR}/logs/post-destroy-pct-list.log" pct list
capture_pve_read_only "${EVIDENCE_DIR}/logs/post-destroy-qm-list.log" qm list
capture_pve_read_only "${EVIDENCE_DIR}/logs/post-destroy-pvesm-status.log" pvesm status
```

## 8) Redeploy Sequence

Redeploy in exact order (reverse of destroy dependency direction):

```bash
export TASK_APPROVAL="pve-infra-teardown-test-$(date +%Y%m%d)"

run_logged "${EVIDENCE_DIR}/logs/apply-apt-cacher-stack.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/apt-cacher-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-apt-cacher-stack.log" ./with-secrets-prod ./scripts/provision.sh --stack apt-cacher-stack

run_logged "${EVIDENCE_DIR}/logs/apply-ci-runner-01.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/ci-runner-01 -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-ci-runner-01.log" ./with-secrets-prod ./scripts/provision.sh --stack ci-runner-01

run_logged "${EVIDENCE_DIR}/logs/apply-dns-stack.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/dns-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-dns-stack.log" ./with-secrets-prod ./scripts/provision.sh --stack dns-stack

run_logged "${EVIDENCE_DIR}/logs/apply-step-ca-stack.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/step-ca-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-step-ca-stack.log" ./with-secrets-prod ./scripts/provision.sh --stack step-ca-stack

run_logged "${EVIDENCE_DIR}/logs/apply-proxy-stack.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/proxy-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-proxy-stack.log" ./with-secrets-prod ./scripts/provision.sh --stack proxy-stack

run_logged "${EVIDENCE_DIR}/logs/apply-authentik-stack.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/authentik-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-authentik-stack.log" ./with-secrets-prod ./scripts/provision.sh --stack authentik-stack

run_logged "${EVIDENCE_DIR}/logs/apply-harbor-stack.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/harbor-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-harbor-stack.log" ./with-secrets-prod ./scripts/provision.sh --stack harbor-stack

run_logged "${EVIDENCE_DIR}/logs/apply-monitoring-stack.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/monitoring-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-monitoring-stack.log" ./with-secrets-prod ./scripts/provision.sh --stack monitoring-stack

run_logged "${EVIDENCE_DIR}/logs/apply-netbox-stack.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/netbox-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-netbox-stack.log" ./with-secrets-prod ./scripts/provision.sh --stack netbox-stack

run_logged "${EVIDENCE_DIR}/logs/apply-portainer-stack.log" ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/portainer-stack -auto-approve -no-color
run_logged "${EVIDENCE_DIR}/logs/provision-portainer-stack.log" ./with-secrets-prod ./scripts/provision.sh --stack portainer-stack
```

## 9) Validation Sequence After Redeploy

Run read-only validation in this order:

```bash
capture_pve_read_only "${EVIDENCE_DIR}/logs/post-redeploy-pct-list.log" pct list
capture_pve_read_only "${EVIDENCE_DIR}/logs/post-redeploy-qm-list.log" qm list
capture_pve_read_only "${EVIDENCE_DIR}/logs/post-redeploy-pvesm-status.log" pvesm status
```

```bash
run_logged "${EVIDENCE_DIR}/logs/post-plan-apt-cacher-stack.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/apt-cacher-stack -no-color
run_logged "${EVIDENCE_DIR}/logs/post-plan-ci-runner-01.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/ci-runner-01 -no-color
run_logged "${EVIDENCE_DIR}/logs/post-plan-dns-stack.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/dns-stack -no-color
run_logged "${EVIDENCE_DIR}/logs/post-plan-step-ca-stack.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/step-ca-stack -no-color
run_logged "${EVIDENCE_DIR}/logs/post-plan-proxy-stack.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/proxy-stack -no-color
run_logged "${EVIDENCE_DIR}/logs/post-plan-authentik-stack.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/authentik-stack -no-color
run_logged "${EVIDENCE_DIR}/logs/post-plan-harbor-stack.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/harbor-stack -no-color
run_logged "${EVIDENCE_DIR}/logs/post-plan-monitoring-stack.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/monitoring-stack -no-color
run_logged "${EVIDENCE_DIR}/logs/post-plan-netbox-stack.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/netbox-stack -no-color
run_logged "${EVIDENCE_DIR}/logs/post-plan-portainer-stack.log" ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/portainer-stack -no-color
```

Expected validation outcomes:

1. In-scope VMIDs return to expected presence.
2. Out-of-scope guests remain present/unchanged from preflight intent.
3. Post-redeploy plans show no unexpected drift.
4. No command output suggests mutation outside in-scope stacks.

## 10) Evidence Capture Expectations

Minimum evidence set:

1. Target and auth preflight logs (`target-node`, `gh-auth-status`).
2. Full advisory planner phase outputs for run stamp.
3. Human review sign-off note for pre-destroy logs.
4. Per-stack destroy logs.
5. Post-destroy `pct`/`qm`/`pvesm` snapshots.
6. Per-stack apply and provision logs.
7. Post-redeploy `pct`/`qm`/`pvesm` snapshots.
8. Per-stack post-redeploy terragrunt plan logs.
9. Short operator summary note describing whether any stop condition was hit.

Suggested final summary capture:

```bash
cat > "${EVIDENCE_DIR}/operator-summary.txt" <<EOF
Run stamp: ${PACKET_STAMP}
Scope followed: yes/no
Out-of-scope guests preserved: yes/no
Stop conditions encountered: none/list
Operator notes:
EOF
```

## 11) Abort And Recovery Guidance (Scope Deviation)

If deviation from approved scope is observed:

1. Stop running further mutate commands immediately.
2. Capture immediate host state (`pct list`, `qm list`, `pvesm status`) to new
	timestamped files under `${EVIDENCE_DIR}/logs/`.
3. Record the exact command that triggered deviation and timestamp.
4. Do not improvise unrelated corrective mutation.
5. Escalate to operator decision with evidence attached.

Use the same `capture_pve_read_only` helper from Section 5.1 for those
immediate host-state captures.

If a stack destroy/apply fails but no out-of-scope action is observed:

1. Pause sequence.
2. Collect stack-specific logs and post-failure host status.
3. Resume only after operator confirms whether to retry, continue, or roll
	forward by redeploying affected in-scope stacks.

## 12) What This Packet Does NOT Authorize

This packet does not authorize:

1. Any mutation outside the 10 in-scope stacks/VMIDs in Section 2.
2. Any change to out-of-scope guests, VMs, containers, storage pools,
	templates, backups, snapshots, or host/network configuration.
3. Any use of `scripts/teardown-deploy-test.sh` for production `pve` mutation
	without explicit production target inputs and wrapper selection
	(for example `TEARDOWN_TARGET_NODE_EXPECTED=pve`,
	`TEARDOWN_PVE_HOST=pve.gibbsgreatly.xyz`, and `TEARDOWN_WITH_SECRETS=./with-secrets-prod`).
4. Treating advisory planner output as automatic go/no-go authority.
5. Silent scope expansion due to convenience, partial failure, or ambiguous
	logs.

When ambiguity appears, stop and request explicit human judgment.
