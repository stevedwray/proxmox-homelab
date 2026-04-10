# Secrets Management

## Overview

Infrastructure credentials are stored encrypted in Git using **SOPS + age**.
CI-tool credentials (SONAR_TOKEN, SNYK_TOKEN) go directly into GitHub Actions secrets.

| Secret | Storage |
|---|---|
| `proxmox_token_secret` | SOPS (`terraform/secrets.enc.yaml`) |
| `lxc_password` | SOPS |
| `portainer_admin_password` | SOPS |
| `netbox_*` | SOPS |
| `mikrotik_*` | SOPS |
| `SONAR_TOKEN` | GitHub Actions secret |
| `SNYK_TOKEN` | GitHub Actions secret |
| `SOPS_AGE_KEY` | GitHub Actions secret + Bitwarden |

## Encrypted files

| File | Contents |
|---|---|
| `terraform/secrets.enc.yaml` | All infrastructure credentials |

## Local usage

### Decrypt for inspection
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops --decrypt terraform/secrets.enc.yaml
```

### Edit an encrypted file (re-encrypts on save)
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops terraform/secrets.enc.yaml
```

### Add a new secret
1. Open the file with `sops terraform/secrets.enc.yaml`
2. Add the key/value in your `$EDITOR`
3. Save — sops re-encrypts automatically
4. Commit the updated `.enc.yaml`
5. Add the variable name to `populate-bitwarden.sh` and `sync-secrets.sh`

## Key management

The age private key lives at `~/.config/sops/age/keys.txt` and is backed up in Bitwarden
as **"proxmox-homelab age private key"**.

The public key is committed in `.sops.yaml`. The private key is **never committed**.

### Key rotation
```bash
# Generate new key
age-keygen -o ~/.config/sops/age/keys-new.txt

# Update .sops.yaml with new public key, then re-encrypt all .enc.yaml files:
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops updatekeys terraform/secrets.enc.yaml

# Store new private key in Bitwarden, update SOPS_AGE_KEY GitHub secret
gh secret set SOPS_AGE_KEY < ~/.config/sops/age/keys-new.txt
```

## CI

The `sops-decrypt-check` job in `validate.yml` verifies decryption succeeds on every push.
It uses the `SOPS_AGE_KEY` GitHub Actions secret (set via `gh secret set SOPS_AGE_KEY`).

Output goes to `/dev/null` — the job confirms decryption works without exposing values in logs.

## Naming conventions

Encrypted files use the `.enc.yaml` or `.enc.env` suffix.
Decrypted working copies (never committed) use `.dec.yaml` or `.dec.env` — both are gitignored.
