#!/usr/bin/env bash
set -euo pipefail

# Harbor serves HTTP internally; TLS is terminated by Traefik (which may not
# be deployed yet at this stage). Check directly at the container's HTTP port.
curl -sf "http://${LAB_IP_HARBOR}/api/v2.0/health" \
  | grep -q '"status":"healthy"'

echo "harbor: healthy"
