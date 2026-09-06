#!/usr/bin/env bash
set -euo pipefail

# VictoriaMetrics needs at least one full scrape cycle (global_interval=30s) before
# targets transition from "unknown" to "up". For per-stack provisioning we only
# require the already-deployed core observability dependencies to be healthy here;
# later platform stacks and bootstrap-deferred node_exporter TLS should not block
# monitoring-stack's own smoke test.
max_attempts=8
sleep_between=15
required_stacks=(
  authentik-stack
  dns-stack
  harbor-stack
  monitoring-stack
  proxy-stack
)
missing=""

for ((attempt = 1; attempt <= max_attempts; attempt++)); do
  missing=$(curl -sf "http://${LAB_IP_MONITORING}:8428/api/v1/targets" \
    | python3 -c "
import json, sys
data = json.load(sys.stdin)
required = set(sys.argv[1:])
healthy = {
    t.get('labels', {}).get('stack', '')
    for t in data.get('data', {}).get('activeTargets', [])
    if t.get('health') == 'up'
}
missing = sorted(stack for stack in required if stack not in healthy)
print('\n'.join(missing))
" "${required_stacks[@]}")

  if [[ -z "$missing" ]]; then
    echo "monitoring: required core targets up"
    exit 0
  fi

  if [[ $attempt -lt $max_attempts ]]; then
    echo "monitoring: attempt ${attempt}/${max_attempts}: waiting ${sleep_between}s for core targets..."
    sleep "$sleep_between"
  fi
done

echo "monitoring: required core targets still missing after $((max_attempts * sleep_between))s:"
echo "$missing"
exit 1
