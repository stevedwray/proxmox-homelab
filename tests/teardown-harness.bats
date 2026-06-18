#!/usr/bin/env bats
# Bats tests for scripts/teardown-deploy-test.sh
#
# Run with: bats tests/teardown-harness.bats
# Requires bats-core >= 1.5.0  (https://github.com/bats-core/bats-core)
# No live network, Proxmox, or secrets access required.

REPO_ROOT="$(cd "$(dirname "${BATS_TEST_FILENAME}")/.." && pwd)"
HARNESS="${REPO_ROOT}/scripts/teardown-deploy-test.sh"
EVIDENCE_ROOT="${REPO_ROOT}/docs/teardown-test/artifacts/evidence"
MOCK_DIR="${REPO_ROOT}/tests/mocks"

# Minimal env for offline runs: no real IPs, no secrets.
# Tests that exercise approval/execute guards do not reach any live command.
export LAB_IP_PROXY=192.168.30.10
export LAB_IP_AUTHENTIK=192.168.20.10
export LAB_IP_DNS=192.168.40.1
export LAB_IP_PORTAINER=192.168.20.20
export LAB_GW_MGMT=192.168.20.1
export LAB_DOMAIN=lab.example.test
export PVE_ENV=pve-test-vm

setup() {
  # Prepend mocks so they shadow real executables for network/infra calls.
  export PATH="${MOCK_DIR}:${PATH}"
  # Use a unique stamp per test to avoid cross-test evidence collision.
  export TEARDOWN_TEST_STAMP="bats-test-$$-${BATS_TEST_NUMBER}"
  export TEARDOWN_INVENTORY_FILE="${REPO_ROOT}/docs/teardown-test/inventory.md"
}

teardown() {
  local evidence_dir="${EVIDENCE_ROOT}/${TEARDOWN_TEST_STAMP}"
  rm -rf "${evidence_dir}"
  rm -f "${EVIDENCE_ROOT}/.harness.lock"
}

# ---------------------------------------------------------------------------
# 1. --help is side-effect free
# ---------------------------------------------------------------------------

@test "--help exits 0 and prints usage" {
  run bash "${HARNESS}" --help
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Usage:"* ]]
}

@test "--help writes no evidence directory" {
  local stamp="bats-help-$$"
  TEARDOWN_TEST_STAMP="${stamp}" run bash "${HARNESS}" --help
  [ "${status}" -eq 0 ]
  [ ! -d "${EVIDENCE_ROOT}/${stamp}" ]
}

# ---------------------------------------------------------------------------
# 2. Missing --approval-text fails before live commands
# ---------------------------------------------------------------------------

@test "destroy --execute without --approval-text fails before any live command" {
  run bash "${HARNESS}" destroy --execute
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"approval"* ]] || [[ "${output}" == *"approve"* ]]
}

@test "cycle --execute without --approval-text fails before any live command" {
  run bash "${HARNESS}" cycle --execute
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"approval"* ]] || [[ "${output}" == *"approve"* ]]
}

# ---------------------------------------------------------------------------
# 3. Mutating phase without --execute fails
# ---------------------------------------------------------------------------

@test "destroy without --execute fails" {
  run bash "${HARNESS}" destroy
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"--execute"* ]]
}

@test "deploy-foundation without --execute fails" {
  run bash "${HARNESS}" deploy-foundation
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"--execute"* ]]
}

@test "deploy-edge without --execute fails" {
  run bash "${HARNESS}" deploy-edge
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"--execute"* ]]
}

@test "activate-edge without --execute fails" {
  run bash "${HARNESS}" activate-edge
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"--execute"* ]]
}

@test "deploy-platform without --execute fails" {
  run bash "${HARNESS}" deploy-platform
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"--execute"* ]]
}

@test "cycle without --execute fails" {
  run bash "${HARNESS}" cycle
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"--execute"* ]]
}

# ---------------------------------------------------------------------------
# 4. Approval phrase matching is case-insensitive
# ---------------------------------------------------------------------------
# These tests stop at the approval-packet gate (not live), which is fine —
# the approval-text guard ran and accepted the phrase before that check.

@test "approval phrase 'approve' (lowercase) is accepted" {
  run bash "${HARNESS}" destroy --execute --approval-text "approve" --disposable
  # disposable skips packet validation; should fail at guard_target (no live env)
  # but NOT at require_execute_approval — so error must NOT mention 'approval-text'
  [[ "${output}" != *"requires approval text"* ]]
}

@test "approval phrase 'APPROVE' (uppercase) is accepted" {
  run bash "${HARNESS}" destroy --execute --approval-text "APPROVE" --disposable
  [[ "${output}" != *"requires approval text"* ]]
}

@test "approval phrase 'I Approve this change' (mixed) is accepted" {
  run bash "${HARNESS}" destroy --execute --approval-text "I Approve this change" --disposable
  [[ "${output}" != *"requires approval text"* ]]
}

@test "wrong approval phrase 'nope' is rejected" {
  run bash "${HARNESS}" destroy --execute --approval-text "nope"
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"approval text"* ]] || [[ "${output}" == *"approve"* ]]
}

# ---------------------------------------------------------------------------
# 5. --stamp routes evidence to the named directory
# ---------------------------------------------------------------------------

@test "--stamp routes state.json to the stamped evidence directory" {
  local stamp="bats-stamp-fixed-9999"
  TEARDOWN_TEST_STAMP="" LAB_IP_PROXY=192.168.30.10 \
    run bash "${HARNESS}" source-preflight --stamp "${stamp}"
  local evidence_dir="${EVIDENCE_ROOT}/${stamp}"
  [ -f "${evidence_dir}/state.json" ]
  rm -rf "${evidence_dir}"
}

@test "--stamp routes run log to the stamped evidence directory" {
  local stamp="bats-stamp-runlog-9999"
  TEARDOWN_TEST_STAMP="" LAB_IP_PROXY=192.168.30.10 \
    run bash "${HARNESS}" source-preflight --stamp "${stamp}"
  local log_file="${EVIDENCE_ROOT}/${stamp}/logs/teardown-deploy-test-${stamp}.log"
  [ -f "${log_file}" ]
  rm -rf "${EVIDENCE_ROOT}/${stamp}"
}

# ---------------------------------------------------------------------------
# 6. Concurrency lock: second harness run blocked while first holds lock
# ---------------------------------------------------------------------------

@test "second destructive run blocked when lock file is held by live PID" {
  # Simulate a live lock held by the current shell ($$)
  mkdir -p "${EVIDENCE_ROOT}"
  python3 -c "
import json, os, sys
data = {'stamp': 'fake-20260101-000000', 'pid': str(os.getpid()), 'branch': 'test', 'commit': 'abc123'}
print(json.dumps(data))
" > "${EVIDENCE_ROOT}/.harness.lock"

  run bash "${HARNESS}" destroy --execute --approval-text "approve" --disposable
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"another harness run is active"* ]] || \
    [[ "${output}" == *"lock"* ]]

  rm -f "${EVIDENCE_ROOT}/.harness.lock"
}

@test "stale lock (dead PID) is cleared and run proceeds past lock check" {
  # Write a lock with a PID that doesn't exist
  mkdir -p "${EVIDENCE_ROOT}"
  python3 -c "
import json
data = {'stamp': 'fake-stale', 'pid': '99999999', 'branch': 'test', 'commit': 'abc123'}
print(json.dumps(data))
" > "${EVIDENCE_ROOT}/.harness.lock"

  # Should get past the lock check (stale cleared) and fail for other reasons
  run bash "${HARNESS}" destroy --execute --approval-text "approve"
  # Must NOT fail with "another harness run is active"
  [[ "${output}" != *"another harness run is active"* ]]
  rm -f "${EVIDENCE_ROOT}/.harness.lock"
}
