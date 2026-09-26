#!/usr/bin/env bash
set -euo pipefail

ssh -n -F /dev/null -i ~/.ssh/id_ed25519 \
  -o BatchMode=yes -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  root@192.168.110.10 docker version >/dev/null

echo "newt-connector: SSH reachable, Docker running"
