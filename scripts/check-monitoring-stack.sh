#!/usr/bin/env bash
set -euo pipefail

MONITORING_HOST="${MONITORING_HOST:-10.57.1.12}"
GRAFANA_URL="${GRAFANA_URL:-http://${MONITORING_HOST}:3000}"
VICTORIAMETRICS_URL="${VICTORIAMETRICS_URL:-http://${MONITORING_HOST}:8428/metrics}"
LOKI_READY_URL="${LOKI_READY_URL:-http://${MONITORING_HOST}:3100/ready}"
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-}"

PASS_COUNT=0
FAIL_COUNT=0

usage() {
  cat <<'EOF'
Usage: scripts/check-monitoring-stack.sh [--host <ip-or-hostname>] [--grafana-url <url>]

Required environment variables:
  GRAFANA_ADMIN_PASSWORD  Grafana admin password for datasource API checks

Optional environment variables:
  MONITORING_HOST         Monitoring host (default: 10.57.1.12)
  GRAFANA_URL             Grafana base URL (default: http://<host>:3000)
  VICTORIAMETRICS_URL     VictoriaMetrics metrics URL
  LOKI_READY_URL          Loki readiness URL
  GRAFANA_ADMIN_USER      Grafana admin user (default: admin)
EOF
}

log_info() {
  printf '[INFO] %s\n' "$1"
}

log_pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf '[PASS] %s\n' "$1"
}

log_fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf '[FAIL] %s\n' "$1"
}

print_summary() {
  printf '\n[SUMMARY] passed=%d failed=%d\n' "$PASS_COUNT" "$FAIL_COUNT"
}

require_bin() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1; then
    log_fail "Missing required command: $bin"
    print_summary
    exit 2
  fi
}

run_check() {
  local name="$1"
  shift
  log_info "$name"
  if "$@"; then
    log_pass "$name"
    return 0
  fi

  log_fail "$name"
  print_summary
  exit 1
}

check_grafana_health() {
  local response
  response="$(curl -fsS "${GRAFANA_URL}/api/health")" || return 1
  printf '%s' "$response" | jq -e '.database == "ok"' >/dev/null
}

check_victoriametrics_health() {
  curl -fsS -o /dev/null -w '%{http_code}' "$VICTORIAMETRICS_URL" | grep -qx '200'
}

check_loki_health() {
  local body
  body="$(curl -fsS "$LOKI_READY_URL")" || return 1
  [[ "$body" == *"ready"* ]]
}

check_grafana_datasources() {
  local datasources
  datasources="$(curl -fsS -u "${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}" "${GRAFANA_URL}/api/datasources")" || return 1

  printf '%s' "$datasources" | jq -e 'map(.name) | index("VictoriaMetrics") != null' >/dev/null || return 1
  printf '%s' "$datasources" | jq -e 'map(.name) | index("Loki") != null' >/dev/null
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      MONITORING_HOST="$2"
      shift 2
      ;;
    --grafana-url)
      GRAFANA_URL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n\n' "$1"
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$GRAFANA_ADMIN_PASSWORD" ]]; then
  log_fail "GRAFANA_ADMIN_PASSWORD is required"
  print_summary
  exit 2
fi

require_bin curl
require_bin jq

run_check "Grafana health database is ok" check_grafana_health
run_check "VictoriaMetrics metrics endpoint returns HTTP 200" check_victoriametrics_health
run_check "Loki readiness endpoint reports ready" check_loki_health
run_check "Grafana datasources include VictoriaMetrics and Loki" check_grafana_datasources

print_summary
printf '[RESULT] monitoring smoke checks passed\n'
