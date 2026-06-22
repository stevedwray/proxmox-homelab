#!/usr/bin/env bash
set -euo pipefail

ssh -o BatchMode=yes -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=no \
  "root@${LAB_IP_CI_RUNNER}" true

echo "ci-runner-01: SSH reachable"
