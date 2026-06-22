#!/usr/bin/env bash
set -euo pipefail

down=$(curl -sf "http://${LAB_IP_MONITORING}:8428/api/v1/targets" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
down = [
    t['labels'].get('instance', '?')
    for t in data.get('data', {}).get('activeTargets', [])
    if t['health'] != 'up'
]
print('\n'.join(down))
")

if [[ -n "$down" ]]; then
  echo "monitoring: targets down:"
  echo "$down"
  exit 1
fi

echo "monitoring: all targets up"
