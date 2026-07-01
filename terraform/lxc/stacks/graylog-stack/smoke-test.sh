#!/usr/bin/env bash
set -euo pipefail

# The teardown regression is specific to the pve-test-vm/test-domain path.
# Keep this smoke gate advisory-only for other environments until they opt into
# the same runtime behavior.
if [[ "${PVE_ENV:-}" != "pve-test-vm" ]]; then
  echo "Skipping Graylog smoke test outside pve-test-vm (PVE_ENV=${PVE_ENV:-unset})"
  exit 0
fi

HOST="${LAB_IP_GRAYLOG:-}"
PORT="${GRAYLOG_SMOKE_PORT:-9000}"

if [[ -z "${HOST}" ]]; then
  echo "LAB_IP_GRAYLOG is not set" >&2
  exit 1
fi

for attempt in $(seq 1 24); do
  echo "Graylog smoke attempt ${attempt}/24: host=${HOST} port=${PORT}"
  if bash "${REPO_ROOT}/scripts/smoke/check-graylog-alive.sh" "${HOST}" "${PORT}"; then
    exit 0
  fi
  sleep 5
done

echo "Graylog smoke test failed: ${HOST}:${PORT} never reported ALIVE" >&2
exit 1
