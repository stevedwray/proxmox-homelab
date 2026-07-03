#!/usr/bin/env bash
set -euo pipefail

TECHNITIUM_IP="${LAB_IP_TECHNITIUM:?LAB_IP_TECHNITIUM is required}"
LAB_DOMAIN="${LAB_DOMAIN:?LAB_DOMAIN is required}"
TECHNITIUM_BOOTSTRAP_ZONE="${TECHNITIUM_BOOTSTRAP_ZONE:-tech.${LAB_DOMAIN}}"

check_a_record() {
  local fqdn="$1"
  local expected="$2"
  local result

  result="$(dig @"${TECHNITIUM_IP}" "${fqdn}" +short | head -n 1 | tr -d '\r')"
  if [[ -z "${result}" ]]; then
    echo "technitium parity: no answer for ${fqdn}"
    return 1
  fi
  if [[ "${result}" != "${expected}" ]]; then
    echo "technitium parity: ${fqdn} expected ${expected} but got ${result}"
    return 1
  fi
  echo "technitium parity: ${fqdn} -> ${result}"
}

check_nonempty() {
  local fqdn="$1"
  local result

  result="$(dig @"${TECHNITIUM_IP}" "${fqdn}" +short | head -n 1 | tr -d '\r')"
  if [[ -z "${result}" ]]; then
    echo "technitium parity: no answer for ${fqdn}"
    return 1
  fi
  echo "technitium parity: ${fqdn} -> ${result}"
}

check_a_record "technitium.${LAB_DOMAIN}" "${LAB_IP_PROXY:?LAB_IP_PROXY is required}"
check_a_record "traefik.${LAB_DOMAIN}" "${LAB_IP_PROXY}"
check_a_record "authentik.${LAB_DOMAIN}" "${LAB_IP_PROXY}"
check_a_record "harbor.${LAB_DOMAIN}" "${LAB_IP_PROXY}"
check_a_record "netbox.${LAB_DOMAIN}" "${LAB_IP_PROXY}"
check_a_record "portainer.${LAB_DOMAIN}" "${LAB_IP_PROXY}"
check_a_record "dns.${LAB_DOMAIN}" "${TECHNITIUM_IP}"
check_a_record "ns1.${LAB_DOMAIN}" "${TECHNITIUM_IP}"
check_a_record "authentik-int.${LAB_DOMAIN}" "${LAB_IP_AUTHENTIK:?LAB_IP_AUTHENTIK is required}"
check_a_record "step-ca.${LAB_DOMAIN}" "${LAB_IP_STEP_CA:?LAB_IP_STEP_CA is required}"

check_nonempty "step-ca.${TECHNITIUM_BOOTSTRAP_ZONE}"
check_nonempty "github.com"
