# Secrets Management

## Overview

Environment configuration is split into two tiers:

| Tier | What goes here | File | Committed? |
|---|---|---|---|
| Non-secret config | Hostnames, node names, IP addresses, usernames, workspace names | `.env` | No (gitignored) |
| Secrets | Passwords, tokens, API keys | `terraform/secrets.enc.yaml` | Yes (SOPS-encrypted) |

Both tiers are injected together by the `./with-secrets` wrapper:

```bash
./with-secrets tofu plan
./with-secrets ansible-playbook -i ansible/inventory/dev.yml site.yml
./with-secrets sonar-scanner
./with-secrets snyk iac test terraform/
```

`with-secrets` loads `.env` first, then decrypts and overlays `secrets.enc.yaml`.
Secrets take precedence if a key appears in both files.

## Non-secret config (.env)

Copy `.env.template` to `.env` and adjust for your environment:

```bash
cp .env.template .env
# Edit .env — set PROXMOX_HOST, TF_WORKSPACE, etc. for your target environment
```

`.env` is gitignored and never committed. For pve-test, the key overrides from the default are:

```bash
export PROXMOX_HOST='pve-test.gibbsgreatly.xyz'
export TF_VAR_proxmox_node=pve-test
export TF_VAR_proxmox_host="${PROXMOX_HOST}"
export TF_WORKSPACE=pve-test
export TF_VAR_portainer_server_ip=10.57.1.20
export TF_VAR_registry_host=10.57.3.10
export TF_VAR_apt_cacher_host=10.57.3.11
```

## Secrets (SOPS + age)

All secrets are stored encrypted in `terraform/secrets.enc.yaml` via SOPS + age.

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
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.enc.yaml
```

### Edit a secret (re-encrypts on save)
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml
```

### Add a new secret
1. `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml`
2. Add `KEY_NAME: value` in your `$EDITOR`
3. Save — sops re-encrypts automatically
4. Commit the updated `secrets.enc.yaml`

### Secret inventory

| Key | Purpose |
|---|---|
| `TF_VAR_pm_api_token_secret` | Proxmox API token secret |
| `TF_VAR_lxc_password` | Default LXC root password |
| `TF_VAR_portainer_admin_password` | Portainer initial admin |
| `NETBOX_DB_PASSWORD` | NetBox PostgreSQL password |
| `NETBOX_REDIS_PASSWORD` | NetBox Redis password |
| `NETBOX_REDIS_CACHE_PASSWORD` | NetBox Redis cache password |
| `NETBOX_SECRET_KEY` | NetBox Django secret key |
| `NETBOX_API_TOKEN_PEPPER` | NetBox API token pepper |
| `NETBOX_SUPERUSER_PASSWORD` | NetBox superuser password |
| `NETBOX_SUPERUSER_API_TOKEN` | NetBox superuser API token |
| `MIKROTIK_ADMIN` | MikroTik admin automation username (preferred for write operations) |
| `MIKROTIK_ADMIN_PASSWORD` | MikroTik admin automation password (preferred for write operations) |
| `MIKROTIK_USER` | MikroTik API username |
| `MIKROTIK_PASSWORD` | MikroTik API password |
| `HARBOR_ADMIN_PASSWORD` | Harbor admin password |
| `HARBOR_DB_PASSWORD` | Harbor PostgreSQL password |
| `HARBOR_DOCKERHUB_USERNAME` | DockerHub pull-through account |
| `HARBOR_DOCKERHUB_PASSWORD` | DockerHub pull-through password |
| `NPM_DB_PASSWORD` | Nginx Proxy Manager DB password |
| `SONAR_TOKEN` | SonarCloud analysis token |
| `SNYK_TOKEN` | Snyk IaC scan token |
| `AUTHENTIK_SECRET_KEY` | Authentik Django secret key |
| `AUTHENTIK_POSTGRES_PASSWORD` | Authentik PostgreSQL password |
| `AUTHENTIK_SUPERUSER_PASSWORD` | Authentik initial admin password |
| `AUTHENTIK_SUPERUSER_API_TOKEN` | Authentik API token |
| `CF_DNS_API_TOKEN` | Cloudflare DNS API token (step-ca ACME) |
| `STEP_CA_PASSWORD` | step-ca root CA key password |
| `STEP_CA_PROVISIONER_PASSWORD` | step-ca ACME provisioner password |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin password |
| `GRAFANA_OAUTH_CLIENT_SECRET` | Grafana OAuth client secret |

Keys marked `CHANGEME_*` are placeholders for services not yet deployed.

## CI

The `sops-decrypt-check` job in `validate.yml` verifies decryption succeeds on every push.
It uses the `SOPS_AGE_KEY` GitHub Actions secret (set via `gh secret set SOPS_AGE_KEY`).

## Key management

The public key is committed in `.sops.yaml`. The private key is **never committed**.

### Rotate the age key
```bash
age-keygen -o ~/.config/sops/age/keys-new.txt

# Re-encrypt with new key (update .sops.yaml first with new public key)
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops updatekeys terraform/secrets.enc.yaml

# Update GitHub Actions secret
gh secret set SOPS_AGE_KEY < ~/.config/sops/age/keys-new.txt

# Store new key in Bitwarden
```
