#!/usr/bin/env bash
set -euo pipefail

COREDNS_IP="${LAB_IP_DNS:-}"
TECHNITIUM_IP="${LAB_IP_TECHNITIUM:-}"
LAB_DOMAIN="${LAB_DOMAIN:-}"

usage() {
  cat <<'EOF'
Usage: verify-coredns-technitium-parity.sh [options]

Compare direct DNS answers from CoreDNS and Technitium for the active lab zone.

Options:
  --coredns-ip IP        CoreDNS server IP (default: LAB_IP_DNS)
  --technitium-ip IP     Technitium server IP (default: LAB_IP_TECHNITIUM)
  --lab-domain DOMAIN    Authoritative lab domain (default: LAB_DOMAIN)
  --help                 Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --coredns-ip)
      COREDNS_IP="${2:?missing value for --coredns-ip}"
      shift 2
      ;;
    --technitium-ip)
      TECHNITIUM_IP="${2:?missing value for --technitium-ip}"
      shift 2
      ;;
    --lab-domain)
      LAB_DOMAIN="${2:?missing value for --lab-domain}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

: "${COREDNS_IP:?CoreDNS IP is required (set LAB_IP_DNS or pass --coredns-ip)}"
: "${TECHNITIUM_IP:?Technitium IP is required (set LAB_IP_TECHNITIUM or pass --technitium-ip)}"
: "${LAB_DOMAIN:?Lab domain is required (set LAB_DOMAIN or pass --lab-domain)}"

compare_record() {
  local record_type="$1"
  local fqdn="$2"
  local coredns_answer
  local technitium_answer

  coredns_answer="$(
    dig @"${COREDNS_IP}" "${fqdn}" "${record_type}" +short \
      | sed '/^$/d' \
      | sort -u
  )"
  technitium_answer="$(
    dig @"${TECHNITIUM_IP}" "${fqdn}" "${record_type}" +short \
      | sed '/^$/d' \
      | sort -u
  )"

  if [[ -z "${coredns_answer}" ]]; then
    echo "parity fail: CoreDNS returned no ${record_type} answer for ${fqdn}"
    return 1
  fi

  if [[ -z "${technitium_answer}" ]]; then
    echo "parity fail: Technitium returned no ${record_type} answer for ${fqdn}"
    return 1
  fi

  if [[ "${coredns_answer}" != "${technitium_answer}" ]]; then
    echo "parity fail: ${record_type} ${fqdn}"
    echo "  CoreDNS:    ${coredns_answer}"
    echo "  Technitium: ${technitium_answer}"
    return 1
  fi

  echo "parity ok: ${record_type} ${fqdn} -> ${technitium_answer}"
}

check_expected_record() {
  local server_name="$1"
  local server_ip="$2"
  local record_type="$3"
  local fqdn="$4"
  local expected="$5"
  local answer

  answer="$(
    dig @"${server_ip}" "${fqdn}" "${record_type}" +short \
      | sed '/^$/d' \
      | sort -u
  )"

  if [[ -z "${answer}" ]]; then
    echo "parity fail: ${server_name} returned no ${record_type} answer for ${fqdn}"
    return 1
  fi

  if [[ "${answer}" != "${expected}" ]]; then
    echo "parity fail: ${server_name} ${record_type} ${fqdn}"
    echo "  expected: ${expected}"
    echo "  actual:   ${answer}"
    return 1
  fi

  echo "parity ok: ${server_name} ${record_type} ${fqdn} -> ${answer}"
}

compare_soa_identity() {
  local fqdn="$1"
  local coredns_answer
  local technitium_answer

  coredns_answer="$(
    dig @"${COREDNS_IP}" "${fqdn}" SOA +short \
      | awk 'NF >= 2 {print $1 " " $2}' \
      | sed '/^$/d'
  )"
  technitium_answer="$(
    dig @"${TECHNITIUM_IP}" "${fqdn}" SOA +short \
      | awk 'NF >= 2 {print $1 " " $2}' \
      | sed '/^$/d'
  )"

  if [[ -z "${coredns_answer}" ]]; then
    echo "parity fail: CoreDNS returned no SOA answer for ${fqdn}"
    return 1
  fi

  if [[ -z "${technitium_answer}" ]]; then
    echo "parity fail: Technitium returned no SOA answer for ${fqdn}"
    return 1
  fi

  if [[ "${coredns_answer}" != "${technitium_answer}" ]]; then
    echo "parity fail: SOA identity ${fqdn}"
    echo "  CoreDNS:    ${coredns_answer}"
    echo "  Technitium: ${technitium_answer}"
    return 1
  fi

  echo "parity ok: SOA ${fqdn} -> ${technitium_answer}"
}

check_recursion() {
  local fqdn="$1"
  local coredns_answer
  local technitium_answer

  coredns_answer="$(dig @"${COREDNS_IP}" "${fqdn}" +short | head -n 1 | tr -d '\r')"
  technitium_answer="$(dig @"${TECHNITIUM_IP}" "${fqdn}" +short | head -n 1 | tr -d '\r')"

  if [[ -z "${coredns_answer}" ]]; then
    echo "parity fail: CoreDNS returned no recursive answer for ${fqdn}"
    return 1
  fi

  if [[ -z "${technitium_answer}" ]]; then
    echo "parity fail: Technitium returned no recursive answer for ${fqdn}"
    return 1
  fi

  echo "parity ok: recursion ${fqdn} -> CoreDNS=${coredns_answer} Technitium=${technitium_answer}"
}

echo "Comparing CoreDNS ${COREDNS_IP} with Technitium ${TECHNITIUM_IP} for ${LAB_DOMAIN}"

compare_record A "traefik.${LAB_DOMAIN}"
compare_record A "authentik.${LAB_DOMAIN}"
compare_record A "harbor.${LAB_DOMAIN}"
compare_record A "netbox.${LAB_DOMAIN}"
compare_record A "portainer.${LAB_DOMAIN}"
compare_record A "authentik-int.${LAB_DOMAIN}"
compare_record A "step-ca.${LAB_DOMAIN}"
compare_record NS "${LAB_DOMAIN}"
compare_soa_identity "${LAB_DOMAIN}"
check_recursion "github.com"

echo "Checking Technitium cutover-target authority records"
check_expected_record "Technitium" "${TECHNITIUM_IP}" A "dns.${LAB_DOMAIN}" "${TECHNITIUM_IP}"
check_expected_record "Technitium" "${TECHNITIUM_IP}" A "ns1.${LAB_DOMAIN}" "${TECHNITIUM_IP}"

echo "Parity check passed for ${LAB_DOMAIN}"
