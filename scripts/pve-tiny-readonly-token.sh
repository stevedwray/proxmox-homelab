#!/usr/bin/env bash
# Kept for the runbook's sake: same as `scripts/pve-readonly-token.sh pve-tiny "$@"`.
exec "$(dirname "$0")/pve-readonly-token.sh" pve-tiny "$@"
