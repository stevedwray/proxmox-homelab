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
