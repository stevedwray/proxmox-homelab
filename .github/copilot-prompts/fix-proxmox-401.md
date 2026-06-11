# Copilot Task: Fix Proxmox API 401 for netbox-populate service

**Output:** Write `artifacts/proxmox-401-fix.md` as a handback when done.
**Scope:** Diagnose, fix, re-provision, verify. Do not stop to ask for input — work through
the full chain in one session, making reasonable decisions at each step.

---

## Background

`netbox-populate.service` runs inside the NetBox LXC at `192.168.40.12` and calls the
Proxmox REST API at `https://pve-test.gibbsgreatly.xyz:8006` to discover topology.
It is currently failing with `GET /nodes → 401: Authentication failed`.

Credentials are managed through `with-secrets`:
- `.env` and `.env.pve-test` hold **non-secret** config (hostnames, token IDs, node names)
- `terraform/secrets.enc.yaml` holds **SOPS-encrypted secrets** (token secrets, passwords)
- `with-secrets` loads both and injects them into the subprocess env; SOPS values override

The Ansible playbook (`deploy-netbox-stack.yml`) resolves the Proxmox token ID with this
fallback chain: `PROXMOX_READONLY_TOKEN_ID` → `PROXMOX_TOKEN_ID` → `TF_VAR_pm_api_token_id`.
The secret uses the same pattern with `_SECRET` suffixes.

The previous diagnostic (see `artifacts/proxmox-401-diagnosis.md`) found that
`PROXMOX_READONLY_TOKEN_ID` is absent from `secrets.enc.yaml`, so the token ID is coming
from a fallback source. The 401 is most likely either an ID/secret mismatch (ID and secret
belong to different tokens) or a stale/rotated secret.

---

## Step 1 — Establish what credentials are currently resolved

Run this to see exactly what the playbook will use, without printing secret values:

```bash
./with-secrets env | grep -E "^PROXMOX_(READONLY_)?TOKEN_(ID|SECRET)|^TF_VAR_pm_api_token"
```

Note which variables are set and what the token ID value is. Do not log the secret value.

---

## Step 2 — Establish what tokens exist on pve-test

```bash
ssh root@pve-test.gibbsgreatly.xyz "pveum user token list automation@pve --output-format json"
```

Note: the `automation@pve` user is in the `pve` realm (PVE built-in auth), not `pam`.
Record which token names exist (e.g. `terraform`, `terraform-readonly`) and their
`expire` and `privsep` fields.

---

## Step 3 — Test the current resolved token directly

Construct the test using values from Step 1 (replace `<TOKEN_ID>` and `<TOKEN_SECRET>`
with what Step 1 revealed):

```bash
./with-secrets bash -c 'curl -sk -w "\nHTTP %{http_code}\n" \
  -H "Authorization: PVEAPIToken=${PROXMOX_READONLY_TOKEN_ID:-${PROXMOX_TOKEN_ID:-${TF_VAR_pm_api_token_id}}}=${PROXMOX_READONLY_TOKEN_SECRET:-${PROXMOX_TOKEN_SECRET:-${TF_VAR_pm_api_token_secret}}}" \
  "https://pve-test.gibbsgreatly.xyz:8006/api2/json/version"'
```

If this returns HTTP 200, the credential chain is already correct and the 401 is an env
file deployment issue — skip to Step 6. If it returns 401, continue to Step 4.

---

## Step 4 — Resolve the mismatch

Based on Steps 1–3, choose the correct path:

### Path A: Token exists on Proxmox but ID/secret are mismatched

If `automation@pve!terraform` exists in the token list (Step 2) but the curl test (Step 3)
still returns 401, the SOPS secret is stale. Regenerate it:

```bash
# Regenerate the token on the Proxmox node and capture the new secret
ssh root@pve-test.gibbsgreatly.xyz \
  "pveum user token remove automation@pve terraform && \
   pveum user token add automation@pve terraform --privsep 0 --output-format json"
```

Capture the `value` field from the JSON output — that is the new token secret.

Update the SOPS file with the new secret:
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops --set '["TF_VAR_pm_api_token_secret"] "PASTE_NEW_SECRET_HERE"' \
  terraform/secrets.enc.yaml
```

If `PROXMOX_READONLY_TOKEN_SECRET` is a separate key from `TF_VAR_pm_api_token_secret`,
update it too:
```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops --set '["PROXMOX_READONLY_TOKEN_SECRET"] "PASTE_NEW_SECRET_HERE"' \
  terraform/secrets.enc.yaml
```

### Path B: Token does not exist on Proxmox

If neither `terraform` nor `terraform-readonly` appears in the Step 2 token list,
the token has been deleted. Create a dedicated readonly token:

```bash
ssh root@pve-test.gibbsgreatly.xyz \
  "pveum user token add automation@pve terraform-readonly --privsep 0 --output-format json"
```

Capture the `value` field. Then:

1. Add the token ID to `.env.pve-test`:
   ```
   PROXMOX_READONLY_TOKEN_ID=automation@pve!terraform-readonly
   ```

2. Update SOPS with the secret:
   ```bash
   SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
     sops --set '["PROXMOX_READONLY_TOKEN_SECRET"] "PASTE_NEW_SECRET_HERE"' \
     terraform/secrets.enc.yaml
   ```

### Path C: PROXMOX_READONLY_TOKEN_ID is missing, token exists and secret is correct

If the curl test returns 200 but only because it fell back to `TF_VAR_pm_api_token_id`,
add an explicit `PROXMOX_READONLY_TOKEN_ID` entry to `.env.pve-test` pointing at whichever
token is intended for read-only discovery work, so the fallback chain is unambiguous.

---

## Step 5 — Verify the fix resolves before re-provisioning

Repeat the curl test from Step 3. It must return HTTP 200 before proceeding.

---

## Step 6 — Re-provision the netbox-stack

```bash
./with-secrets scripts/provision.sh --stack netbox-stack
```

This will redeploy the credential env file to the LXC with the corrected token values.

---

## Step 7 — Verify the service

```bash
ssh root@192.168.40.12 'systemctl start netbox-populate.service; sleep 5; \
  journalctl -u netbox-populate.service --no-pager -n 40'
```

Success criteria:
- No `IndexError` (already fixed in a prior commit)
- No `401: Authentication failed`
- Log shows `Using network intent: /etc/netbox-populate/network.yaml`
- Script progresses past `discover_from_proxmox()` (may still fail on later steps —
  that is out of scope for this task)

---

## Step 8 — Commit if files changed

If `.env.pve-test` or `terraform/secrets.enc.yaml` were modified, stage and commit:

```bash
git add .env.pve-test terraform/secrets.enc.yaml
git commit -m "fix(netbox-populate): align Proxmox API token ID and secret for pve-test

<one line describing what was mismatched and what was done>

Co-Authored-By: GitHub Copilot <noreply@github.com>"
```

---

## Handback document

Write `artifacts/proxmox-401-fix.md` with these sections:

```markdown
# Proxmox 401 Fix — Handback

## Resolved token ID and source
(which env var, which value — no secret values)

## Root cause confirmed
(what was actually wrong)

## Changes made
(files edited, tokens created/rotated, SOPS keys updated — no secret values)

## Provision result
(ok/changed/failed counts from ansible run)

## Service verification
(paste the last 15 lines of journalctl output)

## Commit
(sha and message, or "no files changed")

## Residual failures (if any)
(anything that failed beyond the 401 — note but do not fix)
```
