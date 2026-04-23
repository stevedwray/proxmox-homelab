#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

stacks=(
  "portainer-stack"
  "harbor-stack"
  "apt-cacher-stack"
  "ci-runner-01"
  "dns-stack"
  "step-ca-stack"
  "authentik-stack"
  "proxy-stack"
  "monitoring-stack"
  "netbox-stack"
)

for stack in "${stacks[@]}"; do
  echo "=== Planning stack: ${stack} ==="
  ./with-secrets terragrunt init -reconfigure --working-dir "terraform/lxc/stacks/${stack}"
  ./with-secrets terragrunt plan --working-dir "terraform/lxc/stacks/${stack}"
done
