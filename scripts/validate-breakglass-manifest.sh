#!/usr/bin/env bash
set -euo pipefail

manifest="terraform/lxc/ansible/group_vars/all/breakglass.yml"
services=(
  apt-cacher
  dns
  step-ca
  ci-runner-01
  harbor
  authentik
  proxy
  monitoring
  netbox
  portainer
)
fields=(breakglass_username bg_fqdn bypass_authentik bypass_traefik)
lab_domain="${LAB_DOMAIN:-lab.gibbsgreatly.xyz}"
escaped_lab_domain="${lab_domain//./\\.}"

if [[ ! -f "$manifest" ]]; then
  echo "FAIL: missing $manifest"
  exit 1
fi

for service in "${services[@]}"; do
  if ! rg -n "^\s*${service}:" "$manifest" >/dev/null; then
    echo "FAIL: missing service key ${service}"
    exit 1
  fi

  if ! rg -n "${service}-bg\\.${escaped_lab_domain}" "$manifest" >/dev/null; then
    echo "FAIL: missing bg_fqdn for ${service}"
    exit 1
  fi

done

for field in "${fields[@]}"; do
  if ! rg -n "$field" "$manifest" >/dev/null; then
    echo "FAIL: missing field ${field}"
    exit 1
  fi

done

echo "PASS"
