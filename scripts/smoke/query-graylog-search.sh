#!/usr/bin/env bash
set -euo pipefail

# Query Graylog 6.x Search/Messages export API for recent test messages
# Usage: query-graylog-search.sh [host] [port] [query]
# Defaults: host=127.0.0.1 port=9000 query="message:graylog-smoke-test"

HOST=${1:-127.0.0.1}
PORT=${2:-9000}
QUERY=${3:-"message:graylog-smoke-test"}

API="http://${HOST}:${PORT}/api/views/search/messages"
FROM=300  # seconds back
FIELDS='["timestamp","source","application_name","message"]'

echo "Querying Graylog API: ${API} (query='${QUERY}', range=${FROM}s)"

GRAYLOG_PASS="${GRAYLOG_ROOT_PASSWORD:-admin}"
curl -fsS -X POST "${API}" \
  -H "Content-Type: application/json" \
  -H "X-Requested-By: smoke-script" \
  -u "admin:${GRAYLOG_PASS}" \
  -d "$(cat <<JSON
{
  "limit": 20,
  "fields_in_order": ${FIELDS},
  "time_zone": "UTC",
  "timerange": {
    "type": "relative",
    "range": ${FROM}
  },
  "query_string": {
    "type": "elasticsearch",
    "query_string": "${QUERY}"
  }
}
JSON
)" || true
