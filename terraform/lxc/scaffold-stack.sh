#!/usr/bin/env bash
# DEPRECATED -- drove five narrow-scoped OpenCode agents to scaffold a new
# stack's five files. opencode is a deprecated path in this lab (operator
# decision, 2026-09-04 -- see docs/media-stack-lab/plan.md). Running this
# just calls into scaffold-stack.py, which refuses to run and points at the
# manual fallback instead.
# Usage: ./scaffold-stack.sh <stack-name>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "${SCRIPT_DIR}/scaffold-stack.py" "$@"
