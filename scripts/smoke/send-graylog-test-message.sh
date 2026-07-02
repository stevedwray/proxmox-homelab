#!/usr/bin/env bash
set -euo pipefail

# Send a test syslog message to the local rsyslog TCP input (127.0.0.1:10514)
# Usage: send-graylog-test-message.sh [message]

MSG=${1:-"graylog-smoke-test: $(hostname) $(date -Iseconds)"}

echo "Sending test message to 127.0.0.1:10514 -> ${MSG}"

# Use nc to send RFC5424-like syslog line
SYSLOG_LINE="<14>1 $(date -Iseconds) $(hostname) smoke-test - - - ${MSG}"

printf '%s\n' "${SYSLOG_LINE}" | nc -w 1 127.0.0.1 10514 || {
  echo "Failed to send via nc; trying curl to local tcp endpoint"
  curl -sS --max-time 2 --data-binary "${SYSLOG_LINE}" "http://127.0.0.1:10514/" || true
}

echo "Sent. You can query Graylog or check local rsyslog queues for forwarding."
