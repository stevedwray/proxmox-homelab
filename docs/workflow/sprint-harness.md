# Sprint: Provisioning Harness Improvements

**Scope:** Four improvements to `scripts/provision.sh` and per-stack smoke tests
for all platform-tier stacks. No changes to stack Terraform or Ansible.

**Promotion target:** `stable` only. These changes do not go to `main` until the
legacy app integration sprint, when the harness and smoke tests are needed against pve.

**Branch:** `work/sprint-harness` — cut from `fix/monitoring-proxmox-host-target`
once that fix is merged. Both sessions (H-1, H-2) land here directly. Delete
after merge to `stable`. Sub-branches only if a session needs isolated review.

**Sequencing:** H-1 (script changes) can be done without live infra and must
complete first. H-2 (smoke test scripts) requires a running pve-test-vm platform tier.

**Branch model reference:** [docs/workflow/branch-model.md](branch-model.md)

---

## Dependency placement — platform stacks

Stack placement must be derived from each stack's function and declared
requirements, not from a hand-maintained diagram. `depends_on` in `stack.yaml`
is the source of truth for execution order. The harness should compute layers
from that metadata every run and then execute only stacks with no dependency
relationship in parallel.

Functional placement rules:

- Foundation services with no runtime dependency on another platform stack may
  start in the first layer.
- Services that consume package caching, registry images, DNS, PKI, identity, or
  edge routing must declare those requirements explicitly in `depends_on`.
- Smoke tests should run immediately after the stack they validate, before any
  dependent stack starts.
- The static graph below is illustrative only; update it only after checking the
  current `stack.yaml` metadata.

```
Layer 0 (no deps):  dns-stack, apt-cacher-stack
Layer 1:            step-ca-stack, harbor-stack
Layer 2:            proxy-stack, netbox-stack, authentik-stack, portainer-stack, ci-runner-01
Layer 3:            monitoring-stack
```

---

## Session H-1 — `provision.sh` enhancements

**Branch:** `work/sprint-harness`
**Live infra required:** No
**Promotion gate:** `ansible-playbook --syntax-check` on all platform playbooks passes;
`./scripts/provision.sh --help` shows updated usage; `--check` dry run against
pve-test-vm completes without error

### Tasks

**H-1a — Failure and skip reporting**

When a stack fails, `provision.sh` currently exits immediately. Add downstream
impact reporting before exiting:

```
[provision] ERROR: Stack 'harbor-stack' failed (exit 1)
[provision] Skipping downstream stacks (depend on harbor-stack): authentik-stack, netbox-stack, monitoring-stack, proxy-stack, ci-runner-01
```

Implementation: after the topo-sort, build a reverse-dependency map. On failure,
walk the map to collect all transitively blocked stacks and print them.

**H-1b — Environment-scoped invocation**

Make the target environment visible in logs and fail fast when the requested
environment does not match the wrapper-injected environment.

Important constraint: environment and secrets selection happens in
`with-secrets` / `with-secrets-prod` before `scripts/provision.sh` starts. A
positional argument inside `provision.sh` cannot safely choose the env file or
secrets file after the fact.

Preferred invocation pattern:

```
PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --tier platform
./with-secrets-prod scripts/provision.sh --stack monitoring-stack
```

Behaviour:
- Add an optional `--target-env <pve-test-vm|pve>` guard if useful, but use it
  only to assert that `PVE_ENV` and `TF_VAR_proxmox_node` already match.
- Do not source env files directly inside `provision.sh`; secrets still flow
  through `with-secrets`/`with-secrets-prod`.
- Emit `[provision] target: pve-test-vm` or `[provision] target: pve` at startup so
  the target is always visible in logs.
- If the requested target and injected environment disagree, abort before any
  Ansible, Terraform, or reconciler action.

**H-1c — Parallel execution**

After the topological sort produces a sequenced list, group stacks by dependency
depth derived from current `stack.yaml` metadata (stacks in the same layer have
no dependency relationship between them).
Run each layer as a parallel batch using background jobs + `wait`:

```bash
for layer in "${layers[@]}"; do
  pids=()
  for stack in $layer; do
    provision_stack "$stack" 2>&1 | sed "s/^/[$stack] /" &
    pids+=($!)
  done
  for pid in "${pids[@]}"; do
    wait "$pid" || failed=true
  done
  [[ "$failed" == true ]] && report_skipped_downstream && exit 1
done
```

Log lines must be prefixed with the stack name so parallel output is readable.
Collect all failures within a layer before exiting (do not short-circuit mid-layer).

**H-1d — Smoke test runner**

After the Ansible step succeeds for a stack, check for `smoke-test.sh` in the
stack directory. If present, run it with a 60-second timeout:

```bash
smoke_script="${STACKS_DIR}/${stack}/smoke-test.sh"
if [[ -x "$smoke_script" ]]; then
  log "Running smoke test for ${stack}"
  if ! REPO_ROOT="$REPO_ROOT" timeout 60 "$smoke_script"; then
    fail "Smoke test failed for ${stack}"
  fi
  log "Smoke test passed: ${stack}"
fi
```

No smoke test present = pass (additive, backward compatible with all existing stacks).
Failure is treated the same as Ansible failure: downstream stacks are reported and
skipped.

### Handoff state

- `--help` output shows target guard and parallel notes
- `[provision] target: <env>` appears in all run logs
- Skip reporting tested by killing a stack mid-run and verifying downstream list
- Parallel batch logic verified with `--check` against pve-test-vm (no live Terraform needed)
- Smoke test runner integrated but no smoke test scripts exist yet (that is H-2)

---

## Session H-2 — Per-stack smoke tests

**Branch:** `work/sprint-harness` (continued)
**Live infra required:** Yes — full platform tier must be running on pve-test-vm
**Promotion gate:** `PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --tier platform`
completes with all platform smoke tests green; no regression in any stack

### Conventions

Each `smoke-test.sh`:
- Is executable (`chmod +x`)
- Exits 0 on pass, non-zero on failure
- Reads env vars injected by `provision.sh` (inherited from `with-secrets`)
- Can rely on `REPO_ROOT` because the harness exports it before invoking tests
- Completes in under 60 seconds
- Prints a one-line pass/fail summary to stdout

Use `curl -sf` (silent + fail-on-HTTP-error) for HTTP checks. Use `--cacert
certs/homelab-root.crt` where internal TLS is required.

### H-2a — `step-ca-stack/smoke-test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
step ca health \
  --ca-url "https://${LAB_IP_STEP_CA}" \
  --root "${REPO_ROOT}/certs/homelab-root.crt"
echo "step-ca: healthy"
```

Dependency: `step` CLI must be on the control node (installed via `setup-dev-env.sh`).
Fallback if `step` is absent: `curl -sf --cacert certs/homelab-root.crt "https://${LAB_IP_STEP_CA}/health"`.

### H-2b — `dns-stack/smoke-test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
result=$(dig @"${LAB_IP_DNS}" "step-ca.${LAB_DOMAIN}" +short)
[[ -n "$result" ]] || { echo "dns: no answer for step-ca.${LAB_DOMAIN}"; exit 1; }
echo "dns: resolved step-ca.${LAB_DOMAIN} → ${result}"
```

### H-2c — `harbor-stack/smoke-test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -sf --cacert "${REPO_ROOT}/certs/homelab-root.crt" \
  "https://${LAB_FQDN_HARBOR}/api/v2.0/health" \
  | grep -q '"status":"healthy"'
echo "harbor: healthy"
```

`LAB_FQDN_HARBOR` is constructed as `harbor.${LAB_DOMAIN}` if not set explicitly.

### H-2d — `apt-cacher-stack/smoke-test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -sf "http://${LAB_IP_APT_CACHER}:3142/acng-report.html" > /dev/null
echo "apt-cacher: reachable"
```

### H-2e — `netbox-stack/smoke-test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -sf "http://${LAB_IP_NETBOX}:8080/api/" > /dev/null
echo "netbox: API responding"
```

### H-2f — `portainer-stack/smoke-test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -sf "http://${LAB_IP_PORTAINER}:9000/api/system/status" > /dev/null
echo "portainer: API responding"
```

### H-2g — `authentik-stack/smoke-test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -sf --cacert "${REPO_ROOT}/certs/homelab-root.crt" \
  "https://${LAB_FQDN_AUTHENTIK}/api/v3/root/config/" > /dev/null
echo "authentik: API responding"
```

`LAB_FQDN_AUTHENTIK` = `authentik.${LAB_DOMAIN}`.

### H-2h — `monitoring-stack/smoke-test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
# All node_exporter targets must be in state "up"
down=$(curl -sf "http://${LAB_IP_MONITORING}:8428/api/v1/targets" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
down = [t['labels'].get('instance','?') for t in data.get('data',{}).get('activeTargets',[]) if t['health'] != 'up']
print('\n'.join(down))
")
if [[ -n "$down" ]]; then
  echo "monitoring: targets down:"; echo "$down"; exit 1
fi
echo "monitoring: all targets up"
```

### H-2i — `proxy-stack/smoke-test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -sf "http://${LAB_IP_PROXY}:8080/ping" > /dev/null
echo "proxy: Traefik ping ok"
```

### H-2j — `ci-runner-01` (connectivity only)

ci-runner-01 has no HTTP health endpoint. Use SSH connectivity as the check:

```bash
#!/usr/bin/env bash
set -euo pipefail
ssh -o BatchMode=yes -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=no \
  "root@${LAB_IP_CI_RUNNER}" true
echo "ci-runner-01: SSH reachable"
```

### Handoff state

- All platform `smoke-test.sh` scripts present and executable
- Full `--tier platform` run on pve-test-vm completes with all smoke tests green
- Verified: killing Ansible mid-run still triggers skip reporting and halts
  downstream smoke tests
- Branch merged to `stable`; no pve deploy needed (harness-only change)

---

## Validation tiers

| Session | Change class | Minimum validation |
|---|---|---|
| H-1 | Ansible-agnostic script change | `--syntax-check` on platform playbooks; `--check` dry run on pve-test-vm |
| H-2 | New `smoke-test.sh` scripts (no Ansible/TF changes) | Full `--tier platform` live run on pve-test-vm |

Syntax-check command:
```bash
find terraform/lxc/ansible/playbooks -name "deploy-*-stack.yml" | \
  xargs -I{} ansible-playbook --syntax-check {}
```

---

## Relationship to environment isolation sprint

Once H-2 is merged, the smoke tests serve as the automated validation gate
for [sprint-env-isolation.md](sprint-env-isolation.md) session E-2: a full
rebuild on pve-test-vm with the new IP scheme passes when all platform smoke
tests are green.

---

## Promotion scan handling

Because H-1 changes shell code and H-2 adds shell/YAML-adjacent validation
assets, run `./with-secrets /home/steve/.local/bin/sonar-scanner` before
promotion. If the scan reports new findings, create GitHub issues for actionable
findings, attach the scan evidence, and do not promote until blocking findings
are fixed or explicitly accepted by the operator.
