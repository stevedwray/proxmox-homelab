#!/usr/bin/env bash
set -euo pipefail

curl -sf "http://${LAB_IP_PORTAINER}:9000/api/system/status" >/dev/null

echo "portainer: API responding"
