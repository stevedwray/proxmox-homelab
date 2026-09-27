# Secrets Management

## Overview

Secret **values** live in OpenBao, not in Git. Git holds only references
(`secrets/manifest.json`), OpenBao's policies and auth configuration, and
the automation around it. Design and rationale:
`docs/secrets-refactor/secrets-design.md`. How it was built, and every
finding along the way: `docs/secrets-refactor/README.md`.

| Tier | What goes here | Where | Committed? |
| --- | --- | --- | --- |
| Non-secret config | Hostnames, node names, IP addresses, usernames, workspace names | `.env`, `.env.<node>` | See the note in `docs/framework-integration/decisions.md` Decision 6 |
| Secret references | Which KV entries and fields each environment needs | `secrets/manifest.json` | Yes (names only, never values) |
| Secret values | Passwords, tokens, API keys | OpenBao KV v2 at `kv/` on `openbao-stack` | No |

A `git checkout`, `merge`, `rebase` or `reset` cannot change a secret value.
A branch can change only *which* entries and fields it reads.

## At a glance

| Thing | Where |
| --- | --- |
| OpenBao API (machines) | `https://192.168.20.16:8200` (`LAB_IP_OPENBAO`), CA `certs/homelab-root.crt`. Never through Traefik |
| OpenBao UI (humans) | `https://openbao.lab.gibbsgreatly.xyz/ui/` → Method **OIDC** → Authentik (group `homelab-admins`) |
| Container | LXC 20016 `openbao` on `pve`, `mgmt_seg`; OpenBao 2.7.0 native `.deb`; config `/etc/openbao/openbao.hcl` (managed by `deploy-openbao.yml`) |
| Config as code | `terraform/lxc/ansible/playbooks/configure-openbao.yml`; policies in `terraform/lxc/stacks/openbao-stack/policies/` |
| Audit log | `/var/log/openbao/audit.log` on the LXC (values are HMAC'd; logrotate 30 days) |
| Dashboard | Grafana → "OpenBao" |
| Seal key | USB A (ADATA, label `BAOSEAL`) plugged into `pve`, mounted read-only at `/mnt/openbao-seal`; offline copy on USB B (SanDisk, `BAOSEAL-B`), stored away from `pve` |
| Bootstrap kit | Bitwarden secure note "openbao bootstrap kit" plus passphrase-encrypted `kit.age` on USB B |

## Identities

| Identity | Who uses it | Can do | Where its credentials live |
| --- | --- | --- | --- |
| `deploy-dev` | `./with-secrets` (pve-test-vm, pve-test) | read `services/*`, `shared/*`, `hosts/pve-test-vm`, `hosts/pve-test` | `~/.config/openbao/deploy-dev.*` (0600) |
| `deploy-<node>` | `./with-secrets-prod*` (one per line of `terraform/PRODUCTION_NODES`) | read `services/*`, `shared/*`, own `hosts/<node>` | `~/.config/openbao/deploy-<node>.*` |
| `ci-netbox-populate` | GitHub Actions (`jwt-github`), `netbox-populate.yml` on `main` only | read mikrotik, netbox, portainer, `hosts/pve` | none stored (GitHub OIDC token) |
| `snapshot` | nightly and post-write snapshot job | `sys/storage/raft/snapshot` only | `/etc/openbao-snapshot/` on the LXC |
| `metrics` | dashboard inventory exporter | list+read `kv/metadata/*` only; never values | `/etc/openbao-metrics/` on the LXC |
| `breakglass` | operator, when Authentik is down | `sys/generate-root-token/*` only; still needs the recovery key | `~/.config/openbao/breakglass.*` and the bootstrap kit |
| OIDC `homelab-admin` | humans | `openbao-admin` (full), 1-hour tokens | Authentik |

Deploy identities never write, and agents only ever get deploy identities.
Back up `~/.config/openbao/` to Bitwarden ("openbao deploy approles").

## Using secrets

```bash
./with-secrets tofu plan                         # dev environments (PVE_ENV, default pve-test-vm)
./with-secrets-prod terragrunt plan ...           # production node pve (same for -tiny, -framework)
```

The wrappers load `.env`, then `.env.<PVE_ENV>`, then log in to OpenBao with
the **read-only** deploy AppRole for that environment and export every field
the manifest lists for its profile (`scripts/secrets_env.py`). Host entries
(`hosts/<node>`) are applied last and override shared ones. The wrapper
**fails closed**: if any listed field is missing or empty, the command does
not run. `python3 scripts/secrets_env.py --profile pve --check` reads
everything and prints only counts.

## KV layout

One entry per service or host; **field names are the environment variable
names**, so `TF_VAR_*` naming is unchanged.

| Path | Scope |
| --- | --- |
| `kv/services/<service>` | Secrets whose identity comes from a service (Harbor, Graylog, Authentik, ...) |
| `kv/hosts/<node>` | A node's own Proxmox API tokens and LXC root password |
| `kv/shared/platform` | Cross-cutting platform values (Cloudflare DNS token, node_exporter scrape credentials, break-glass password, default LXC password) |
| `kv/shared/external-apis` | Third-party API keys (OpenAI, Anthropic, NVD, ...) |
| `kv/shared/dev-tooling` | Workstation tooling tokens (Snyk, Sonar) |
| `kv/services/legacy-unused` | Imported keys with no consumer in the repo (review for deletion) |

`secrets/manifest.json` is the complete inventory: every entry, every field
it must contain, and one profile per environment.

## Adding or rotating a secret

Writes need a human, explicitly logged in: never a deploy identity and
never a cached token.

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"   # Authentik, group homelab-admins
LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py services/graylog GRAYLOG_ROOT_PASSWORD GRAYLOG_ROOT_PASSWORD_SHA2
unset BAO_TOKEN
```

`openbao_write.py` prompts for each value, writes all named fields as one new
KV version (check-and-set), and then triggers a post-write snapshot on the
OpenBao LXC. It exits non-zero with "WRITE OK, SNAPSHOT FAILED" if the
snapshot fails.

For a **new** field, also add its name to the right entry in
`secrets/manifest.json` on your branch; the loader only exports listed
fields. The value is visible to every branch whose manifest lists it, and
invisible to the rest. For a **new entry**, add it to `entries` and to each
profile that needs it. The dashboard's drift panel shows any entry that is
in the manifest but missing from OpenBao, or the reverse.

Undo a bad value: `bao kv rollback -mount=kv -version=<n> <entry>` (KV v2 keeps
20 versions per entry). `bao kv metadata get -mount=kv <entry>` shows the
version history without values.

## Adding a production node

1. Add the node to `terraform/PRODUCTION_NODES` and create `.env.<node>`.
2. Add a `hosts/<node>` entry and a `<node>` profile to
   `secrets/manifest.json`, and a `./with-secrets-prod-<node>` wrapper
   (a copy of `with-secrets-prod-tiny` with `PVE_PROD_NODE` changed).
3. Re-run `configure-openbao.yml`, which generates `deploy-host-<node>` and
   the `deploy-<node>` AppRole from `PRODUCTION_NODES`. Then issue its
   credentials:

   ```bash
   bao read -field=role_id auth/approle/role/deploy-<node>/role-id | install -m 0600 /dev/stdin ~/.config/openbao/deploy-<node>.role-id
   bao write -f -field=secret_id auth/approle/role/deploy-<node>/secret-id | install -m 0600 /dev/stdin ~/.config/openbao/deploy-<node>.secret-id
   ```

4. Write the node's tokens with `openbao_write.py hosts/<node> ...`.

## Changing OpenBao's own configuration

Edit `configure-openbao.yml` or `openbao-stack/policies/*.hcl`, then:

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
TASK_APPROVAL=<task> ./with-secrets-prod ansible-playbook terraform/lxc/ansible/playbooks/configure-openbao.yml
unset BAO_TOKEN
```

The playbook is idempotent and never creates SecretIDs. Server settings
(listener, seal, the **audit device**) are in `openbao.hcl`, which
`deploy-openbao.yml` writes. OpenBao 2.x refuses audit devices created
through the API.

## CI

`netbox-populate.yml` authenticates with GitHub's OIDC token
(`auth/jwt-github`, role `ci-netbox-populate`, bound to this repository, the
workflow file and `refs/heads/main`) and loads the `ci-netbox-populate`
profile. No secret-store credential is stored in GitHub; secrets are only
ever retrieved on the self-hosted runner. **This goes live when `stable` is
promoted to `main`**; until then `main` still carries the old SOPS-based
workflow, which fails.

## USB seal key operations

- **Normal:** USB A stays plugged into `pve`. OpenBao reads the key only at
  start and auto-unseals unattended after any LXC restart or `pve` reboot.
- **After unplugging or replugging USB A**, even briefly: the host mount
  and the LXC bind mount go stale. OpenBao keeps running, but the next
  restart would stay sealed. Fix on `pve`:
  `mount /mnt/openbao-seal && pct reboot 20016`, then check
  `curl -s --cacert certs/homelab-root.crt https://192.168.20.16:8200/v1/sys/health`
  shows `"sealed":false`.
- **USB A missing at boot:** `pve` still boots (the fstab entry is
  `nofail`); `openbao.service` fails and stays sealed until the key is back.
- **Key rotation** (only if a stick is lost or compromised): add a new key
  as `current_key` and the old one as `previous_key` in the `seal "static"`
  block (see OpenBao's static seal docs). Restart, confirm it unseals, then
  write the new key to both sticks. Keep the old key until every snapshot
  made under it has aged out (12 months).

## Break-glass (Authentik unavailable)

Deploy reads don't depend on Authentik, so redeploying Authentik works
normally. Break-glass is only for administrative changes to OpenBao itself
while OIDC is down:

```bash
bash scripts/openbao-breakglass-test.sh
```

That is the tested drill: breakglass AppRole login → generate-root with the
recovery key → root token. As written, it verifies the token and revokes
it. For real use, run the same steps but make the change before revoking.
Recovery key and breakglass credentials: the bootstrap kit.

## Backup and recovery

- **Raft snapshots:** after every write through `openbao_write.py`, plus
  nightly at 03:30, to the NAS (`/mnt/nas-backup/openbao-snapshots` on
  `pve`). Retention: 90 days post-write / 14 daily / 8 weekly / 12 monthly,
  never fewer than the newest 7. Manual:
  `ssh root@192.168.20.16 systemctl start openbao-snapshot@postwrite.service`.
- **A snapshot is useless without its seal key**, which is on USB B, so
  snapshots can go to ordinary storage. Never store USB B with them.
- **Recovery drill** (proves snapshot + USB B + recovery key are enough, on
  a throwaway, network-less LXC): plug USB B into `pve`, then
  `bash scripts/openbao-recovery-test.sh`. It passed on 2026-09-28. Re-run
  it after any change to the seal, the backup job, or OpenBao's major
  version.
- **Real rebuild of `openbao-stack`:**
  1. Load the bootstrap kit into a shell only:
     `set -a; source .env; source .env.pve; source <(age -d kit.age); set +a`.
  2. Recreate the LXC and run the playbook with `terragrunt apply` +
     `scripts/provision.sh --stack openbao-stack` directly (not via the
     wrappers, which need OpenBao).
  3. Redo the bind mounts (`pct set 20016 -mp0 ... -mp1 ...`, see
     `STACK_CONTRACT.md` and `stack.yaml` `host_bind_mounts`).
  4. With USB B's key in place, start OpenBao, `bao operator init`, then
     `bao operator raft snapshot restore -force <newest.snap>`. The restored
     data auto-unseals.
  5. Get a root token with the breakglass AppRole and the kit's recovery key.

## Monitoring

Grafana → "OpenBao":

- snapshot age and last run, and whether the LXC is up;
- secret **entries and fields per category**;
- a per-entry table of version and last-changed;
- changes in the last 7 days;
- manifest-vs-OpenBao drift.

The inventory comes from the `metrics` identity, which can read KV metadata
only; its attempts to read values are denied (verified in the audit log).
**There is no alerting yet.** Watch the snapshot age (should be under 26 h)
and drift (should be 0).

## Checking everything still works

- `python3 scripts/secrets_env.py --profile <env> --check` for each
  environment: every field present.
- `LAB_IP_OPENBAO=192.168.20.16 python3 scripts/openbao_boundary_check.py`:
  each deploy identity reads only its own scope and can't write.
- `TASK_APPROVAL=<task> bash scripts/secrets-check-sweep.sh`: `ansible --check`
  of every production stack through the wrappers. Nothing on any host is
  changed. It proves every playbook's secret lookups resolve and shows
  whether secret-bearing files would change.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `secrets_env: ERROR: missing or empty fields (fail closed): <entry>:<FIELD>` | Field listed in the manifest but not in OpenBao. Write it, or fix the manifest |
| `missing AppRole credentials for '<role>'` | `~/.config/openbao/<role>.*` absent. Restore it from Bitwarden |
| `OpenBao ... HTTP 403` from the wrapper | Profile/role mismatch, or the SecretID is bound to another CIDR (deploy roles accept only 192.168.1.0/24) |
| Health shows `"sealed":true` | Seal key not readable. See USB seal key operations |
| UI login: "callback ... did not supply all of the required parameters" | Authentik provider `grant_types` empty (reconciler create-time default). The openbao route is fixed; check `_oidc_grant_types` for new stacks |
| `generate-root` 403 | Expected without a token (OpenBao ≥ 2.5.3). Use the breakglass AppRole |

## History

Until the 2026-09 cutover, secrets were SOPS-encrypted YAML files in Git
(`terraform/secrets.common.enc.yaml` plus one per node). Checking out an old
branch could silently restore an old password, which caused real incidents.
Those files were frozen at the cutover, and then deleted after the recovery
test. Old copies remain in Git history and are not authoritative, but they
can be decrypted with the old age key, so rotate the high-value secrets
over time.
