#!/usr/bin/env bash
set -euo pipefail

curl -sf "http://${LAB_IP_NETBOX}:8080/api/" >/dev/null

echo "netbox: API responding"
