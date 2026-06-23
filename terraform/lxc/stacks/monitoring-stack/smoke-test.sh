#!/usr/bin/env bash
set -euo pipefail

# VictoriaMetrics needs at least one full scrape cycle (global_interval=30s) before
# targets transition from "unknown" to "up". Poll until all are healthy or timeout.
max_attempts=8
sleep_between=15
down=""

for ((attempt = 1; attempt <= max_attempts; attempt++)); do
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

  if [[ -z "$down" ]]; then
    echo "monitoring: all targets up"
    exit 0
  fi

  if [[ $attempt -lt $max_attempts ]]; then
    echo "monitoring: attempt ${attempt}/${max_attempts}: waiting ${sleep_between}s for targets to scrape..."
    sleep "$sleep_between"
  fi
done

echo "monitoring: targets still down after $((max_attempts * sleep_between))s:"
echo "$down"
exit 1
