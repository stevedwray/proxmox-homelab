# pve Parity Pass 01

## Goal

Capture the first concrete `pve` vs `pve-test` parity pass using the current
repo state, with `pve-test` treated as the known-good reference model.

This pass is intentionally narrow:

- active platform runtime inputs only
- current wrappers only
- no secret values recorded

## Reference Rule

When a runtime key is required for the active `pve` path and is missing from
the production path, derive it from the working `pve-test` path first unless
the key is intentionally environment-specific.

For this pass, the reference sources were:

- `terraform/secrets.enc.yaml`
- `terraform/secrets.pve.enc.yaml`
- `.env`
- `.env.pve`
- `.env.pve-test`
- current stack contracts and active Ansible playbooks

## Wrapper Reality

`./with-secrets` and `./with-secrets-prod` do not load the same input surface.

- `./with-secrets` loads `.env`, then `.env.<PVE_ENV>`, then
  `terraform/secrets.enc.yaml`
- `./with-secrets-prod` loads `.env.pve`, then
  `terraform/secrets.pve.enc.yaml`

Implication:

- a key present only in `.env` is available on `pve-test`
- that same key is missing on `pve` unless it is also present in `.env.pve`

## Secret Parity

### Required now on `pve` and missing from `terraform/secrets.pve.enc.yaml`

These are current blockers or latent blockers for repeatable production runs.

| Key | Why it matters on `pve` | Present in `terraform/secrets.enc.yaml` |
|---|---|---|
| `CF_DNS_API_TOKEN` | Mandatory input for `proxy-stack` ACME DNS challenge flow | yes |

### Presently documented as required, but not current `pve` blockers

The current runner canary docs still refer to `GITHUB_RUNNER_TOKEN` and
`GITHUB_RUNNER_REPO` as mandatory inputs. The live playbook path no longer
depends on those names:

- `runner_repo` defaults internally to
  `https://github.com/stevedwray/proxmox-homelab`
- the playbook generates a fresh runner registration token through `gh api`
  when `runner_registration_token` is not provided

That means the actual precondition for `ci-runner-01` is an authenticated local
GitHub CLI session with permission to mint runner registration tokens, not
static `GITHUB_RUNNER_*` entries in either SOPS file.

### Present in `terraform/secrets.enc.yaml` only, but not current `pve` blockers

These keys exist in the legacy/default SOPS file but do not appear to be the
main production blockers for the currently migrated platform path.

| Key | Current read |
|---|---|
| `GRAFANA_ADMIN` | Legacy alias; current playbook uses `GRAFANA_ADMIN_PASSWORD` and defaults `GRAFANA_ADMIN_USER=admin` |
| `GRAFANA_OAUTH_CLIENT_ID` | Optional in current playbook; defaults to `grafana` |
| `HARBOR_ADMIN` | Legacy alias; current playbook uses `HARBOR_ADMIN_PASSWORD` |
| `HARBOR_ROBOT_USER` | CI/runtime consumer secret, not a stack deployment blocker |
| `HARBOR_ROBOT_PASSWORD` | CI/runtime consumer secret, not a stack deployment blocker |
| `NPM_DB_PASSWORD` | Legacy/unrelated to the active productionized platform set |

## Non-Secret Env Parity

### Effective parity already matches the working `pve-test` model

The core segmented service IPs and gateways already line up between `.env` and
`.env.pve`. This is good news: the basic addressing model is not the current
problem.

- `LAB_IP_APT_CACHER=192.168.40.11`
- `LAB_IP_AUTHENTIK=192.168.20.10`
- `LAB_IP_STEP_CA=192.168.20.11`
- `LAB_IP_DNS=192.168.20.13`
- `LAB_IP_PROXY=192.168.30.10`
- `LAB_IP_HARBOR=192.168.40.10`
- `LAB_IP_MONITORING=192.168.20.12`
- `LAB_IP_NETBOX=192.168.40.12`
- `LAB_IP_PORTAINER=192.168.20.20`
- `LAB_IP_CI_RUNNER=192.168.10.63`
- `LAB_GW_BUILD=192.168.10.1`
- `LAB_GW_MGMT=192.168.20.1`
- `LAB_GW_EDGE=192.168.30.1`
- `LAB_GW_INFRA=192.168.40.1`

### Required by the production wrapper path and currently missing from `.env.pve`

These are available to `pve-test` through `.env`, but `./with-secrets-prod`
does not source `.env`, so they are effectively absent on `pve` today unless
the operator injects them some other way.

| Key | Why it matters on `pve` | Present in `.env` | Present in `.env.pve` |
|---|---|---|---|
| `TRAEFIK_DNS_RESOLVER_PRIMARY` | Mandatory `proxy-stack` input | yes | no |
| `TRAEFIK_DNS_RESOLVER_SECONDARY` | Mandatory `proxy-stack` input | yes | no |

### Not current blockers

| Key | Current read |
|---|---|
| `AUTHENTIK_EXTRA_CA` | Present only in `.env.pve-test`; not currently required by the migrated `pve` canary evidence |
| `RUNNER_NAME` | Optional; playbook now defaults to `ci-runner-01` |
| `RUNNER_LABELS` | Optional; playbook now defaults to `self-hosted,pve-test,build,linux,x64` |
| `RUNNER_SERVICE_NAME` | Optional; derived from runner name if unset |

## Immediate Fill Actions

1. Copy `CF_DNS_API_TOKEN` from `terraform/secrets.enc.yaml` into
   `terraform/secrets.pve.enc.yaml`.
2. Add `TRAEFIK_DNS_RESOLVER_PRIMARY` and
   `TRAEFIK_DNS_RESOLVER_SECONDARY` to `.env.pve` so the production wrapper has
   the same effective input surface as the working `pve-test` path.
3. Reconcile the `ci-runner-01` production docs and preflights with the actual
   `gh`-backed runner registration flow so the next canary does not block on
   stale `GITHUB_RUNNER_*` requirements.
4. After parity fill, re-run the affected production provisioning paths from the
   `pve-test`-known-good contract rather than preserving canary-time workarounds
   as permanent drift.

## Recommended Follow-On Pass

After the key-surface parity above is filled, the next pass should compare the
application integration behavior that worked on `pve-test` against the current
`pve` state for:

- Harbor <-> Authentik OIDC reconcile
- Portainer <-> Authentik OIDC reconcile
- Monitoring <-> Authentik OIDC reconcile
- runner registration/runtime dependencies
