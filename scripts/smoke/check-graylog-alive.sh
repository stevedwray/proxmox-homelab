#!/usr/bin/env bash
set -euo pipefail

# Usage: check-graylog-alive.sh [host] [port]
# Defaults: host=127.0.0.1 port=9000

HOST=${1:-127.0.0.1}
PORT=${2:-9000}
URL="http://${HOST}:${PORT}/api/system/lbstatus"

echo "Checking Graylog ALIVE at ${URL}"

if OUTPUT=$(curl -fsS --max-time 5 "${URL}" 2>/dev/null || true); then
  # trim CR/LF
  OUTPUT=$(echo -n "${OUTPUT}" | tr -d '\r\n')
  if [ "${OUTPUT}" = "ALIVE" ]; then
    echo "OK: Graylog ALIVE"
    exit 0
  fi
fi

echo "ERROR: Graylog not ALIVE at ${URL}"
curl -v --max-time 5 "${URL}" || true
exit 2
