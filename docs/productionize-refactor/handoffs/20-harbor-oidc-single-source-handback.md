# Harbor OIDC Single-Source Handback

Date: 2026-05-23
Branch: work/productionize-06-canary-validation

## Executive Summary

`HARBOR_OIDC_PRIMARY_AUTH_MODE` is now single-sourced to `.env.pve` for the pve
environment. The redundant definition in `terraform/secrets.pve.enc.yaml` has been
removed. The Harbor playbook reads this value correctly through the full
`with-secrets-prod` execution chain.

The Harbor runtime ambiguity that was blocking the next advisory pve teardown-planner
run is resolved.

---

## Previous Dual-Source Condition

### What existed

| Source | Value | Load order in with-secrets-prod |
|--------|-------|----------------------------------|
| `.env.pve` line 59 | `export HARBOR_OIDC_PRIMARY_AUTH_MODE=true` | Loaded first (shell `source`) |
| `terraform/secrets.pve.enc.yaml` line 35 | `HARBOR_OIDC_PRIMARY_AUTH_MODE: ENC[...]` (decrypts to `true`) | Loaded second via `sops exec-env` |

### Why SOPS won (not `.env.pve`)

`with-secrets-prod` loads secrets in this order:

1. Sources `.env.pve` via `source "${PROD_ENV_FILE}"` — sets vars in current shell
2. Runs `exec sops exec-env terraform/secrets.pve.enc.yaml <command>` — injects
   decrypted SOPS values into the child process environment

`sops exec-env` injects its key-value pairs as env vars for the subprocess. When
a key exists in both the inherited shell environment (from step 1) and the SOPS file
(step 2), the SOPS value **wins** because `sops exec-env` overwrites the inherited
env var. This was confirmed by test:

```bash
# Setting OVERRIDDEN in the shell env before sops exec-env:
HARBOR_OIDC_PRIMARY_AUTH_MODE=OVERRIDDEN \
  SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  sops exec-env terraform/secrets.pve.enc.yaml \
    'bash -c "echo $HARBOR_OIDC_PRIMARY_AUTH_MODE"'
# Output: true   (SOPS overrode OVERRIDDEN)
```

**Consequence:** Handback 19 documented `.env.pve` as the canonical source, but in
practice SOPS was the de facto source. Both values happened to be `true`, so Harbor
behavior was unaffected. However, the canonical ownership claim in the documentation
was incorrect.

---

## Single Source Chosen: `.env.pve`

**Rationale:**

- `HARBOR_OIDC_PRIMARY_AUTH_MODE` is a non-secret boolean feature flag (`true`/`false`)
- Non-secret runtime tuning belongs in the tracked env overlay, not SOPS
- `.env.pve` is already the single source for all other Harbor OIDC settings
  (endpoint, client ID, groups claim, scope, etc.)
- Keeping it in SOPS requires maintaining encryption overhead for a non-sensitive value
- pve-test reference model (`HARBOR_OIDC_PRIMARY_AUTH_MODE=true` in `.env` and
  `secrets.enc.yaml`) uses the same value; `.env.pve` parity is correct

---

## Implementation

### What was removed

**`terraform/secrets.pve.enc.yaml`**: Removed the `HARBOR_OIDC_PRIMARY_AUTH_MODE`
entry entirely using SOPS editor:

```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
  EDITOR="sed -i '/^HARBOR_OIDC_PRIMARY_AUTH_MODE:/d'" \
  sops terraform/secrets.pve.enc.yaml
```

After this change, the key no longer appears in `terraform/secrets.pve.enc.yaml`.
The SOPS file was re-encrypted automatically by SOPS on write.

### What remains unchanged

**`.env.pve` line 59:**

```bash
export HARBOR_OIDC_PRIMARY_AUTH_MODE=true
```

This line is unchanged and is now the single authoritative source.

---

## Files Changed

| File | Change |
|------|--------|
| `terraform/secrets.pve.enc.yaml` | Removed `HARBOR_OIDC_PRIMARY_AUTH_MODE` entry |
| `.env.pve` | **Unchanged** — existing entry is now the single source |
| `.env.pve-test` | **Unchanged** — not applicable to pve resolution |
| `.env` | **Unchanged** — pve-test reference model, not pve |

### Parallel issue in pve-test (out of scope)

`terraform/secrets.enc.yaml` (pve-test SOPS file) also contains
`HARBOR_OIDC_PRIMARY_AUTH_MODE` alongside the `.env` definition. This is the same
dual-source pattern in the pve-test environment. It is intentionally **out of scope**
for this handback — the task is scoped to pve only.

---

## Validation Run

### 1. Confirm removal from SOPS

```bash
grep -n "HARBOR_OIDC_PRIMARY_AUTH_MODE" terraform/secrets.pve.enc.yaml
# Output: (no matches — key removed)
```

### 2. Confirm SOPS no longer injects the key (clean env test)

```bash
env -i HOME=$HOME SOPS_AGE_KEY_FILE=$HOME/.config/sops/age/keys.txt PATH=$PATH \
  sops exec-env terraform/secrets.pve.enc.yaml \
    'bash -c "echo FROM_SOPS=${HARBOR_OIDC_PRIMARY_AUTH_MODE:-UNSET}"'
# Output: FROM_SOPS=UNSET
```

### 3. Confirm full with-secrets-prod chain delivers value from .env.pve

```bash
env -i HOME=$HOME PATH=$PATH SOPS_AGE_KEY_FILE=$HOME/.config/sops/age/keys.txt \
  bash -c 'source .env.pve && sops exec-env terraform/secrets.pve.enc.yaml \
    "bash -c \"echo HARBOR_OIDC_PRIMARY_AUTH_MODE=\${HARBOR_OIDC_PRIMARY_AUTH_MODE:-UNSET}\""'
# Output: HARBOR_OIDC_PRIMARY_AUTH_MODE=true
```

All three tests passed. `.env.pve` is now the single authoritative source and the
Harbor playbook will receive the correct value through the `with-secrets-prod` chain.

---

## Resolution Status

| Item | Previous State | Resolved State |
|------|----------------|----------------|
| Canonical source | Ambiguous (docs said `.env.pve`, de facto was SOPS) | `.env.pve` — confirmed sole source |
| SOPS entry | Present (encrypted, decrypts to `true`) | **Removed** |
| `.env.pve` entry | Present (but overridden by SOPS at runtime) | Present and now effective |
| Harbor runtime behavior on pve | `true` (from SOPS, correct by coincidence) | `true` (from `.env.pve`, correct by design) |

**Harbor runtime ambiguity for pve: fully resolved.**

---

## Teardown-Planner Readiness

The blocking item previously noted in handbacks 17, 18, and 19 is now resolved.
`HARBOR_OIDC_PRIMARY_AUTH_MODE` is no longer dual-sourced for pve.

The advisory pve teardown-planner run (`docs/productionize-refactor/15-pve-infra-only-teardown-planner.md`)
can now proceed with the Harbor runtime input surface fully deterministic.

### Remaining items before planner run (if any)

The following items from prior handbacks were already resolved:

- Grafana OAuth parity (`GRAFANA_OAUTH_SCOPES`, `GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH`) — resolved in handback 19
- Harbor OIDC primary-auth-mode single-source — **resolved in this handback**

No further Harbor-related runtime ambiguity is known. If additional items surface
during the planner run, treat them as new findings rather than continuations of this
scope.

---

## Predecessor Handbacks

- `17-pve-infra-input-parity-audit-handback.md` — first identified the dual-source
- `18-pve-teardown-preflight-clarifications-handback.md` — confirmed ambiguity still open
- `19-pve-runtime-parity-resolution-handback.md` — documented canonical ownership as
  `.env.pve` but deferred SOPS removal (incomplete); also incorrectly described
  `.env.pve` as the effective source (SOPS was actually winning at runtime)
