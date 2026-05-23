# Handback 16: Harbor Bitwarden Removal

**Branch:** `work/productionize-06-canary-validation`
**Date:** 2026-05-23

---

## What active Bitwarden behavior was removed

The `harbor_postconfigure` Ansible role previously attempted to persist the
newly-created CI robot account secret into Bitwarden automatically when the
robot account was first created. This consisted of:

1. **Check task** — ran `bw status` to detect whether the Bitwarden CLI was
   present and the vault was unlocked.
2. **Save task** — if the check passed, used `jq` + `bw encode | bw create/edit`
   to upsert an item named "Harbor CI Robot" into a hard-coded Bitwarden
   organisation/collection.
3. **Confirm task** — printed a success message when the save succeeded.
4. **Fallback warn task** — printed the credentials in plain text to the
   Ansible output when the Bitwarden CLI was unavailable or the vault was locked.
5. **"Already exists" message** — when the robot already existed, stated
   "credentials are in Bitwarden".

Three Bitwarden-specific default variables were also present in `defaults/main.yml`:
- `harbor_postconfigure_bw_org_id`
- `harbor_postconfigure_bw_collection_id`
- `harbor_postconfigure_bw_item_name`

---

## What replacement workflow was chosen

**Manual capture with a mandatory operator warning.**

When the CI robot account is first created, the play now prints a single
prominent `debug` block containing the robot name and secret, with explicit
instructions for the operator to store the values in SOPS immediately:

```
================================================================
ACTION REQUIRED: Harbor CI robot account created.
Copy these credentials and store them in terraform/secrets.enc.yaml
(and terraform/secrets.pve.enc.yaml for production) under the keys:
  HARBOR_ROBOT_USER  = robot$ci-runner
  HARBOR_ROBOT_PASSWORD = <secret shown below>
Secret: <robot_secret>
This is the only time the secret is shown. It cannot be retrieved later.
================================================================
```

When the robot already exists the message states:
> "CI robot account 'robot$ci-runner' already exists. Credentials were
> captured at initial creation and stored in SOPS."

**Rationale for this path:**
- Lowest friction; no external dependency on CLI tooling at play time.
- Consistent with the current SOPS-centred model: all operational secrets live
  in `terraform/secrets.enc.yaml` / `terraform/secrets.pve.enc.yaml`.
- The fallback (credentials printed to screen when Bitwarden was unavailable)
  was already the effective behaviour in most run contexts; this makes it the
  primary and only path.
- Avoids introducing a SOPS write step inside Ansible, which would require AGE
  key injection into the playbook environment and add fragile tool coupling.

---

## What operator action is now required when a robot is created or rotated

1. Run `harbor_postconfigure` (via the stack provision playbook).
2. When the play reaches "Display new robot credentials", copy the printed
   `HARBOR_ROBOT_USER` and secret value from the Ansible output.
3. Store them in SOPS:
   ```
   SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml
   # add / update:  HARBOR_ROBOT_USER and HARBOR_ROBOT_PASSWORD
   ```
   For production:
   ```
   SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.pve.enc.yaml
   ```
4. If the robot needs to be rotated, delete it in Harbor UI first (the account
   name `robot$ci-runner` is idempotency-keyed — a fresh creation only happens
   when the account is absent).

---

## Files changed

| File | Change |
|---|---|
| `terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml` | Removed 4 Bitwarden tasks; replaced with single mandatory-capture debug task; fixed stale "credentials are in Bitwarden" message |
| `terraform/lxc/ansible/roles/harbor_postconfigure/defaults/main.yml` | Removed `harbor_postconfigure_bw_org_id`, `harbor_postconfigure_bw_collection_id`, `harbor_postconfigure_bw_item_name` defaults |
| `docs/productionize-refactor/evidence/harbor-canary-20260523-130537/README.md` | Updated note: changed "save secret to Bitwarden" to SOPS capture instruction |

---

## Validation run

No re-run was performed for this change. The robot-creation path only fires
when `robot$ci-runner` is absent; the production canary already created the
account. To validate:

1. On next robot rotation: delete the robot in Harbor, re-run provision, confirm
   the new debug output block appears and contains the secret.
2. Confirm no `bw` binary invocation occurs during the play.

The non-Bitwarden portions of the play are unchanged and were validated in the
Harbor canary run documented at
`docs/productionize-refactor/evidence/harbor-canary-20260523-130537/`.

---

## Stale Bitwarden references intentionally left in place

| Location | Reference | Reason left |
|---|---|---|
| `docs/productionize-refactor/evidence/harbor-canary-20260523-130537/31-provision-live.txt` | 4 task-name lines referencing old Bitwarden task names | Raw evidence log of the actual canary run prior to this change; modifying it would corrupt the historical record |
| `with-secrets`, `with-secrets-prod` | Bitwarden referenced only as recovery location for the age private key | Intentional; this is acceptable per project scope rules |
| Various older docs (`_legacy/`, historical session notes) | Historical Bitwarden references | Out of scope for this task; not live runtime behaviour |
