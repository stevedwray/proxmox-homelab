# 04 — Secrets refactor close-out

**When:** 2026-09-29, after the scheduled 02:40 UTC `netbox-populate` run ·
**Effort:** 15 min · **Value:** High (removes a live, now-unneeded credential)
**Production access:** GitHub only

## State on 2026-09-28

- #434 merged at 03:33 UTC 2026-09-28. Every `netbox-populate` run so far
  predates it: the 02:45 UTC run that day failed in the old workflow's
  "Install SOPS" step (`sudo: a password is required`). So **no run has yet
  used the new GitHub OIDC → OpenBao login on `main`** (plan step 15 of
  `docs/secrets-refactor/plan.md`).
- `.github/workflows/*.yml` on `main` no longer reference `SOPS_AGE_KEY`
  (`validate.yml`'s `sops-freeze` job is a file-freeze check, not a
  decryption step).
- The `SOPS_AGE_KEY` Actions secret still exists (created 2026-04-10).

## Operator steps

### 1. Check the first post-merge scheduled run

```bash
gh run list --workflow netbox-populate.yml --branch main --limit 3 --json databaseId,createdAt,conclusion,event
```

Take the newest run whose `createdAt` is after `2026-09-28T03:33:29Z`.

- `conclusion: success` → go to step 2.
- `failure` → `gh run view <id> --log-failed | tail -60`, record the
  failure in the hand-back, and stop. Don't delete the secret. The failure
  belongs to `docs/secrets-refactor/` (OIDC role `ci-netbox-populate`, bound
  to `main` only).
- No such run yet → trigger one (this is the job's normal daily action on
  NetBox, nothing extra): `gh workflow run netbox-populate.yml --ref main`,
  then `gh run watch`.

### 2. Confirm the success used OpenBao

```bash
gh run view <id> --log | grep -iE 'openbao|jwt|login|secrets_env' | head -20
```

Expect lines showing the OIDC/JWT login to OpenBao succeeding, and no SOPS
step at all.

### 3. Delete the secret

```bash
git grep -n SOPS_AGE_KEY origin/main -- .github || echo "no workflow references"
gh secret delete SOPS_AGE_KEY
gh secret list | grep -c SOPS_AGE_KEY   # expect 0
```

## Step (repo)

### catchup-04-secrets-readme-closeout

```yaml
id: catchup-04-secrets-readme-closeout
title: Mark the secrets refactor fully complete in its README
depends_on: []

change: |
  In docs/secrets-refactor/README.md, replace the whole numbered item that
  begins "2. **Promote `stable` → `main`** when the operator decides." (it
  runs until the line "   - Delete the `SOPS_AGE_KEY` GitHub Actions secret.")
  with this LITERAL text:

  2. ~~Promote `stable` → `main`~~ — done (PR #434, 2026-09-28). Plan step
     15's live test passed on the first scheduled `netbox-populate` run after
     the merge (GitHub OIDC → OpenBao, no SOPS), and the `SOPS_AGE_KEY`
     GitHub Actions secret was deleted. See docs/catch-up/README.md,
     hand-back for plan 04.

  Then, in docs/secrets-refactor/plan.md, replace exactly these two lines
  (lines 14-15):

  **Status: complete except plan step 15's live CI test, which waits on a
  `stable` → `main` promotion.** The full record, with every gate result, is

  with this LITERAL line (the rest of the paragraph stays as it is):

  **Status: complete.** Step 15's live CI test passed after the #434 merge (docs/catch-up/README.md, plan 04 hand-back). The full record, with every gate result, is

  Change nothing else in either file.

scope:
  allowed_paths:
    - docs/secrets-refactor/README.md
    - docs/secrets-refactor/plan.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any gh command"

gates:
  - id: status-complete
    cmd: "grep -c '^\\*\\*Status: complete\\.\\*\\* Step 15' docs/secrets-refactor/plan.md"
    expect: "prints 1"
    critical: true
  - id: promotion-struck
    cmd: "grep -c 'Promote `stable` → `main`~~ — done (PR #434' docs/secrets-refactor/README.md"
    expect: "prints 1"
    critical: true
```

Run this step only after operator step 3 succeeds.

## Done when

- A post-merge `netbox-populate` run on `main` succeeded through OpenBao.
- `SOPS_AGE_KEY` no longer exists.
- `catchup-04-secrets-readme-closeout` is done, and the memory note
  `project_secrets_refactor_openbao` says "complete".
