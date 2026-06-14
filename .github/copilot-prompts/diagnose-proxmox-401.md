# Copilot Task: Diagnose Proxmox API 401 on netbox-populate service

**Model:** GPT-4o mini
**Output:** Write your findings to `artifacts/proxmox-401-diagnosis.md` and stop. Do not fix anything.

---

## Context

This is a Proxmox homelab repository. A systemd service called `netbox-populate`
runs inside a NetBox LXC container at `192.168.40.12` and populates NetBox with
live Proxmox topology by calling the Proxmox REST API.

The service is currently failing with:

```
RuntimeError: GET /nodes → 401:
urllib.error.HTTPError: HTTP Error 401: Authentication failed!
```

The service talks to `https://pve-test.gibbsgreatly.xyz:8006` (the dev Proxmox node).

The token written to `/etc/netbox-populate/env` on the LXC is:
- `PROXMOX_READONLY_TOKEN_ID=automation@pve!terraform`
- `PROXMOX_READONLY_TOKEN_SECRET=<redacted>`

A direct curl test of this token against the Proxmox API returned HTTP 401,
confirming the token is rejected by the host — it either does not exist, has
been regenerated, or belongs to the wrong realm.

---

## Your task

Investigate the credential chain and identify the root cause. **Read only —
do not modify any files or run any commands that change state.**

### Files to read

1. `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`
   — Focus on the `proxmox_token_id` and `proxmox_token_secret` Ansible vars
     (look for `PROXMOX_READONLY_TOKEN_ID` fallback chain, ~line 359).

2. `terraform/secrets.enc.yaml`
   — List every key name that contains `PROXMOX` or `pm_api_token`. Do not
     attempt to decrypt values. SOPS-encrypted values look like `ENC[AES256_GCM,...]`.
     Just report the key names present.

3. `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py`
   — Show how the token ID and secret are read from environment variables and
     assembled into the `Authorization` header format the Proxmox API expects.

4. `terraform/lxc/network/pve-test.yaml`
   — Note the `proxmox_host` value so we know exactly which node is targeted.

### Questions to answer

1. **Token ID source:** The playbook resolves `proxmox_token_id` from a
   three-level fallback: `PROXMOX_READONLY_TOKEN_ID` → `PROXMOX_TOKEN_ID` →
   `TF_VAR_pm_api_token_id`. Which of these keys actually exist in
   `terraform/secrets.enc.yaml`? Which one is being used at provision time?

2. **Token format:** Proxmox API tokens use the format
   `<user>@<realm>!<tokenname>=<secret>`. The token ID in the env file is
   `automation@pve!terraform`. Is `pve` the correct realm for this user, or
   should it be `pam`? Check `proxmox_client.py` for how the header is built.

3. **Secret key mismatch:** The secrets file has `PROXMOX_READONLY_TOKEN_SECRET`.
   Does it also have `PROXMOX_READONLY_TOKEN_ID`? If not, which key is supplying
   the token ID that ends up as `automation@pve!terraform`?

4. **Likely root cause:** Given the above, state your best hypothesis for why
   the 401 is occurring. Possible causes include:
   - Token was regenerated on the Proxmox node and the secret in the secrets
     file is stale
   - Token ID is sourced from `TF_VAR_pm_api_token_id` (the Terraform admin
     token) rather than a dedicated read-only token, and that token may have
     different permissions or have been rotated
   - Wrong realm (`pve` vs `pam`) in the token user part

---

## Output format

Write `artifacts/proxmox-401-diagnosis.md` with exactly these sections:

```markdown
# Proxmox 401 Diagnosis

## Key names found in secrets.enc.yaml
(list each PROXMOX / pm_api_token key name)

## Token ID resolution at provision time
(which fallback env var wins, and what value it produces)

## proxmox_client.py Authorization header assembly
(quote the relevant lines, confirm header format)

## Root cause hypothesis
(your best explanation, ranked if multiple are plausible)

## Recommended operator action
(concrete next steps — e.g. "regenerate the token on the Proxmox node and
re-encrypt the secret in secrets.enc.yaml", or "add PROXMOX_READONLY_TOKEN_ID
as a dedicated key in secrets.enc.yaml")

## Open questions for Claude Code review
(anything you could not determine from static analysis alone)
```

Do not modify any files other than creating `artifacts/proxmox-401-diagnosis.md`.
