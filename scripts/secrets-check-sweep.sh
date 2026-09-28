#!/bin/bash
# Dry-run (ansible --check) every production stack through the OpenBao-backed
# wrappers. Nothing is changed on any host: no playbook task runs for real in
# check mode except read-only DNS/GET lookups (audited 2026-09-28), and
# provision.sh --check skips smoke tests and does not pass --diff.
#
# What it proves per stack: every secret the playbook needs resolves
# (mandatory() lookups), and files that embed secrets render identically to
# what is deployed ("changed" on a config/env task = rendered content differs).
#
# Full logs are written to RAM (/dev/shm) and deleted; only a summary of
# counts and task NAMES is kept in $SUMMARY (default /tmp/secrets-check-sweep-summary.txt).
# Run from the repo root:
#   export TASK_APPROVAL="secrets-refactor-check-sweep"
#   bash scripts/secrets-check-sweep.sh
set -uo pipefail
: "${TASK_APPROVAL:?export TASK_APPROVAL first (provision.sh is classified as mutating even with --check)}"
LOGDIR=$(mktemp -d /dev/shm/check-sweep.XXXXXX)
SUMMARY=${SUMMARY:-/tmp/secrets-check-sweep-summary.txt}
trap 'rm -rf "$LOGDIR"' EXIT
: > "$SUMMARY"

PVE_STACKS="apt-cacher-stack authentik-stack ci-runner-01 gaming-stack-lab graylog-stack greenbone-stack harbor-stack media-stack-lab monitoring-stack netbox-stack newt-connector nextcloud-stack openbao-stack pangolin-proxy portainer-stack proxy-stack pterodactyl-lab step-ca-stack technitium-stack torrent-stack-lab wazuh-stack"
TINY_STACKS="ai-services-stack mcp-utility-stack secpipe-stack opensearch-stack cse-panel-stack cse-controller cse-code-eval"

run() {  # wrapper stack
  local wrapper="$1" stack="$2" log="$LOGDIR/$2.log" recap
  "./$wrapper" scripts/provision.sh --check --stack "$stack" > "$log" 2>&1
  recap=$(grep -E '^\S+\s+: ok=' "$log" | tail -1 | sed -E 's/\s+/ /g')
  {
    printf '%-22s %-26s %s\n' "$stack" "$wrapper" "${recap:-NO RECAP: $(grep -E '\[provision\] (SKIP|ERROR)|ERROR' "$log" | head -1 | cut -c1-120)}"
    # task NAMES only (never values): which tasks changed or failed
    awk '/^TASK \[/{t=$0} /^changed: /{print "    changed: " t} /^(fatal|failed): /{print "    FAILED:  " t}' "$log" \
      | sed -E 's/TASK \[([^]]*)\].*/\1/' | sort -u
    grep -ohE "mandatory\('[A-Z0-9_]+ [^']*'\)|'[A-Z0-9_]+' is undefined|env var (is required|is not set|not set)" "$log" | sort -u | sed 's/^/    MISSING? /'
  } | tee -a "$SUMMARY"
}

echo "== pve"; for s in $PVE_STACKS; do run with-secrets-prod "$s"; done
echo "== pve-tiny"; for s in $TINY_STACKS; do run with-secrets-prod-tiny "$s"; done
echo "Summary kept at $SUMMARY (full logs deleted)."
