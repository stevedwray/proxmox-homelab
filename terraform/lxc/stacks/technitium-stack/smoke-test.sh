#!/usr/bin/env bash
set -euo pipefail

# Queries technitium-stack directly, not through the MikroTik forward path —
# this stack is not cut over yet (see STACK_CONTRACT.md). Once Phase 3
# cutover lands, this should be updated to match dns-stack/smoke-test.sh's
# via-resolver pattern.

TECHNITIUM_BOOTSTRAP_ZONE="${TECHNITIUM_BOOTSTRAP_ZONE:-tech.${LAB_DOMAIN}}"

result=$(dig @"${LAB_IP_TECHNITIUM}" "step-ca.${TECHNITIUM_BOOTSTRAP_ZONE}" +short)
[[ -n "$result" ]] || { echo "technitium: no answer for step-ca.${TECHNITIUM_BOOTSTRAP_ZONE}"; exit 1; }
echo "technitium: resolved step-ca.${TECHNITIUM_BOOTSTRAP_ZONE} → ${result}"

recursive_result=$(dig @"${LAB_IP_TECHNITIUM}" github.com +short)
[[ -n "$recursive_result" ]] || { echo "technitium: no answer for recursive query (github.com)"; exit 1; }
echo "technitium: resolved github.com → ${recursive_result}"
