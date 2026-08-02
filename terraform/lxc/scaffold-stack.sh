#!/usr/bin/env bash
# Scaffold a new stack's five files using narrow-scoped OpenCode agents.
# Usage: ./scaffold-stack.sh <stack-name>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "${SCRIPT_DIR}/scaffold-stack.py" "$@"
