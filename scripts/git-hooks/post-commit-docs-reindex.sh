#!/usr/bin/env bash
# Auto-refresh docs-rag-mcp's corpus/index after a commit that touches
# tracked documentation (docs/**/*.md, any STACK_CONTRACT.md, or CLAUDE.md).
#
# This is deliberately treated as a data-refresh housekeeping action, not an
# infra mutation: it copies markdown into an already-running container's
# corpus and restarts that one stateless container to re-run its own
# startup reindex (see docs/coding-stack/plan.md Phase 2's "Reindex
# mechanism" and Phase 4/5) -- no terraform, no firewall/SDN/storage change,
# no container replacement. The operator explicitly decided CLAUDE.md's
# per-task production-mutation approval gate doesn't apply to this class of
# action (docs/coding-stack/plan.md Phase 5). It still targets production
# `pve` for real, so keep this hook doing exactly this one narrow thing --
# don't grow it into a general "run arbitrary stuff on commit" hook.
#
# Runs in the background so `git commit` returns immediately. Installed via
# scripts/install-git-hooks.sh (not tracked directly under .git/hooks/, so
# it survives review/re-install).
#
# Uses with-secrets-prod (not with-secrets): docs-rag-mcp is deployed on
# production `pve`, not pve-test-vm. with-secrets defaults to pve-test-vm
# and would silently try to reindex a host that doesn't run this stack.
# TASK_APPROVAL is set to a fixed value here deliberately -- the operator
# already decided (docs/coding-stack/plan.md Phase 5) that this specific,
# narrow, idempotent action doesn't need a fresh per-run chat approval the
# way a real infra mutation would.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

CHANGED="$(git diff --name-only HEAD~1 HEAD 2>/dev/null || true)"

if echo "$CHANGED" | grep -qE '^(docs/.*\.md$|.*STACK_CONTRACT\.md$|CLAUDE\.md$)'; then
  LOG="/tmp/docs-rag-reindex-$(date +%Y%m%d-%H%M%S).log"
  echo "[post-commit] docs changed -- refreshing docs-rag-mcp corpus in the background"
  echo "[post-commit] log: $LOG"
  (
    export TASK_APPROVAL="docs-rag-mcp-housekeeping-reindex"
    nohup ./with-secrets-prod scripts/provision.sh --stack mcp-utility-stack \
      > "$LOG" 2>&1 &
    disown
  )
fi
