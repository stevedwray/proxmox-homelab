#!/usr/bin/env bash
# Pre-push: scan the commits about to be pushed with TruffleHog, unverified.
#
# CI's TruffleHog job only runs for PRs into main and is --only-verified, so it
# never sees work on stable and cannot judge a secret it has no way to test (a
# LAN Proxmox token, say). This runs before anything leaves the machine and
# reports anything that looks like a credential. It cannot find a secret with no
# recognisable format (a bare UUID); that is what block-terraform-plan-files and
# review of `git diff --cached --name-only` are for.
set -euo pipefail

command -v trufflehog >/dev/null || {
  echo "trufflehog is not installed; the pre-push secret scan needs it (https://github.com/trufflesecurity/trufflehog)" >&2
  exit 1
}

to="${PRE_COMMIT_TO_REF:-HEAD}"
from="${PRE_COMMIT_FROM_REF:-}"
# A brand-new branch has no remote ref: scan everything not already on stable.
if [[ -z "$from" || "$from" =~ ^0+$ ]]; then
  from="$(git merge-base origin/stable "$to" 2>/dev/null || true)"
fi
[[ -n "$from" ]] || { echo "trufflehog_prepush: no base commit to scan from, skipping" >&2; exit 0; }
[[ "$from" == "$(git rev-parse "$to")" ]] && exit 0

exec trufflehog git "file://$(git rev-parse --show-toplevel)" \
  --since-commit "$from" --branch "$to" --fail --no-update --no-verification
