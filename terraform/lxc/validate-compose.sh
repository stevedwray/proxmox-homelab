#!/usr/bin/env bash
# Validate docker-compose.yml conventions for active platform stacks.
# Usage: ./validate-compose.sh [--stack <name>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "${SCRIPT_DIR}/validate-compose.py" "$@"
