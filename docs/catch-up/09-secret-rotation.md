# 09 — Rotate the high-value secrets

**When:** following weeks, after plan 04 (SOPS fully retired) · **Effort:**
2–3 h, one secret per sitting · **Value:** Med-High
**Approval names:** `catchup-09-rotate-<secret>` (one per section below)

## Why

The pre-OpenBao values of every secret are still in Git history as SOPS
ciphertext, readable by anyone holding the age key. Rotating makes those
copies worthless. Once all of these are rotated, the age key can be retired
from Bitwarden (last section). Source: `docs/secrets-refactor/README.md`,
"Recommended follow-ups".

## How every rotation works

1. Change the credential **at its source** (the system that checks it).
2. Store the new value in OpenBao with an explicit human login (agents never
   write secrets):
   ```bash
   export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
   export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
   LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py <entry> <FIELD> [<FIELD> ...]
   unset BAO_TOKEN
   ```
   `openbao_write.py` prompts for each value, writes one KV version and takes
   a post-write snapshot.
3. Redeploy only the consumers that **bake** the value into a host at deploy
   time (listed per secret). Consumers that read it at run time from
   `./with-secrets*` pick it up on their next run.
4. Verify with the check listed.
5. **Rollback** for any step: `bao kv rollback -mount=kv -version=<previous> <entry>`,
   and revert the source change if it's reversible.

Order is lowest blast radius first. Do one section per sitting and write its
hand-back before starting the next.

## 1. Cloudflare DNS token — `shared/platform` → `CF_DNS_API_TOKEN`

- **Source:** Cloudflare dashboard → My Profile → API Tokens → the DNS-edit
  token used for ACME → **Roll**. The old token stops working immediately.
- **Baked into:** `proxy-stack` (Traefik env, `deploy-proxy-stack.yml:102`) and
  `pangolin-proxy` (`deploy-pangolin-proxy.yml:97`).
- **Redeploy** (Authentik/Traefik tier: this stack plus a sample of consumers):
  ```bash
  TASK_APPROVAL=catchup-09-rotate-cf-token ./with-secrets-prod scripts/provision.sh --stack proxy-stack
  TASK_APPROVAL=catchup-09-rotate-cf-token ./with-secrets-prod scripts/provision.sh --stack pangolin-proxy
  ```
- **Verify:** `for h in grafana authentik harbor; do curl -s -o /dev/null -w "$h %{http_code}\n" https://$h.lab.gibbsgreatly.xyz/; done`
  all answer. Traefik's log shows no ACME/DNS-01 errors
  (`ssh root@192.168.30.10 'docker logs traefik --since 10m 2>&1 | grep -iE "acme|cloudflare" | tail'`).
- **Risk:** only certificate renewal depends on it. Existing certificates stay
  valid for weeks, so a mistake here is low-impact if caught the same day.

## 2. MikroTik admin — `services/mikrotik` → `MIKROTIK_ADMIN_PASSWORD`

- **Source** (router CLI, logged in as that admin user; its name is in
  `./with-secrets-prod printenv MIKROTIK_ADMIN`):
  `/user set [find name="<MIKROTIK_ADMIN>"] password="<new>"`.
  **Keep the current session open until verify passes** (safe mode is fine
  too; see memory `reference_routeros_safe_mode`).
- **Baked into:** nothing. Only the `ansible/00-initial-setup/mikrotik-*.yml`
  playbooks read it, at run time.
- **Verify:**
  `./with-secrets-prod ansible-playbook ansible/00-initial-setup/mikrotik-firewall-torrent-lab-ui-lockdown.yml`
  (plan 01's playbook; after plan 01 it's idempotent: it reads, finds the rule
  and changes nothing) ends `failed=0`.

## 3. Harbor CI robot — `services/harbor` → `HARBOR_ROBOT_PASSWORD`

- **Source:** Harbor UI → Administration → Robot Accounts → the CI robot
  (name in `./with-secrets-prod printenv HARBOR_ROBOT_USER`) → **Refresh
  secret** → generate → copy.
- **Baked into:** nothing on hosts. The CI workflows (`security-scan.yml`,
  `signature-gate.yml`, `supply-chain-signing-proof.yml`) read it from OpenBao
  per run.
- **Verify:** `gh workflow run security-scan.yml --ref main && gh run watch`.
  The "Build image for scan" and "Signature Gate" jobs pass (they push to and
  pull from Harbor with the robot).

## 4. Harbor admin — `services/harbor` → `HARBOR_ADMIN_PASSWORD`

- **Source:** Harbor UI, logged in as `admin` → user menu → Change Password.
  If it goes wrong, memory `reference_harbor_local_password_reset` has the
  exact DB recovery procedure.
- **Baked into:**
  - `monitoring-stack`: `.env` `HARBOR_API_PASSWORD` for the Harbor findings
    exporter → **redeploy**.
  - `authentik`, `netbox`, `graylog`, `wazuh` and `opensearch` stacks: each
    deploy runs `docker login` to Harbor with this password, so
    `/root/.docker/config.json` on those hosts holds the old value. Running
    containers are unaffected. The next deploy of each re-logs in. Nothing to
    do now, but a manual `docker pull` on those hosts fails until then.
- **Redeploy:**
  `TASK_APPROVAL=catchup-09-rotate-harbor-admin ./with-secrets-prod scripts/provision.sh --stack monitoring-stack`
- **Verify:** log in to the Harbor UI as `admin` with the new password, and
  Grafana's "Harbor operations" and "Harbor CVE inventory" dashboards show
  fresh data after one exporter cycle.
- **Follow-up (plan 13):** those five hosts log in to Harbor as `admin`.
  A pull-only robot would be the right credential there.

## 5. Authentik superuser — split the LDAP password first

**Found 2026-09-28:** `AUTHENTIK_LDAP_SERVICE_PASSWORD` isn't in the manifest,
so both `deploy-authentik-stack.yml:56` and `deploy-graylog-stack.yml:92` fall
back to `AUTHENTIK_SUPERUSER_PASSWORD`. Authentik sets the LDAP service
account's password to it on every deploy (`:1072`), and Graylog stores it as
its LDAP bind password (`:616`, `:666`). Rotating the superuser password
alone would silently change Graylog's LDAP bind. So:

### 5a. Give the LDAP service account its own secret

Repo step first:

#### catchup-09-ldap-manifest-field

```yaml
id: catchup-09-ldap-manifest-field
title: Add AUTHENTIK_LDAP_SERVICE_PASSWORD to the services/authentik manifest entry
depends_on: []

change: |
  In secrets/manifest.json, in the "services/authentik" entry's "fields"
  list, insert the string "AUTHENTIK_LDAP_SERVICE_PASSWORD" as the first
  element, before "AUTHENTIK_POSTGRES_PASSWORD" (the list is alphabetical).
  Keep the file's one-entry-per-line formatting. Change nothing else.

scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: field-present
    cmd: >-
      python3 -c "import json;f=json.load(open('secrets/manifest.json'))['entries']['services/authentik']['fields'];assert f==sorted(f) and 'AUTHENTIK_LDAP_SERVICE_PASSWORD' in f and len(f)==7;print('ok')"
    expect: "prints ok"
    critical: true
```

Then, operator (approval `catchup-09-rotate-authentik-ldap`), in this order.
The loader fails closed on a manifest field that's missing from OpenBao, so
the value goes in **before** anything deploys from the branch with the
manifest change:

1. `openbao_write.py services/authentik AUTHENTIK_LDAP_SERVICE_PASSWORD`
   with a new random value (`openssl rand -base64 32`).
2. `./with-secrets-prod scripts/provision.sh --stack authentik-stack` (sets
   the LDAP service account to the new password).
3. `./with-secrets-prod scripts/provision.sh --stack graylog-stack` (stores
   the new bind password).
4. **Verify:** log in to Graylog with an Authentik (LDAP) user. Authentik's
   own login and a forwardAuth route (e.g. `https://radarr.lab.gibbsgreatly.xyz/`)
   still work.

Steps 2–3 are the Authentik/Traefik tier: a Graylog LDAP outage lasts from
step 2 until step 3 finishes, so run them back to back.

### 5b. Rotate the superuser password and API token

- **Source:** Authentik admin → Directory → Users → the superuser (name in
  `./with-secrets-prod printenv AUTHENTIK_SUPERUSER`) → Set password. Then
  Directory → Tokens and App passwords → the API token used by automation →
  Delete, and create a new non-expiring API token for the same user.
- **Store:** `openbao_write.py services/authentik AUTHENTIK_SUPERUSER_PASSWORD AUTHENTIK_SUPERUSER_API_TOKEN`
  (one version, both together).
- **Baked into:** `authentik-stack`'s `.env` (`AUTHENTIK_BOOTSTRAP_PASSWORD`,
  only read on first boot, so changing it does nothing to a running instance).
  The API token is read at run time by `scripts/provision.sh` edge reconcile,
  `reconcile-authentik-edge.py` and the monitoring playbook's Grafana
  reconcile.
- **Redeploy:** `authentik-stack` only, to keep its `.env` in sync (approval
  `catchup-09-rotate-authentik-superuser`).
- **Verify:** `./with-secrets-prod python3 terraform/lxc/reconcile-edge.py`
  (dry run; no `--apply`) completes without an auth error, and
  `https://authentik.lab.gibbsgreatly.xyz/-/health/live/` answers.

## 6. Proxmox API tokens — `hosts/<node>`

Per node, one sitting each: `pve`, then `pve-tiny`, then `pve-framework`.
The token ID (`user@realm!name`) is in `TF_VAR_pm_api_token_id`: in `.env.pve`
for pve, and in OpenBao `hosts/<node>` for pve-tiny and pve-framework.

- **Before (read-only), on the node:**
  ```bash
  ./with-secrets-prod printenv TF_VAR_pm_api_token_id PROXMOX_READONLY_TOKEN_ID
  ssh root@pve.gibbsgreatly.xyz 'pveum user token list <user> --output-format json-pretty; pveum acl list --output-format json-pretty | grep -B2 -A4 "<user>"'
  ```
  Record each token's `privsep` flag and any ACL entries on the token itself.
- **Deploy token** (`TF_VAR_pm_api_token_secret`): regenerate with the same ID
  so no config outside OpenBao changes. Do it outside 02:30–03:00 UTC, when the
  CI populate job runs:
  ```bash
  TASK_APPROVAL=catchup-09-rotate-proxmox-pve ssh root@pve.gibbsgreatly.xyz 'pveum user token remove <user> <name> && pveum user token add <user> <name> --privsep <same as before> --output-format json'
  ```
  Copy `value` into `openbao_write.py hosts/pve TF_VAR_pm_api_token_secret`
  immediately. If the token had its own ACL entries, re-add them exactly as
  recorded (`pveum acl modify <path> --tokens '<user>!<name>' --roles <role>`).
- **Read-only token** (`PROXMOX_READONLY_TOKEN_SECRET`, pve only): same
  procedure. It is privilege-separated, so its ACL (read-only role) **must** be
  re-added after `token add`.
- **Baked into:** `netbox-stack` (`.env` `PROXMOX_READONLY_TOKEN_SECRET`,
  `deploy-netbox-stack.yml:458`) → redeploy netbox-stack after the read-only
  token changes. CI `netbox-populate` reads it at run time.
- **Verify:** a read-only plan authenticates with the new deploy token
  (`cd terraform/lxc/environments/pve/apt-cacher-stack && ../../../../../with-secrets-prod terragrunt plan -lock=false`
  reaches "Plan:" or "No changes"), and the next `netbox-populate` run
  (read-only token) succeeds.

## 7. Retire the age key

After sections 1–6 have hand-backs, and plan 04 has deleted `SOPS_AGE_KEY`
from GitHub: delete the age private key from Bitwarden, and from any
workstation path (`~/.config/sops/age/keys.txt`). Old SOPS ciphertext in Git
then can't be decrypted by anyone, and every value in it has been rotated
anyway.

Not in this plan (lower value, same procedure when wanted): Portainer token,
Grafana admin/OAuth secrets, Graylog root, NetBox tokens, PBS root@pam
password (plan 03 stores it in pve-tiny's storage config).
