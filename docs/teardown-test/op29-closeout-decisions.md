# OP-29 Closeout Decisions

**Status:** Pending explicit approval

## Certificate Drift Follow-up

During OP-06..OP-28 execution, the following certificate changed:

- **File:** `certs/homelab-root.crt`
- **Status:** Modified (unstaged)
- **Trigger:** step-ca rebuild/re-export during teardown-test cycle

### Decisions Required

1. **Should the repo track the public lab root certificate?**
   - Option A: Commit `certs/homelab-root.crt` as the canonical lab root CA public cert
   - Option B: Add to `.gitignore` and manage outside Git
   - Option C: Keep unstaged; manually sync before deployments

2. **Should step-ca authority material persist across teardown/rebuild?**
   - Option A: Back up step-ca keys/config before destroy; restore post-rebuild to maintain continuity
   - Option B: Let step-ca rotate authority on each rebuild (impacts issued certs issued under old CA)
   - Option C: Pin step-ca to specific authority key via Terraform var

### Constraint

- Do **not** merge cert drift without explicit decision documented above
- Current state: cert unstaged, awaiting approval

### Recommended Path

1. Restore `certs/homelab-root.crt` to last-known-good state (before step-ca changes)
2. Decide on cert persistence strategy for future cycles
3. Document in step-ca stack Terraform whether CA material is ephemeral or persistent
4. Update `.gitignore` or `.git/info/exclude` if certificate is not meant to be tracked

---

**Created:** 2026-04-21
**Related:** OP-06..OP-28 execution, step-ca-stack teardown/rebuild

## 2026-04-22 Cycle Update (Stamp 20260422-044416)

### Verified Current State

- Branch: docs/teardown-test-execution-variables
- SDN safety fix present at HEAD: `23dea28` (`fix(sdn): guard subnet delete behind safe vnet gate`)
- OP-28 final validation: passed
- `certs/homelab-root.crt` remains modified and unstaged

### Additional Follow-ups Captured

1. Reconciler default Authentik URL behavior
   - Default URL path still fails discovery with HTTP 404 in OP-25 flows.
   - Direct URL `http://10.57.1.10:9000` works for apply/dry-run.
   - Recommendation: change reconciler default for rehearsal contexts or require explicit `--authentik-url` in runbook commands.

2. Portainer final validation probe
   - Initial OP-28 direct probe targeted wrong port and produced false failure.
   - Correct target is Portainer API on port 9000.
   - Recommendation: update runbook validation script/snippet to lock `http://10.57.1.20:9000/api/system/status`.

### Recommended Decision For Root Cert Drift

- Preferred: Track the new public root cert in git when and only when operator confirms step-ca rotation is intended for this cycle.
- If rotation was not intended, restore file to previous committed version and document non-persistent CA behavior as a defect.
- Until explicit approval: keep `certs/homelab-root.crt` unstaged.
