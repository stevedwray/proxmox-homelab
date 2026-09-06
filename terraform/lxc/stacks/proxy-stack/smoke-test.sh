#!/usr/bin/env bash
set -euo pipefail

max_attempts=12
sleep_between=5

for ((attempt = 1; attempt <= max_attempts; attempt++)); do
  if curl -sf "http://${LAB_IP_PROXY}:8082/metrics" >/dev/null; then
    echo "proxy: Traefik metrics ok"
    exit 0
  fi

  if [[ $attempt -lt $max_attempts ]]; then
    echo "proxy: attempt ${attempt}/${max_attempts}: waiting ${sleep_between}s for Traefik metrics..."
    sleep "$sleep_between"
  fi
done

echo "proxy: Traefik metrics not ready after $((max_attempts * sleep_between))s"
exit 1
