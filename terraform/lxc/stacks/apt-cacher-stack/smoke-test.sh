#!/usr/bin/env bash
set -euo pipefail

curl -sf "http://${LAB_IP_APT_CACHER}:3142/acng-report.html" >/dev/null

echo "apt-cacher: reachable"
