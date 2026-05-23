# ci-runner-01 Canary Execution Packet (pve)

Use this as the short-form operator run script for the upcoming `ci-runner-01`
production migration on `pve`.

This packet is for future execution handoff only. Do not run mutation steps in a
documentation-prep session.

Detailed references:
- `docs/productionize-refactor/runbooks/11-pve-canary-ci-runner.md`
- `docs/productionize-refactor/runbooks/11-pve-canary-ci-runner-checklist.md`

## Open Decisions (Confirm Before Running)

1. **Confirmed:** the runner keeps the current workflow-compatible label set so existing jobs continue to schedule normally.
2. **Expected:** `ci-runner-01` remains in `build_seg` with `${LAB_GW_BUILD}` as gateway and DNS server.
3. **Expected:** the runner still depends on Harbor and apt-cacher for provisioning and job-cache behavior.

Do not start execution if `.env.pve` no longer sets the expected
`LAB_IP_CI_RUNNER`, `LAB_GW_BUILD`, `LAB_IP_HARBOR`, and `LAB_IP_APT_CACHER`
values for this packet.

## Objective

Validate `ci-runner-01` can be deployed and provisioned on production `pve`
using direct access (`ssh_access_mode: direct`), with the runner service active,
GitHub registration passing, and the build-seg path reachable from the host.

## Branch And Context Assumptions

1. Running from repo root: `/home/steve/git/proxmox-homelab`
2. Working branch is short-lived (`work/*`, `feat/*`, `fix/*`, or `task/*`), not `baseline/teardown-validated`, `dev/pve-test`, or `main`
3. `.env` and `.env.pve` are present locally
4. Production commands use `./with-secrets-prod`
5. No live production mutation is executed until explicit operator approval is given

## Pre-Run Decisions And Preconditions

1. Confirm the production MikroTik preflight passes for the live `pve` uplink, required VLAN tags, and current `build_seg` ACLs.
2. Confirm whether production is still reusing the active `pve-test` `ci-runner-01` service IP.
3. Confirm `.env.pve` still sets intended `LAB_IP_CI_RUNNER`, `LAB_GW_BUILD`, and `LAB_IP_HARBOR` values.
4. Confirm required inputs are non-empty in production runtime: `GITHUB_RUNNER_TOKEN`, `GITHUB_RUNNER_REPO`, `LAB_IP_HARBOR`, and `LAB_IP_APT_CACHER`.

If IP reuse is confirmed, counterpart disposal is mandatory before production
cutover.

## Execution Sequence (In Order)

Run from repo root.

### 1) Read-Only Target Validation

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_CI_RUNNER=%s\nLAB_GW_BUILD=%s\nLAB_IP_HARBOR=%s\n' "$LAB_IP_CI_RUNNER" "$LAB_GW_BUILD" "$LAB_IP_HARBOR"
if command -v pvesh >/dev/null 2>&1; then
	./with-secrets-prod pvesh get /nodes/pve
else
	echo 'INFO: pvesh not installed on this workstation; rely on step 5 terragrunt plan target_node validation.'
fi
```

### 2) Production Router Preflight

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

If this fails with a missing credential error, ensure `MIKROTIK_PASSWORD` is
present in `terraform/secrets.pve.enc.yaml`.

### 3) Required Input Variable Check (Read-Only)

```bash
./with-secrets-prod bash -lc 'for v in GITHUB_RUNNER_TOKEN GITHUB_RUNNER_REPO LAB_IP_HARBOR LAB_IP_APT_CACHER; do if [ -n "${!v:-}" ]; then printf "PASS %s set\n" "$v"; else printf "FAIL %s missing\n" "$v"; fi; done'
```

Stop if any line reports `FAIL`.

### 4) Counterpart Check (Always Plan)

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack ci-runner-01 --plan
```

### 5) Required Counterpart Destroy (`pve-test`)

Run this only when the service IP is being reused from `pve-test` to `pve`.

Approval point: operator approves counterpart teardown on `pve-test` before production cutover.

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack ci-runner-01 --execute
```

### 6) Read-Only Terraform Plan (Production Wrapper)

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/ci-runner-01 -no-color
```

Expected signals: `target_node = pve`, `network.zone = build_seg`, intended
IP/gateway, `ansible_playbook = deploy-ci-runner`, no unexpected destroy
outside `ci-runner-01`.
