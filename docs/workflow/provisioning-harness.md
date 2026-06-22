# Provisioning Harness

## Current State

`scripts/provision.sh` is the main orchestration entry point. It:

- Reads `stack.yaml` from each stack directory to discover stacks and their
  `deployment_tier` (`platform` or `apps`) and `depends_on` relationships
- Topologically sorts stacks respecting dependencies
- Runs `ansible-playbook` configuration for each selected stack in order
- Supports `--stack <name>` (one or more specific stacks) and `--tier <platform|apps|all>`
- Supports `--check` to run Ansible in check mode
- Handles stack-specific pre-flight logic (e.g., Portainer OAuth secret bootstrap)

Environment selection is controlled externally: `./with-secrets` sets the
pve-test context; `./with-secrets-prod` sets the pve context. The script itself
is environment-agnostic.

Terraform/Terragrunt creation and destruction are separate workflows today. A
full rebuild gate must explicitly run Terraform/Terragrunt destroy/apply before
calling `scripts/provision.sh`; calling `provision.sh` alone after destroy will
not recreate LXCs.

### What the harness does not yet do

- **Post-provision smoke tests**: no health checks run after each stack deploy.
  Pass/fail is determined purely by Ansible/Terraform exit codes.
- **Parallel execution**: stacks are provisioned serially, even when their
  dependencies would allow parallelism.
- **Stack-level test assertions**: there is no standard way for a stack to declare
  what "healthy" means and have the harness verify it.
- **Selective re-run on partial failure**: if a stack mid-sequence fails, the
  operator must re-run manually with `--stack` to resume.
- **Full rebuild orchestration**: there is no single command yet that performs
  destroy, Terraform/Terragrunt apply, Ansible configuration, and smoke tests as
  one auditable rebuild.

---

## Target State

### Per-stack smoke tests

Each stack should be able to declare a smoke test — a minimal check that the
deployed service is reachable and responding correctly. The check runs
automatically after the Ansible playbook for that stack succeeds.

**Design**: each stack directory gets an optional `smoke-test.sh` (or declared
check command in `stack.yaml`). The provision harness runs it after Ansible
completes. Failure aborts the run at that stack rather than continuing to
dependent stacks.

Examples of what a smoke test would check:

| Stack | Smoke test |
|---|---|
| step-ca-stack | `step ca health --ca-url https://<LAB_IP_STEP_CA> --root certs/homelab-root.crt` |
| dns-stack | `dig @<LAB_IP_DNS> step-ca.<LAB_DOMAIN> +short` returns the expected IP |
| harbor-stack | `curl -sf https://<LAB_FQDN_HARBOR>/api/v2.0/health` returns `{"status":"healthy"}` |
| monitoring-stack | VictoriaMetrics `/api/v1/targets` — all node_exporter targets `up` |
| authentik-stack | `curl -sf https://<LAB_FQDN_AUTHENTIK>/api/v3/root/config/` returns HTTP 200 |
| proxy-stack | Traefik `/ping` returns HTTP 200 |

Smoke tests must be idempotent, side-effect-free, and fast (target: under 30s
per stack). They are not integration tests — they confirm the service is alive and
responding, not that it produces correct output.

This is the primary mechanism for reducing routine teardown testing. Most
Ansible and service-management changes should be validated by syntax checks,
targeted provisioning, and stack smoke tests instead of by a full destroy and
rebuild.

### Dependency-aware partial re-run

When a stack fails, the harness should report clearly which stack failed and which
downstream stacks were skipped. Re-running with `--stack <failed>` should resume
from that point, honouring the dependency order.

This is largely already supported via `--stack`; the missing piece is clear
reporting of what was skipped and why.

### Parallel execution for independent stacks

Stacks with no dependency relationship between them can be provisioned in parallel.
The topological sort already produces a valid ordering; the next step is to
identify stacks at the same dependency depth and run them concurrently.

Dependency placement should be rationalised according to each stack's function
and requirements. The harness must compute layers from current `stack.yaml`
metadata rather than relying on a static table. If a service consumes DNS, PKI,
Harbor, Authentik, Traefik, apt-cacher, or another platform dependency, that
relationship should be explicit in `depends_on`.

This is most valuable for the `apps` tier, where harbor, netbox, and authentik
are independent of each other and currently provision sequentially. In practice
each takes 5–15 minutes; parallelism here would halve the total provisioning time
for a full `--tier apps` run.

**Implementation note**: parallelism adds complexity to log output and error
handling. A simple approach is to batch by dependency level and run each batch in
parallel with `wait`. Log output should be prefixed with the stack name.

### Environment-scoped invocation

The harness should make it explicit which environment is being targeted. Currently
environment selection happens at the shell level (which wrapper script you ran).
Because secrets and env files are loaded by the wrapper before `provision.sh`
starts, target selection must happen before the wrapper invocation:

```
PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --stack monitoring-stack
./with-secrets-prod scripts/provision.sh --tier platform
```

Recommendation: `provision.sh` may accept a guard argument such as
`--target-env`, but it should only verify that `PVE_ENV` and
`TF_VAR_proxmox_node` already match. It must not attempt to choose secrets after
the wrapper has already selected them.

### Full rebuild harness

Add a separate rebuild command, or extend an existing teardown harness, for the
cases where fresh-install behaviour is the thing being validated. That command
should:

- Select the environment before loading secrets.
- Verify the target node before any mutating action.
- Run Terraform/Terragrunt destroy and apply.
- Run `scripts/provision.sh --tier <...>`.
- Run smoke and integration checks.
- Emit a concise validation summary that can be attached to promotion notes.

---

## Test Strategy

**Scope**: the provisioning harness tests are not unit tests of Ansible roles.
They verify that the deployed service actually works. Three levels:

### 1. Syntax validation (pre-deploy, fast)

- `ansible-playbook --syntax-check` on all affected playbooks
- `terraform validate` on all affected modules
- Run in CI on every push to a development branch

### 2. Stack smoke test (post-deploy, per stack)

- Run by the provisioning harness immediately after each stack deploy
- Stack-specific health checks (see table above)
- Should complete in under 60s per stack

### 3. Integration test (post-full-deploy, promotion or periodic)

- Run after all stacks are up
- Cross-stack checks: e.g., VictoriaMetrics can scrape all 10 node_exporter
  targets, Grafana OIDC login works end-to-end, Harbor image pull from a
  managed LXC succeeds
- Not run on every stack deploy. Run after a full `--tier all` provision, before
  promotion when the change affects cross-stack behaviour, or periodically as a
  fresh-install confidence check.

The integration test suite is currently implicit (manual checklist in
`docs/teardown-test/`). Formalising it as a script or set of scripts that can
be run against any environment is follow-on work.

---

## Relationship to Branch Model

The provisioning harness is the mechanism that enforces the [branch model](branch-model.md)
validation tiers:

| Branch model gate | Harness action |
|---|---|
| Ansible task/role change | `provision.sh --stack <affected>` on pve-test |
| Full rebuild cycle | `terraform destroy` → `terraform apply` → `provision.sh --tier all` → integration test on pve-test |
| pve smoke test (stable → main) | `provision.sh --stack <affected>` on pve, then stack smoke tests |

As smoke tests and integration tests are formalised, the harness becomes the
single command that validates a promotion rather than a manual checklist.

Promotion still requires the appropriate security scan before merge. New scan
findings should become GitHub issues with linked evidence and an explicit
blocking/non-blocking decision.
