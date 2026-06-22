#!/usr/bin/env bash
set -euo pipefail

result=$(dig @"${LAB_IP_DNS}" "step-ca.${LAB_DOMAIN}" +short)
[[ -n "$result" ]] || { echo "dns: no answer for step-ca.${LAB_DOMAIN}"; exit 1; }
echo "dns: resolved step-ca.${LAB_DOMAIN} → ${result}"
