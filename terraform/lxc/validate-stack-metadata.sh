#!/usr/bin/env bash
# Validate documentation-only stack metadata for active platform stacks.
# Usage: ./validate-stack-metadata.sh [--check-contract-sections] [--check-contract-docs] [--json]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "${SCRIPT_DIR}/validate-stack-metadata.py" "$@"
