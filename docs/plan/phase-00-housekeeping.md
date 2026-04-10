# Phase 00 — Immediate Housekeeping

## Goal

Push all unpushed local commits to `origin/dev/pve-test`, commit the new `GreenField.md` planning document, and delete stale local branches left over from merged feature work.

## Repository context

- Working branch: `dev/pve-test`
- Check whether `dev/pve-test` is ahead of `origin/dev/pve-test` before pushing
- `docs/plans/GreenField.md` is untracked and should be committed
- Several local branches remain from already-merged PRs

## Prerequisites

None — this is the first thing to do.

## Related issues

None — pure housekeeping.

---

## Step 1 — Commit GreenField.md

`docs/plans/GreenField.md` is an architecture planning document that is currently untracked. It should be committed to the repo.

```bash
cd /home/steve/git/proxmox-homelab
git add docs/plans/GreenField.md
git commit -m "docs: add GreenField architecture planning document"
```

## Step 2 — Push dev/pve-test to origin

Push the 6 accumulated local commits plus the new commit above.

```bash
git push origin dev/pve-test
```

Verify the push succeeded — the commit count since origin should be 0:

```bash
git log origin/dev/pve-test..HEAD --oneline
# Expected: (no output)
```

## Step 3 — Delete stale local branches

These branches have already been merged into `dev/pve-test` and should be removed locally and from `origin`:

```bash
git branch -d dev/pve-test-network-layer-01
git branch -d feat/pve-test-validation-teardown-55
git branch -d feature/ci-test-ignore
git branch -d fix/pin-setup-terraform-v3
git push origin --delete dev/pve-test-network-layer-01
git push origin --delete feat/pve-test-validation-teardown-55
git push origin --delete feature/ci-test-ignore
git push origin --delete fix/pin-setup-terraform-v3
```

If any refuse with "not fully merged", inspect with `git log <branch> --oneline` before force-deleting locally. If any remote delete fails, confirm the branch is merged before removing it from `origin`.

Also prune remote tracking refs that no longer exist upstream:

```bash
git fetch --prune
```

## Step 4 — Verify clean state

```bash
git status
git branch -a
```

Expected state:
- `git status` shows a clean working tree
- Only `dev/pve-test`, `main`, and `cleanup/staged-archive` remain as local branches
- Remote branches: `origin/main`, `origin/dev/pve-test`, `origin/cleanup/staged-archive`

---

## Acceptance criteria

- [ ] `docs/plans/GreenField.md` committed and pushed
- [ ] `git log origin/dev/pve-test..HEAD --oneline` returns nothing
- [ ] All 4 stale branches deleted locally
- [ ] All 4 stale branches deleted from `origin`
- [ ] `git fetch --prune` removes stale remote-tracking refs
- [ ] `git status` shows clean working tree
