# Secrets Management

## Overview

Secret **values** live in OpenBao, not in Git. Git holds only references
(`secrets/manifest.json`), OpenBao's policies and auth configuration, and
the automation around it. Design and rationale:
`docs/secrets-refactor/secrets-design.md`. How it was built:
`docs/secrets-refactor/plan.md`.

| Tier | What goes here | Where | Committed? |
| --- | --- | --- | --- |
| Non-secret config | Hostnames, node names, IP addresses, usernames, workspace names | `.env`, `.env.<node>` | See the note in `docs/framework-integration/decisions.md` Decision 6 |
| Secret references | Which KV entries and fields each environment needs | `secrets/manifest.json` | Yes (names only, never values) |
| Secret values | Passwords, tokens, API keys | OpenBao KV v2 at `kv/` on `openbao-stack` (`https://192.168.20.16:8200`) | No |

A `git checkout`, `merge`, `rebase` or `reset` cannot change a secret value.
A branch can change only *which* entries and fields it reads.

## Using secrets

```bash
./with-secrets tofu plan                         # dev environments (PVE_ENV, default pve-test-vm)
./with-secrets-prod terragrunt plan ...           # production node pve (same for -tiny, -framework)
```

The wrappers load `.env`, then `.env.<PVE_ENV>`, then log in to OpenBao with
the **read-only** deploy AppRole for that environment and export every field
the manifest lists for its profile (`scripts/secrets_env.py`). Host entries
(`hosts/<node>`) are applied last and override shared ones, exactly as the old
per-node SOPS files did. The wrapper **fails closed**: if any listed field is
missing or empty, the command does not run.

Workstation credentials (the "secret zero", replacing the age key):
`~/.config/openbao/<role>.role-id` and `<role>.secret-id`, mode 0600, one pair
per role (`deploy-dev`, `deploy-pve`, `deploy-pve-tiny`, ...), backed up in
Bitwarden. Deploy identities can read but never write.

## KV layout

One entry per service or host; **field names are the environment variable
names**, so `TF_VAR_*` naming is unchanged.

| Path | Scope |
| --- | --- |
| `kv/services/<service>` | Secrets whose identity comes from a service (Harbor, Graylog, Authentik, ...) |
| `kv/hosts/<node>` | A node's own Proxmox API tokens and LXC root password |
| `kv/shared/platform` | Genuinely cross-cutting platform values (Cloudflare DNS token, node_exporter scrape credentials, break-glass password, default LXC password) |
| `kv/shared/external-apis` | Third-party API keys (OpenAI, Anthropic, NVD, ...) |
| `kv/shared/dev-tooling` | Workstation tooling tokens (Snyk, Sonar) |

`secrets/manifest.json` is the complete inventory: every entry, every field
it must contain, and one profile per environment.

## Adding or rotating a secret

Writes need a human, explicitly logged in -- never a deploy identity and
never a cached token:

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"   # Authentik, group homelab-admins
LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py services/graylog GRAYLOG_ROOT_PASSWORD GRAYLOG_ROOT_PASSWORD_SHA2
unset BAO_TOKEN
```

`openbao_write.py` prompts for each value, writes all named fields as one new
KV version, and then triggers a post-write snapshot on the OpenBao LXC.

For a **new** field, also add its name to the right entry in
`secrets/manifest.json` on your branch; the loader only exports listed fields.
Because values are not branch state, the value is visible to every branch
whose manifest lists it, and invisible to the rest.

Undo a bad value: `bao kv rollback -mount=kv -version=<n> <entry>` (KV v2 keeps
20 versions per entry).

## CI

`netbox-populate.yml` authenticates with GitHub's OIDC token
(`auth/jwt-github`, role `ci-netbox-populate`, bound to this repository, the
workflow file, and `refs/heads/main`) and loads the `ci-netbox-populate`
profile. No secret-store credential is stored in GitHub. Secrets are only
ever retrieved on the self-hosted runner.

## Backup and recovery

- Raft snapshots: after every write through `openbao_write.py`, plus nightly
  at 03:30, to the NAS (`/mnt/nas-backup/openbao-snapshots` on `pve`).
  Retention: design doc 27.0.1. Snapshot age is on the Grafana "OpenBao"
  dashboard; there is no alerting yet.
- Seal key: USB stick attached to `pve` (operational copy) plus an offline
  copy (USB B). A snapshot is useless without the seal key it was made under.
- Bootstrap kit (design doc 9.1): what is needed to rebuild OpenBao without
  OpenBao -- Bitwarden secure note "openbao bootstrap kit", and a
  passphrase-encrypted `kit.age` on USB B.

## History

Until the 2026 cutover, secrets were SOPS-encrypted YAML files in Git
(`terraform/secrets.common.enc.yaml` plus one per node). Checking out an old
branch could silently restore an old password, which caused real incidents.
Those files are frozen and then deleted; old copies remain in Git history and
are not authoritative.
