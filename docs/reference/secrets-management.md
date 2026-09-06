# Secrets Management

## Overview

Environment configuration is split into two tiers:

| Tier | What goes here | File | Committed? |
| --- | --- | --- | --- |
| Non-secret config | Hostnames, node names, IP addresses, usernames, workspace names | `.env`, `.env.<node>` | No (`.env`/`.env.<node>` are gitignored — except `.env.pve`/`.env.pve-test`/`.env.pve-test-vm`/`.env.pve-framework`, which predate that rule and are tracked; see the note in Decision 6) |
| Secrets | Passwords, tokens, API keys | `terraform/secrets.common.enc.yaml` + `terraform/secrets.<node>.enc.yaml` | Yes (SOPS-encrypted) |

As of 2026-07-17, secrets are split across **one common file plus one delta
file per production-trust node** — `pve`, `pve-test-vm`, and (once it has a
real Terraform token) `pve-framework` — rather than one shared file plus
near-complete duplicate copies per environment. See
`docs/framework-integration/decisions.md` Decision 6 for the full rationale
and the migration that produced this layout; this doc describes the
resulting model, not the history.

```bash
./with-secrets tofu plan
./with-secrets ansible-playbook -i ansible/inventory/dev.yml site.yml
./with-secrets sonar-scanner
./with-secrets snyk iac test terraform/
```

`with-secrets` loads `.env` first, then `.env.<PVE_ENV>`, then decrypts and
overlays `secrets.common.enc.yaml` merged with `secrets.<PVE_ENV>.enc.yaml`
(if that node has one). A node's own delta file always wins over `common`
if the same key appears in both.

## The common/per-node split

**`terraform/secrets.common.enc.yaml`** holds every secret that is
genuinely the same value everywhere — the large majority. Two kinds of
secret end up here:

- Shared infrastructure credentials that exist once regardless of how many
  Proxmox environments consume them (there is only one MikroTik router,
  one Cloudflare zone, one SonarCloud/Snyk account, one Docker Hub
  pull-through account).
- Secrets that are technically per-environment-instance (Authentik,
  NetBox, Harbor, step-ca each run their own instance per environment) but
  are deliberately kept identical across environments by design/convention
  rather than left to drift — e.g. `HARBOR_ADMIN_PASSWORD` and
  `PORTAINER_OAUTH_CLIENT_SECRET` are meant to be the same value
  everywhere; if a given environment's live Harbor/Authentik doesn't
  already match, that's a reconciliation task for that environment, not a
  reason to fork the secret.

**`terraform/secrets.<node>.enc.yaml`** holds only secrets that are
*genuinely, structurally* tied to that specific Proxmox node — today just:

- `PROXMOX_READONLY_TOKEN_ID` / `PROXMOX_READONLY_TOKEN_SECRET` — a
  read-only Proxmox API discovery token, issued per-node and meaningless
  against any other node's API.
- `TF_VAR_pm_api_token_secret` — the Terraform automation token, same
  reasoning.
- `TF_VAR_lxc_password` — kept per-node by operator choice (not unified;
  revisit if that changes).

If you're deciding where a new secret belongs: default to `common`. Only
put it in a per-node delta file if the value is inherently tied to that
node's own Proxmox API identity (like the token family above) — not
merely because the secret happens to currently only be consumed by a
stack that runs on one environment.

## Non-secret config (.env)

Copy `.env.template` to `.env` and adjust for your environment:

```bash
cp .env.template .env
# Edit .env — set PROXMOX_HOST, TF_WORKSPACE, etc. for your target environment
```

`.env` is gitignored and never committed (new `.env.<node>` files are too —
see the tracked-legacy-files note above). For `pve-test-vm`, the key
overrides from the default are:

```bash
export PROXMOX_HOST='pve-test-vm.gibbsgreatly.xyz'
export TF_VAR_proxmox_node=pve-test-vm
export TF_VAR_proxmox_host="${PROXMOX_HOST}"
export TF_WORKSPACE=pve-test-vm
export TF_VAR_portainer_server_ip=192.168.20.20
export TF_VAR_registry_host=192.168.40.10
export TF_VAR_apt_cacher_host=192.168.40.11
```

## Secrets (SOPS + age)

All secrets are stored encrypted via SOPS + age, split as described above.

### Prerequisites

The age private key lives at `~/.config/sops/age/keys.txt` (mode `0600`).
Retrieve it from Bitwarden: **"proxmox-homelab age private key"**

```bash
mkdir -p ~/.config/sops/age
install -m 600 /dev/stdin ~/.config/sops/age/keys.txt
# paste key content, then Ctrl-D
```

### Inspect secrets

```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.common.enc.yaml
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.pve.enc.yaml
```

### Guard required keys from accidental removal

Run this check before or after editing `terraform/secrets.common.enc.yaml`:

```bash
bash scripts/check-required-sops-keys.sh
```

By default it enforces presence of (in `secrets.common.enc.yaml` — these
are shared-router credentials, not per-node):

- `MIKROTIK_USER`
- `MIKROTIK_PASSWORD`
- `MIKROTIK_ADMIN`
- `MIKROTIK_ADMIN_PASSWORD`

The same check runs in pre-commit whenever `terraform/secrets.common.enc.yaml`
is part of a commit.

### Edit a secret (re-encrypts on save)

```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.common.enc.yaml
# or, for a node-specific secret:
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.pve.enc.yaml
```

### Add a new secret

1. Decide common vs per-node using the rule above.
2. `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.<common-or-node>.enc.yaml`
3. Add `KEY_NAME: value` in your `$EDITOR`
4. Save — sops re-encrypts automatically
5. Commit the updated file

### Secret inventory

Common (`terraform/secrets.common.enc.yaml`) — used by every environment:

| Key | Purpose | Used by |
| --- | --- | --- |
| `TF_VAR_lxc_password` | Generic fallback default LXC root password for any environment without its own override | Terraform |
| `TF_VAR_portainer_admin_password` | Portainer initial admin | deploy-portainer-stack |
| `NETBOX_DB_PASSWORD` | NetBox PostgreSQL password | deploy-netbox-stack |
| `NETBOX_REDIS_PASSWORD` | NetBox Redis password | deploy-netbox-stack |
| `NETBOX_REDIS_CACHE_PASSWORD` | NetBox Redis cache password | deploy-netbox-stack |
| `NETBOX_SECRET_KEY` | NetBox Django secret key | deploy-netbox-stack |
| `NETBOX_API_TOKEN_PEPPER` | NetBox API token pepper | deploy-netbox-stack |
| `NETBOX_SUPERUSER_PASSWORD` | NetBox superuser password | deploy-netbox-stack |
| `NETBOX_SUPERUSER_API_TOKEN` | NetBox superuser API token | Ansible NetBox API calls |
| `NETBOX_API_TOKEN` | Least-privilege NetBox automation token (non-superuser) | reconciliation tooling |
| `MIKROTIK_ADMIN` | MikroTik admin username (write operations) | Manual / future IaC |
| `MIKROTIK_ADMIN_PASSWORD` | MikroTik admin password (write operations) | Manual / future IaC |
| `MIKROTIK_USER` | MikroTik read-only API username (legacy name) | Manual |
| `MIKROTIK_PASSWORD` | MikroTik read-only API password (legacy name) | Manual |
| `MIKROTIK_READONLY_USER` | MikroTik read-only API username (preferred name) | NetBox discovery |
| `MIKROTIK_READONLY_PASSWORD` | MikroTik read-only API password (preferred name) | NetBox discovery |
| `HARBOR_ADMIN_PASSWORD` | Harbor admin password (unified across environments by convention, not auto-generated per instance) | deploy-harbor-stack |
| `HARBOR_DB_PASSWORD` | Harbor PostgreSQL password | deploy-harbor-stack |
| `HARBOR_OIDC_CLIENT_ID` | Harbor OIDC client ID (Authentik application slug/client ID) | deploy-harbor-stack |
| `HARBOR_OIDC_CLIENT_SECRET` | Harbor OIDC client secret | deploy-harbor-stack |
| `HARBOR_ROBOT_USER` | Harbor robot account username | All stack playbooks (image pull auth) |
| `HARBOR_ROBOT_PASSWORD` | Harbor robot account password | All stack playbooks (image pull auth) |
| `HARBOR_DOCKERHUB_USERNAME` | DockerHub pull-through account | Harbor proxy cache config |
| `HARBOR_DOCKERHUB_PASSWORD` | DockerHub pull-through password | Harbor proxy cache config |
| `PORTAINER_OAUTH_CLIENT_SECRET` | Portainer's Authentik OAuth client secret (unified across environments by convention) | deploy-portainer-stack |
| `SONAR_TOKEN` | SonarCloud analysis token | CI / `sonar-scanner` |
| `SNYK_TOKEN` | Snyk IaC scan token | CI / `snyk iac test` |
| `AUTHENTIK_SECRET_KEY` | Authentik Django secret key (must never change) | deploy-authentik-stack |
| `AUTHENTIK_POSTGRES_PASSWORD` | Authentik PostgreSQL password | deploy-authentik-stack |
| `AUTHENTIK_SUPERUSER_PASSWORD` | Authentik initial admin password | deploy-authentik-stack |
| `AUTHENTIK_SUPERUSER_API_TOKEN` | Authentik API token for IaC automation | terraform-provider-authentik |
| `CF_DNS_API_TOKEN` | Cloudflare DNS API token — `Zone:DNS:Edit` for `gibbsgreatly.xyz` only (SEC-07) | deploy-proxy-stack (Traefik DNS-01) |
| `STEP_CA_PASSWORD` | step-ca root CA key password | deploy-step-ca |
| `STEP_CA_PROVISIONER_PASSWORD` | step-ca ACME provisioner password | deploy-step-ca |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin password | deploy-monitoring-stack |
| `GRAFANA_OAUTH_CLIENT_ID` | Grafana OAuth client ID (from Authentik OIDC provider) | deploy-monitoring-stack |
| `GRAFANA_OAUTH_CLIENT_SECRET` | Grafana OAuth client secret (from Authentik OIDC provider) | deploy-monitoring-stack |
| `TF_VAR_dayz_steam_username` / `TF_VAR_dayz_steam_password` | Steam account for the (pve-only) DayZ gaming-stack | gaming-stack |

Per-node (`terraform/secrets.<node>.enc.yaml`, one file per production-trust
node — see `terraform/PRODUCTION_NODES`):

| Key | Purpose | Used by |
| --- | --- | --- |
| `PROXMOX_READONLY_TOKEN_ID` | Read-only Proxmox API discovery token ID for this node | NetBox discovery, health checks |
| `PROXMOX_READONLY_TOKEN_SECRET` | Read-only Proxmox API discovery token secret for this node | NetBox discovery, health checks |
| `TF_VAR_pm_api_token_secret` | Proxmox API token secret for this node | Terraform |
| `TF_VAR_lxc_password` | Default LXC root password override for this node | Terraform |

**SEC-07 reminder:** The Cloudflare API token (`CF_DNS_API_TOKEN`) must be scoped to
`Zone:DNS:Edit` for `gibbsgreatly.xyz` only. Rotate after each development pass.

**Known follow-up (not automatic):** `HARBOR_ADMIN_PASSWORD` and
`PORTAINER_OAUTH_CLIENT_SECRET` being unified in `secrets.common.enc.yaml`
only changes what's in the file. Each environment's already-provisioned
Harbor/Authentik instance stores its own copy of these internally at
deploy time, so any environment whose live values don't already match the
common one needs a separate reconciliation (reset Harbor's admin password;
update the Authentik OAuth application's client secret) — a file edit
alone doesn't retroactively change already-running service state.

## CI

The `sops-decrypt-check` job in `validate.yml` verifies decryption succeeds
for every `terraform/secrets*.enc.yaml` file on every push (both the
common file and every per-node delta file). It uses the `SOPS_AGE_KEY`
GitHub Actions secret (set via `gh secret set SOPS_AGE_KEY`).

## Key management

The public key is committed in `.sops.yaml`. The private key is **never committed**.

### Rotate the age key

```bash
age-keygen -o ~/.config/sops/age/keys-new.txt

# Re-encrypt with new key (update .sops.yaml first with new public key)
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops updatekeys terraform/secrets.common.enc.yaml
# Repeat for every terraform/secrets.<node>.enc.yaml file

# Update GitHub Actions secret
gh secret set SOPS_AGE_KEY < ~/.config/sops/age/keys-new.txt

# Store new key in Bitwarden
```
