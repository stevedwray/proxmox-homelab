#!/usr/bin/env bash
set -euo pipefail

# Queries technitium-stack directly, not through the MikroTik forward path —
# this stack is not cut over yet (see STACK_CONTRACT.md). Once Phase 3
# cutover lands, this should be updated to match dns-stack/smoke-test.sh's
# via-resolver pattern.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/verify-parity.sh"
