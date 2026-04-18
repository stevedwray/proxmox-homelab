# Secret Leak Remediation — `.env.pve-test`

**Date:** 2026-04-17
**Severity:** High (public repo, secrets now rotated)
**Status:** Resolved

## What happened

`.env.pve-test` was committed to the repository and appeared in git history across all branches, including `main`. The file contained credentials for the home lab test environment: Proxmox API token, service passwords, NetBox secrets, MikroTik router password, SonarCloud token, and Snyk token. The repo is public, so the file was visible in PR diffs.

Three PRs exposed the file contents:
- PR #122 — docs: align active repo docs with current pve-test workflow
- PR #130 — feat(01): CI runner recovery, DNS egress docs, zone DNS hardening
- PR #133 — feat(03d): secrets delivery hardening *(deleted the file — full contents visible as removed diff)*

## Remediation steps taken

### 1. Rotated all secrets

All credentials in the file were rotated or revoked before history rewrite:
- `PROXMOX_TOKEN_SECRET` — rotated, now read from SOPS
- `SONAR_TOKEN` — revoked in SonarCloud, new token stored in SOPS and updated in VSCode SonarLint
- `SNYK_TOKEN` — revoked in Snyk (OAuth flow), new token stored in SOPS and updated in GitHub Actions secrets
- Home lab passwords (`SERVICE_PASSWORD`, `PORTAINER_ADMIN_PASSWORD`, `NETBOX_*`, `MIKROTIK_PASSWORD`) — rotated

### 2. Rewrote git history

Used a mirror clone to rewrite all branches with `git filter-repo`:

```bash
git clone --mirror git@github.com:stevedwray/proxmox-homelab.git /tmp/proxmox-homelab-mirror
cd /tmp/proxmox-homelab-mirror
git filter-repo --invert-paths --path .env.pve-test
git remote add origin git@github.com:stevedwray/proxmox-homelab.git
git push --mirror origin
```

13 branches were rewritten and force-pushed. The `refs/pull/*/head` PR refs were rejected by GitHub (expected — those require a support request).

### 3. Synced local working copy

```bash
git fetch --prune
git branch -f main origin/main
git reset --hard origin/dev/pve-test
git gc --prune=now
```

All stale local topic branches (holding old hashes) were deleted.

### 4. Requested GitHub Support purge

Filed three GitHub Support requests (via the virtual assistant) to dereference cached commit refs for PRs #122, #130, and #133. Selected "Remove the commit references" (not remove PRs).

### 5. Added `.env.pve-test` to `.gitignore`

The file is gitignored so it cannot be accidentally committed again. All secrets are now managed via SOPS (`terraform/secrets.enc.yaml`) and injected at runtime via the `with-secrets` wrapper.

## Tools used

- `git-filter-repo` — history rewrite
- `gh` CLI — branch protection check, secret rotation, support ticket
- `with-secrets` — verified Snyk and SonarCloud tokens work with new credentials

## Prevention

- `.env*` files (except `.env.template`) are in `.gitignore`
- `gitleaks` runs in CI (added in PR #133) to detect future secret commits
- Secrets are stored encrypted in `terraform/secrets.enc.yaml` (SOPS + age)
- `with-secrets` wrapper injects secrets at runtime without writing them to disk
