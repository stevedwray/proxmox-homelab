#!/usr/bin/env bash
set -euo pipefail

curl -sf "http://${LAB_IP_PROXY}:8080/ping" >/dev/null

echo "proxy: Traefik ping ok"
