# Current State — Session Resume Point

## Purpose

This is the master resume point for the current sprint. Use it together with
the workstream docs listed below. Files under `docs/*/artifacts/` are ignored
session evidence, not durable documentation.

## Current Position (as of 2026-06-13)

On `baseline/teardown-validated` (commit `b7e20ba`).

`feat/netbox-populate-multi-source-inventory` was merged and the branch
deleted. The teardown gate was satisfied via a full cycle on **pve-test-vm**
(`192.168.1.41` — the bare-metal-hosted VM, not the retired laptop
`pve-test`). Validated in browser.

Documentation consistency pass completed (`38508f1`, `b7e20ba`): teardown-test
docs updated to reflect pve-test-vm, `dev/pve-test` replaced with
`baseline/teardown-validated` across all active planning and task docs.

**Immediate next action:** cut `fix/ci-pipeline-cleanup` from
`baseline/teardown-validated` and work through items 1a–1d below.

**Sprint plan:** see [sprint-plan.md](sprint-plan.md) for the full five-session
breakdown with handoffs, gates, and dependency order.

## Planned Branches

Three branches follow in order after the current branch is merged. They are
independent and can be worked in parallel, but the order below reflects
priority.

---

### Branch 1: `fix/ci-pipeline-cleanup`

No operational impact. No teardown gate required. Gate: CI passes on the branch.

#### 1a — Remove `dev/pve-test` from workflow triggers

`dev/pve-test` is an archival branch. Three workflow files still trigger on it:

| File | Lines to change |
|---|---|
| `.github/workflows/validate.yml` | `branches:` blocks on `push` and `pull_request` |
| `.github/workflows/security-scan.yml` | `branches:` blocks on `push` and `pull_request` |
| `.github/workflows/supply-chain-signing-proof.yml` | `branches:` on `push` |

Replace `dev/pve-test` entries with `baseline/teardown-validated` in each.

#### 1b — Fix ShellCheck false positives

ShellCheck fails with exit code 123 on several scripts. All are false positives:
- **SC2016** (`Expressions don't expand in single quotes`): fired on intentional
  single-quoted strings in `bash -c '...'` args and `printf` format strings.
  These are correct — you *want* no expansion on the calling side.
- **SC1090** (`Can't follow non-constant source`): fired on `source $VAR` patterns
  in scripts that source dynamic paths.
- **SC2034** (`appears unused`): fired on `depends_on` and `playbook` variables
  that are used externally by the provisioning framework.

Affected scripts (from CI log):
- `scripts/rebuild-gate-destroy.sh` (line 88)
- `scripts/plan-pve-infra-teardown.sh` (lines 477–595)
- `scripts/merge-sops-env.sh` (lines 29, 33)
- `scripts/run-netbox-populate-container.sh` (lines 20, 22)
- `scripts/check-proxmox-status.sh` (line 198)
- `scripts/preflight-network-refactor.sh` (line 44)
- `scripts/deploy-phase-04.sh` (line 79)
- `scripts/deploy-phase-04-orchestrate.sh` (line 128)
- `router/scripts/cutover.sh` (lines 25, 86)

Fix: add targeted `# shellcheck disable=SC2016` (and SC1090, SC2034 where
applicable) directives at the offending lines. Do not suppress globally at
file level unless the pattern is pervasive throughout the whole file.

#### 1c — Fix Harbor-only image reference failures

The CI check (`harbor-image-policy` job in `validate.yml`) rejects compose
files containing `image:` lines that reference `docker.io`, `ghcr.io`,
`quay.io`, or `registry.k8s.io` directly.

Failing files (non-terragrunt-cache):

| File | Offending image |
|---|---|
| `terraform/lxc/stacks/authentik-stack/docker-compose.yml:30,67` | `ghcr.io/goauthentik/server:2024.12.3` |
| `terraform/lxc/stacks/authentik-stack/docker-compose.yml:56` | `docker.io/library/nginx:1.27-alpine` |

Note: `gcr.io/cadvisor/cadvisor` references are NOT caught by this check
(gcr.io is not in the regex) — leave them for now.

The authentik playbook deploys the static `docker-compose.yml` directly via
`lookup('file', '../../stacks/authentik-stack/docker-compose.yml')`. These
are the actual deployed image references. They need to use Harbor proxy cache
paths:
- `ghcr.io/goauthentik/server` → `harbor.lab.gibbsgreatly.xyz/ghcr-io/goauthentik/server`
  (requires Harbor to have a `ghcr-io` proxy cache configured for `ghcr.io`)
- `docker.io/library/nginx` → `harbor.lab.gibbsgreatly.xyz/dockerhub/library/nginx`
  (Harbor `dockerhub` proxy cache is already configured)

**Pre-condition:** Verify Harbor has a proxy cache project for `ghcr.io` before
changing the goauthentik image reference. If not, create the proxy cache project
first (Harbor UI → Administration → Registries → New endpoint: `ghcr.io`; then
new Project with proxy cache enabled targeting that registry).

#### 1d — Ansible lint

Local runs from repo root produce only `yaml[line-length]` warnings (not
errors). The CI failure needs investigation on the branch — check whether the
CI job uses a different profile or `.ansible-lint` config that treats warnings
as fatal. If so, either adjust the profile or add line-length exceptions to
`.ansible-lint`.

---

### Branch 2: `fix/tls-hardening`

Affects two running services. Gate: live login test via Authentik SSO on both
Harbor and at least one other Authentik-protected service (Grafana or Portainer)
after redeploy.

#### 2a — Traefik forward-auth: replace `insecureSkipVerify` with CA

File: `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`

The Authentik middleware config currently skips TLS verification. Traefik's
`forwardAuth.tls` supports a `ca:` field. The combined CA bundle (system CAs
plus homelab root CA) is already mounted in the Traefik container at
`/certs/combined-ca.crt`. Change:

```yaml
# Before (line ~165):
tls:
  insecureSkipVerify: true

# After:
tls:
  ca: /certs/combined-ca.crt
```

The combined CA bundle is built conditionally in the playbook: if
`/usr/local/share/ca-certificates/homelab-root.crt` exists on the proxy host,
it is appended to the system CA bundle. So this works whether or not step-ca
has been deployed before proxy-stack.

Run `deploy-proxy-stack.yml` to apply, then test: confirm Grafana/Portainer
still authenticate through Authentik.

#### 2b — Harbor OIDC: enable cert verification

File: `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`

`harbor_postconfigure_oidc_verify_cert` defaults to `false`. Harbor's OIDC
endpoint is the **public** Authentik URL (via Traefik, Let's Encrypt cert).
Harbor container images trust Let's Encrypt by default. No cert configuration
changes needed — just enable verification.

Option A: change the default in the playbook:
```yaml
# Line ~80, change default from 'false' to 'true':
harbor_postconfigure_oidc_verify_cert: "{{ lookup('env', 'HARBOR_OIDC_VERIFY_CERT') | default('true', true) | bool }}"
```

Option B: add `HARBOR_OIDC_VERIFY_CERT=true` to `terraform/secrets.enc.yaml`.

Either works. Option A (change the default) is cleaner — the env var override
remains available if you ever need to disable it temporarily.

Run `deploy-harbor-stack.yml` to apply, then test: log into Harbor UI via
the Authentik SSO button.

---

### Branch 3: `feat/step-ca-metrics`

Purely additive — no existing services affected. Gate: Grafana shows the
`step-ca` scrape target as `UP` in the VictoriaMetrics targets page.

File: `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`

#### 3a — Mount the homelab CA into VictoriaMetrics

The monitoring-stack LXC has the homelab root CA at
`/usr/local/share/ca-certificates/homelab-root.crt` (placed by `lxc_base`).
The VictoriaMetrics container needs it to verify the step-ca TLS cert.

In the VictoriaMetrics service definition in the compose block, add a volume:
```yaml
volumes:
  - /usr/local/share/ca-certificates/homelab-root.crt:/etc/ssl/certs/homelab-root.crt:ro
  # (keep existing volumes)
```

#### 3b — Add the step-ca scrape job

In the inline scrape config (already written via `ansible.builtin.copy`),
add a new job after the existing jobs:

```yaml
- job_name: step-ca
  scheme: https
  tls_config:
    ca_file: /etc/ssl/certs/homelab-root.crt
  static_configs:
    - targets: ["{{ lookup('env', 'LAB_IP_STEP_CA') }}:9443"]
      labels:
        stack: step-ca-stack
```

Run `deploy-monitoring-stack.yml` to apply. Verify in Grafana:
Status → Targets → job=step-ca shows state=UP.

---

## Branch Promotion Order

| Branch | Gate | Promotion target |
|---|---|---|
| `feat/netbox-populate-multi-source-inventory` | Teardown done ✓ | `baseline/teardown-validated` ✓ merged 2026-06-13 |
| `fix/ci-pipeline-cleanup` | CI passes on branch | `baseline/teardown-validated` |
| `fix/tls-hardening` | Live Authentik SSO test on Harbor + one other service | `baseline/teardown-validated` |
| `feat/step-ca-metrics` | step-ca target `UP` in Grafana | `baseline/teardown-validated` |

## What Not To Reopen

Do not start the following in this sprint:

- Traefik → Harbor backend HTTPS (decided: Traefik handles TLS termination;
  the internal HTTP leg is acceptable)
- Harbor OIDC internal direct endpoint (deferred: complex discovery-coupled
  behavior, see `docs/step-ca-implementation/internal-tls-consumer-matrix.md`)
- Broad docker-socket-proxy rollout (separate workstream)
- NetBox static hosts or stale IP cleanup (minor, not blocking)
- pve production parity (separate promotion gate)

## Related Docs

- `docs/netbox-stack/current-state.md` — netbox workstream resume
- `docs/monitoring-stack/design.md` — monitoring current state and remaining gaps
- `docs/step-ca-implementation/internal-tls-consumer-matrix.md` — TLS consumer classification
- `CLAUDE.md` — branch model, promotion gates, credential controls
