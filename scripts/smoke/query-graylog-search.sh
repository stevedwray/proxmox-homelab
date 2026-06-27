#!/usr/bin/env bash
set -euo pipefail

# Query Graylog search API for recent test messages
# Usage: query-graylog-search.sh [host] [port] [query]
# Defaults: host=127.0.0.1 port=9000 query="message:graylog-smoke-test"

HOST=${1:-127.0.0.1}
PORT=${2:-9000}
QUERY=${3:-"message:graylog-smoke-test"}

API="http://${HOST}:${PORT}/api/search/universal/relative"
FROM=300  # seconds back

echo "Querying Graylog API: ${API} (query='${QUERY}')"

GRAYLOG_PASS="${GRAYLOG_ROOT_PASSWORD:-admin}"
curl -fsS --get "${API}" --data-urlencode "query=${QUERY}" --data-urlencode "range=${FROM}" -u "admin:${GRAYLOG_PASS}" || true
