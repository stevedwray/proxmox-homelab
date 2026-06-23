#!/usr/bin/env bash
set -euo pipefail

# /api/ requires auth (returns 403); /login/ is the public health check endpoint.
curl -sf "http://${LAB_IP_NETBOX}:8080/login/" >/dev/null

echo "netbox: responding"
