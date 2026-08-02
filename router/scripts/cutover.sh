#!/usr/bin/env bash
# Cutover script: transitions the hAP ax3 into production.
#
# Run this BEFORE the physical swap. It will:
#   1. Pre-add the LAN gateway CIDR to the new router
#   2. Monitor vlan1-wan until a DHCP lease is obtained
#   3. Verify internet connectivity
#   4. Finalize: enable DHCP server, remove the temporary management CIDR

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/../.."

eval "$(sops -d "${REPO_ROOT}/terraform/secrets.common.enc.yaml" \
  | grep -E '^(hAPax3_ADMIN|MIKROTIK_USER):' \
  | sed 's/: /=/;s/^/export /')"

TARGET_HOST="${MIKROTIK_HOST:?MIKROTIK_HOST not set}"
TARGET="https://${TARGET_HOST}"
LAN_GW_CIDR="${MIKROTIK_LAN_GW_CIDR:?MIKROTIK_LAN_GW_CIDR not set}"
LAN_GW_IP="${LAN_GW_CIDR%/*}"
MGMT_CIDR="${MIKROTIK_MGMT_CIDR:?MIKROTIK_MGMT_CIDR not set}"
AUTH_USER="${MIKROTIK_USER}"
# shellcheck disable=SC2154  # hAPax3_ADMIN is set in the environment by the caller
AUTH_PASS="${hAPax3_ADMIN}"

_curl() { curl -sf -k -u "${AUTH_USER}:${AUTH_PASS}" "$@"; }
get()   { _curl "${TARGET}/rest${1}"; }
put()   { _curl -X PUT   -H 'Content-Type: application/json' -d "${2}" "${TARGET}/rest${1}"; }
patch() { _curl -X PATCH -H 'Content-Type: application/json' -d "${2}" "${TARGET}/rest${1}"; }
del()   { _curl -X DELETE "${TARGET}/rest${1}"; }
log()   { echo "[$(date '+%H:%M:%S')] $*"; }

# ---------------------------------------------------------------------------
log "Checking connectivity to new router at ${TARGET} ..."
get /system/identity | jq -r '"  OK: \(.name)"'

# ---------------------------------------------------------------------------
log "Step 1: Pre-adding ${LAN_GW_CIDR} to new router bridgeLocal"
existing=$(get /ip/address | jq -r --arg cidr "$LAN_GW_CIDR" '.[] | select(.address == $cidr) | .".id"' || true)
if [[ -n "${existing}" ]]; then
  log "  ${LAN_GW_CIDR} already present"
else
  put /ip/address "{\"address\":\"${LAN_GW_CIDR}\",\"interface\":\"bridgeLocal\"}" > /dev/null
  log "  Added ${LAN_GW_CIDR}"
fi

log ""
log "================================================================"
log "  Ready. Do the physical cutover now:"
log "    1. Unplug the OLD router from the switch AND from the modem"
log "    2. Plug the modem/ISP cable into ether2 on the NEW router"
log "    3. The new router's ether5 is already on the switch"
log "================================================================"
log ""
log "Step 2: Monitoring vlan1-wan for DHCP lease ..."

ATTEMPTS=0
MAX_ATTEMPTS=60   # 2 minutes at 2s intervals

while [ "${ATTEMPTS}" -lt "${MAX_ATTEMPTS}" ]; do
  STATUS=$(get /ip/dhcp-client | jq -r '.[] | select(.interface == "vlan1-wan") | .status' 2>/dev/null || echo "unreachable")
  ADDR=$(get /ip/dhcp-client | jq -r '.[] | select(.interface == "vlan1-wan") | ."active-address" // "none"' 2>/dev/null || echo "none")
  ETHER2=$(get /interface/ethernet | jq -r '.[] | select(.name == "ether2") | .running' 2>/dev/null || echo "false")

  log "  ether2 link: ${ETHER2}  |  vlan1-wan DHCP: ${STATUS}  |  address: ${ADDR}"

  if [ "${STATUS}" = "bound" ] && [ "${ADDR}" != "none" ]; then
    log ""
    log "  WAN lease obtained: ${ADDR}"
    break
  fi

  ATTEMPTS=$(( ATTEMPTS + 1 ))
  sleep 2
done

if [[ "${ATTEMPTS}" -ge "${MAX_ATTEMPTS}" ]]; then
  log "ERROR: DHCP lease not obtained after 2 minutes. Aborting — do not finalize."
  exit 1
fi

# ---------------------------------------------------------------------------
log ""
log "Step 3: Verifying internet connectivity ..."
# shellcheck disable=SC2034  # LOSS captures command exit status as a connectivity probe; value not used
LOSS=$(get /ip/firewall/connection | jq 'length' 2>/dev/null || echo "skip")  # just a connectivity probe
PING=$(curl -sf -k -u "${AUTH_USER}:${AUTH_PASS}" -X POST \
  -H 'Content-Type: application/json' \
  -d '{"address":"8.8.8.8","count":"3"}' \
  "${TARGET}/rest/ping" | jq -r 'last | ."packet-loss"' 2>/dev/null || echo "100")

if [[ "${PING}" == "0" ]]; then
  log "  Internet reachable (0% packet loss to 8.8.8.8)"
else
  log "  WARNING: ping to 8.8.8.8 shows ${PING}% loss — check WAN before finalizing"
fi

# ---------------------------------------------------------------------------
log ""
log "Step 4: Finalizing ..."

log "  Enabling DHCP server"
DHCP_ID=$(get /ip/dhcp-server | jq -r '.[0].".id"')
patch "/ip/dhcp-server/${DHCP_ID}" '{"disabled":"false"}' > /dev/null
log "  DHCP server enabled"

log "  Removing management IP ${MGMT_CIDR}"
MGMT_ID=$(get /ip/address | jq -r --arg cidr "$MGMT_CIDR" '.[] | select(.address == $cidr) | .".id"' || true)
if [[ -n "${MGMT_ID}" ]]; then
  del "/ip/address/${MGMT_ID}" > /dev/null
  log "  Removed ${MGMT_CIDR}"
else
  log "  ${MGMT_CIDR} already gone"
fi

# ---------------------------------------------------------------------------
log ""
log "================================================================"
WAN_IP=$(get /ip/dhcp-client | jq -r '.[] | select(.interface == "vlan1-wan") | ."active-address"')
ROS=$(get /system/resource | jq -r '.version')
log "  Cutover complete!"
log "  Router: $(get /system/identity | jq -r '.name')  ROS: ${ROS}"
log "  WAN IP: ${WAN_IP}"
log "  New router is now live at ${LAN_GW_IP}"
log "================================================================"
