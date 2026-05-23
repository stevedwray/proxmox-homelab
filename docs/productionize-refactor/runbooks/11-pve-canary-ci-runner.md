# Production Canary Runbook: ci-runner-01 on pve

**Target:** `ci-runner-01` on production Proxmox host `pve`
**Zone:** `build_seg` (VLAN 10, gateway from `${LAB_GW_BUILD}`)
**Difficulty:** Moderate
**Risk:** Moderate - runner availability affects CI execution, but the rollout keeps the existing workflow-compatible label set to avoid interrupting job routing

## Purpose

Prepare the next low-risk production migration after `netbox-stack`.
This run verifies that `ci-runner-01` can be deployed directly on `pve` using
the build-seg network, while preserving the stack contract for a self-hosted
GitHub Actions runner and the Docker cache/workload path.

This is not a speculative production mutation. Production apply and
provisioning require explicit operator approval in chat and `TASK_APPROVAL` at
execution time.

`./with-secrets-prod` uses a conservative allowlist. In this runbook, read-only
checks use only commands the wrapper actually permits (`pvesh get`,
`terragrunt plan`) or workstation-side commands that do not go through the
wrapper (`ssh`, `grep`, `rg`).

Use this runbook together with:

- `docs/productionize-refactor/runbooks/11-pve-canary-ci-runner-checklist.md`
- `docs/productionize-refactor/13-ci-runner-canary-execution-packet.md`

## Why ci-runner-01

1. `ci-runner-01` is the next production migration after `netbox-stack` in the current ordering.
2. It validates the runner path on `build_seg`, which is operationally important but less identity-sensitive than ingress or auth.
3. The service is a consumer of the platform, not a provider, so it is a good late-stage cutover target.
4. Its health checks are bounded: direct SSH, runner systemd service state, and GitHub registration status.

## Important Differences From The Earlier Canaries

Do **not** reuse the `monitoring-stack`, `step-ca-stack`, `netbox-stack`, or `portainer-stack` text as-is.

Stale assumptions that do not apply here:

1. This is not an ingress or data-tier service.
2. The primary health gate is the runner systemd service and GitHub registration, not an HTTP API.
3. The current deploy playbook now defaults the runner name to `ci-runner-01`; the runner labels stay on the existing workflow-compatible set so scheduled jobs continue to land on the runner.
4. The stack depends on Harbor and apt-cacher for provisioning, and on the production overlay for environment-driven addresses.

## Pre-Canary Checklist

**Do not proceed past any FAIL without operator intervention.**

### 1. Code State

- [ ] Work is being prepared from a short-lived branch (`work/*`, `feat/*`, `fix/*`, or `task/*`)
- [ ] The branch is not `baseline/teardown-validated`, `dev/pve-test`, or `main`
- [ ] No uncommitted changes in `terraform/` or `ansible/` are unrelated to this migration prep
- [ ] Task 07 migration ordering shows `ci-runner-01` as the next migration after `netbox-stack`

### 2. Repository Preconditions

- [ ] `terraform/lxc/stacks/ci-runner-01/stack.yaml` remains environment-decoupled and does not hardcode `pve-test`
- [ ] `terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md` still matches the intended deploy contract
- [ ] `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml` still behaves as a direct-access runner deployment
- [ ] The current deploy playbook defaults for `runner_name` and `runner_labels` are understood before cutover

**How to verify:**

```bash
grep -r 'pve-test' terraform/lxc/stacks/ci-runner-01/ terraform/lxc/ansible/playbooks/deploy-ci-runner.yml || echo 'PASS'
rg -n 'lab_ip_ci_runner|lab_gw_build|GITHUB_RUNNER_TOKEN|GITHUB_RUNNER_REPO|runner_name|runner_labels|deploy-ci-runner' terraform/lxc/stacks/ci-runner-01/stack.yaml terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md terraform/lxc/ansible/playbooks/deploy-ci-runner.yml
```

### 3. Target Validation And Duplicate-IP Guard

`ci-runner-01` uses the build-seg service IP defined by the production overlay.
If that remains shared with the active `pve-test` counterpart at execution time,
the `pve-test` counterpart must be destroyed before the `pve` cutover.

- [ ] `./with-secrets-prod` resolves `TF_VAR_proxmox_node=pve`
- [ ] Production `LAB_IP_CI_RUNNER` and `LAB_GW_BUILD` resolve to the intended `build_seg` values
- [ ] The operator has confirmed whether `LAB_IP_CI_RUNNER` is reused between `pve-test` and `pve`
- [ ] If the same IP is reused, the `pve-test` `ci-runner-01` counterpart is destroyed first

**How to verify targeting:**

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_CI_RUNNER=%s\nLAB_GW_BUILD=%s\n' "$LAB_IP_CI_RUNNER" "$LAB_GW_BUILD"
if command -v pvesh >/dev/null 2>&1; then
	./with-secrets-prod pvesh get /nodes/pve
else
	echo 'INFO: pvesh not installed on this workstation; rely on terragrunt plan target_node validation below.'
fi
```

**How to inspect and dispose the disposable `pve-test` counterpart:**

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack ci-runner-01 --plan
```

Run the destroy step only if the production runner IP is the same IP currently
in use on `pve-test`.

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack ci-runner-01 --execute
```

### 4. Network Preconditions

Network setup is out of scope for this runbook and must already be in place.
Production router state should be validated with the MikroTik preflight unless
an operator-approved skip is recorded for this exact migration window.

- [ ] The live `pve` uplink is trunked for VLANs `10`, `20`, `30`, and `40`
- [ ] `${LAB_GW_BUILD}` is assigned on `build_seg`
- [ ] `build_seg` input ACLs allow the runner to reach Harbor and apt-cacher for provisioning
- [ ] `${LAB_IP_CI_RUNNER}` has path to Harbor and apt-cacher service endpoints required by the runner provisioning path

**How to verify from the operator workstation:**

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

The preflight requires `MIKROTIK_PASSWORD` in the runtime environment. For
production canaries, ensure it is available via `terraform/secrets.pve.enc.yaml`
before running this step.

**Operator-approved skip path:**

If VLAN state was already validated and no network changes occurred, document
the skip decision and evidence path for this migration window, then continue.

Minimum skip note to capture in evidence/logs:

1. date/time of prior passing preflight evidence
2. evidence file path used as baseline
3. operator statement that VLAN and ACL state is unchanged

### 5. Runner Input Preconditions

`deploy-ci-runner.yml` has mandatory env requirements. Treat any missing
or empty value as a hard stop before apply/provision.

- [ ] `GITHUB_RUNNER_TOKEN` is non-empty
- [ ] `GITHUB_RUNNER_REPO` is non-empty
- [ ] `LAB_IP_HARBOR` is set to the intended Harbor endpoint
- [ ] `LAB_IP_APT_CACHER` is set to the intended apt-cacher endpoint if the runner inventory requires it

**How to verify:**

```bash
./with-secrets-prod bash -lc 'for v in GITHUB_RUNNER_TOKEN GITHUB_RUNNER_REPO LAB_IP_HARBOR LAB_IP_APT_CACHER; do if [ -n "${!v:-}" ]; then printf "PASS %s set\n" "$v"; else printf "FAIL %s missing\n" "$v"; fi; done'
```

### 6. Session Environment

- [ ] `.env` exists locally and contains non-secret defaults only
- [ ] `.env.pve` exists locally and contains the production overlay
- [ ] Production commands will be run through `./with-secrets-prod`
- [ ] There are no lingering manual `TF_VAR_*` exports overriding the wrapper

## Pre-Apply Validation

**Run these checks in order. Stop on any FAIL.**

### Preflight 1: Terragrunt Plan For ci-runner-01 On pve

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/ci-runner-01 -no-color
```

**Expected plan signals:**

1. `target_node = pve`
2. `hostname = ci-runner-01`
3. `ip_address = ${LAB_IP_CI_RUNNER}/24`
4. `gateway = ${LAB_GW_BUILD}`
5. `network.zone = build_seg`
6. `dns_server = ${LAB_GW_BUILD}`
7. `ansible_playbook = deploy-ci-runner`

**Red flags (stop if any appear):**

1. Any plan output still targets `pve-test`
2. Any plan output indicates the wrong runner identity or a non-`build_seg` zone
3. Any unexpected destroy or change outside `ci-runner-01`
4. Storage/template references do not match the production environment

### Preflight 1a: Production Router Preflight

Run the MikroTik preflight before any apply if the packet has not already
captured a passing result for this exact migration window.

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

**Stop if any fail appears for:**

1. `uplink bridge-port discovery`
2. any required `trunk vlan <id>` check
3. `build gateway`
4. `build icmp acl`
5. `build Harbor/apt-cacher reachability`

### Preflight 2: Evidence Directory Preparation

Create an evidence directory before any production mutation so all command
output for this migration window is captured in one place.

```bash
export EVIDENCE_DIR="docs/productionize-refactor/evidence/ci-runner-canary-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$EVIDENCE_DIR"
echo "$EVIDENCE_DIR"
```

Use `tee` while executing mutation-gated steps in the future migration session.
Example:

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/ci-runner-01 -no-color | tee "$EVIDENCE_DIR/01-plan.txt"
```

## Apply Phase

### Authorization Requirement

Production mutations require explicit operator approval in chat.

Before any apply or live provisioning step, the operator must confirm:

> I approve deploying ci-runner-01 to production pve as the next migration.

### Apply Command

```bash
export TASK_APPROVAL="canary-ci-runner-pve-$(date +%Y%m%d)"
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/ci-runner-01 -auto-approve -no-color
```

**Monitor for:**

1. apply exits successfully
2. no fallback or accidental reference to `pve-test`
3. generated inventory points to direct guest access for `ci-runner-01`

## Post-Apply Validation

### Runner Inventory Contract

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host|dns_server|contract_dns_server|ansible_playbook|vmid|stack_name|runner' terraform/lxc/stacks/ci-runner-01/inventory.yml
```

### Provisioning Checks

These two commands are approval-gated in practice because `./with-secrets-prod`
classifies `./scripts/provision.sh` as a production command. Run them only after
the operator has approved the migration, `TASK_APPROVAL` is exported, and the apply
step above has completed.

```bash
./with-secrets-prod ./scripts/provision.sh --stack ci-runner-01 --check
./with-secrets-prod ./scripts/provision.sh --stack ci-runner-01
```

### Health Evidence

```bash
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
| GitHub registration verified | ☐ | provision output reports online runner state |

### Counterpart Safety Recheck

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack ci-runner-01 --plan
```

| Check | Status | Expected |
|---|---|---|
| No lingering disposable counterpart | ☐ | Plan output shows no managed `pve-test` counterpart resources |

## Gate Decision

The ci-runner migration passes only if all of the following are true:

1. The `pve` target and intended `build_seg` IP/gateway were validated before apply.
2. The `pve-test` counterpart was destroyed first if the same service IP was being reused.
3. The plan and generated inventory showed direct-access behavior with no default ProxyJump.
4. Provisioning succeeded in both check mode and live mode.
5. The runner service is active and GitHub registration is verified.
6. No host-route priming workaround is required in the documented flow or observed provisioning path.
