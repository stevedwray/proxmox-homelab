#!/usr/bin/env bash
# Provisions the hAP ax3 as a drop-in replacement for the hAP ac.
# Reads all source config from router/config/current-config.json.
# Safe to run against https://192.168.1.251 while the old router is still live.
#
# Port layout (differs from old hAP ac where ether1 was WAN):
#   ether1 (2.5G) → bridgeLocal  (switch uplink)
#   ether2 (1G)   → WAN          (vlan1-wan, VLAN 10 tag, DHCP client)
#   ether3 (1G)   → bridgeLocal
#   ether4 (1G)   → bridgeLocal
#   ether5 (1G)   → bridgeLocal  (currently connected for management)
#
# Usage:
#   ./provision-hap-ax3.sh
#   MIKROTIK_TARGET=192.168.x.x ./provision-hap-ax3.sh   # override target IP

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/../.."
CONFIG="${SCRIPT_DIR}/../config/current-config.json"

TARGET_IP="${MIKROTIK_TARGET:-192.168.1.251}"
TARGET="https://${TARGET_IP}"

# Load credentials from SOPS
eval "$(sops -d "${REPO_ROOT}/terraform/secrets.enc.yaml" \
  | grep -E '^(hAPax3_ADMIN|MIKROTIK_USER):' \
  | sed 's/: /=/;s/^/export /')"
AUTH_USER="${MIKROTIK_USER}"
AUTH_PASS="${hAPax3_ADMIN}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_curl() { curl -sf -k -u "${AUTH_USER}:${AUTH_PASS}" "$@"; }
get()    { _curl "${TARGET}/rest${1}"; }
put()    { _curl -X PUT   -H 'Content-Type: application/json' -d "${2}" "${TARGET}/rest${1}"; }
patch()  { _curl -X PATCH -H 'Content-Type: application/json' -d "${2}" "${TARGET}/rest${1}"; }
post()   { _curl -X POST  -H 'Content-Type: application/json' -d "${2}" "${TARGET}/rest${1}"; }
del()    { _curl -X DELETE "${TARGET}/rest${1}"; }
jqc()    { jq -r "$@" "${CONFIG}"; }
log()    { echo "[$(date '+%H:%M:%S')] $*"; }

# ---------------------------------------------------------------------------
log "Checking connectivity to ${TARGET} ..."
get /system/identity | jq -r '"  Connected: router is named \(.name)"'

# ---------------------------------------------------------------------------
log "=== Phase 1: System ==="

IDENTITY=$(jqc '.system.identity.name')
log "Setting identity → ${IDENTITY}"
post /system/identity/set "{\"name\":\"${IDENTITY}\"}" > /dev/null

log "Disabling plain HTTP"
patch /ip/service/www '{"disabled":"true"}' > /dev/null

log "Configuring NTP"
NTP_SERVERS=$(jqc '.system.ntp.servers')
post /system/ntp/client/set "{\"enabled\":\"true\",\"mode\":\"unicast\",\"servers\":\"${NTP_SERVERS}\"}" > /dev/null

# ---------------------------------------------------------------------------
log "=== Phase 2: Bridge ==="

# Rename default 'bridge' → 'bridgeLocal'
BRIDGE_ID=$(get /interface/bridge | jq -r '.[] | select(.name == "bridge") | .".id"')
log "Renaming bridge (${BRIDGE_ID}) → bridgeLocal"
patch "/interface/bridge/${BRIDGE_ID}" '{"name":"bridgeLocal"}' > /dev/null

# ether2 leaves the bridge — becomes the WAN port
ETHER2_ID=$(get /interface/bridge/port | jq -r '.[] | select(.interface == "ether2") | .".id"')
log "Removing ether2 from bridgeLocal (becomes WAN)"
del "/interface/bridge/port/${ETHER2_ID}" > /dev/null

# ether1 (2.5G) joins the bridge
log "Adding ether1 (2.5G) to bridgeLocal"
put /interface/bridge/port '{"interface":"ether1","bridge":"bridgeLocal"}' > /dev/null

# Remove WiFi from bridge — configured separately later
for wifi in wifi1 wifi2; do
  WIFI_ID=$(get /interface/bridge/port | jq -r --arg w "$wifi" '.[] | select(.interface == $w) | .".id"' 2>/dev/null || true)
  if [ -n "${WIFI_ID}" ]; then
    log "Removing ${wifi} from bridge"
    del "/interface/bridge/port/${WIFI_ID}" > /dev/null
  fi
done

# ---------------------------------------------------------------------------
log "=== Phase 3: VLANs ==="

put /interface/vlan '{"name":"vlan1-wan",   "vlan-id":"10","interface":"ether2",      "comment":"WAN uplink (VLAN10 on ether2)"}' > /dev/null
put /interface/vlan '{"name":"vlan10-build","vlan-id":"10","interface":"bridgeLocal",  "comment":"build_seg gw"}' > /dev/null
put /interface/vlan '{"name":"vlan20-mgmt", "vlan-id":"20","interface":"bridgeLocal",  "comment":"mgmt_seg gw"}' > /dev/null
put /interface/vlan '{"name":"vlan30-edge", "vlan-id":"30","interface":"bridgeLocal",  "comment":"edge_seg gw"}' > /dev/null
put /interface/vlan '{"name":"vlan40-infra","vlan-id":"40","interface":"bridgeLocal",  "comment":"infra_seg gw"}' > /dev/null
log "  5 VLANs created"

# ---------------------------------------------------------------------------
log "=== Phase 4: IP Addresses ==="

# Remove the factory default 192.168.88.1/24
DEFAULT_ADDR_ID=$(get /ip/address | jq -r '.[] | select(.address == "192.168.88.1/24") | .".id"' || true)
if [ -n "${DEFAULT_ADDR_ID}" ]; then
  log "Removing factory default 192.168.88.1/24"
  del "/ip/address/${DEFAULT_ADDR_ID}" > /dev/null
fi

# Apply VLAN gateway addresses from source config.
# The source has 192.168.1.1/24 on ether2 (a bridge slave); remap to bridgeLocal.
# We skip dynamic addresses (WAN DHCP).
log "Applying VLAN gateway addresses"
jqc -c '.ip.addresses[] | select(.dynamic == "false")' | while IFS= read -r entry; do
  addr=$(echo "$entry" | jq -r '.address')
  iface=$(echo "$entry" | jq -r '.interface')
  comment=$(echo "$entry" | jq -r '.comment // ""')

  # Remap: old LAN IP was on ether2 (bridge slave) → bridgeLocal on new router
  if echo "$addr" | grep -q '^192\.168\.1\.1/'; then
    iface="bridgeLocal"
  fi

  # Skip addresses already present
  existing=$(get /ip/address | jq -r --arg a "$addr" --arg i "$iface" \
    '.[] | select(.address == $a and .interface == $i) | .".id"' || true)
  if [ -n "${existing}" ]; then
    log "  ${iface}: ${addr} (already present)"
    continue
  fi

  log "  ${iface}: ${addr}"
  put /ip/address \
    "{\"address\":\"${addr}\",\"interface\":\"${iface}\",\"comment\":\"${comment}\"}" > /dev/null
done

# 192.168.1.251/24 remains on bridgeLocal for management access throughout provisioning.
# Remove it manually after cutover (or run the cutover script).

# ---------------------------------------------------------------------------
log "=== Phase 5: WAN ==="

log "Adding DHCP client on vlan1-wan"
put /ip/dhcp-client \
  '{"interface":"vlan1-wan","disabled":"false","add-default-route":"yes","use-peer-dns":"no","comment":"WAN"}' > /dev/null

# ---------------------------------------------------------------------------
log "=== Phase 6: Routing ==="

TEMP_ROUTE_ID=$(get /ip/route | jq -r '.[] | select(.comment == "temp-upgrade-route") | .".id"' || true)
if [ -n "${TEMP_ROUTE_ID}" ]; then
  log "Removing temporary upgrade route"
  del "/ip/route/${TEMP_ROUTE_ID}" > /dev/null
fi

# ---------------------------------------------------------------------------
log "=== Phase 7: Firewall ==="

# Clear all existing non-dynamic filter rules
log "Clearing default firewall filter rules"
get /ip/firewall/filter | jq -r '.[] | select(.dynamic == "false") | .".id"' | while IFS= read -r id; do
  del "/ip/firewall/filter/${id}" > /dev/null
done

# Apply filter rules from source config in order
FW_COUNT=$(jqc '.firewall.filter | length')
log "Applying ${FW_COUNT} filter rules"
jqc -c '.firewall.filter[]' | while IFS= read -r rule; do
  payload=$(echo "$rule" | jq 'del(.".id",.dynamic,.invalid,.bytes,.packets)')
  put /ip/firewall/filter "$payload" > /dev/null
done
log "  ${FW_COUNT} filter rules applied"

# Clear existing non-dynamic NAT rules
log "Clearing default NAT rules"
get /ip/firewall/nat | jq -r '.[] | select(.dynamic == "false") | .".id"' | while IFS= read -r id; do
  del "/ip/firewall/nat/${id}" > /dev/null
done

# Apply NAT rules from source config
NAT_COUNT=$(jqc '.firewall.nat | length')
log "Applying ${NAT_COUNT} NAT rules"
jqc -c '.firewall.nat[]' | while IFS= read -r rule; do
  payload=$(echo "$rule" | jq 'del(.".id",.dynamic,.invalid,.bytes,.packets)')
  put /ip/firewall/nat "$payload" > /dev/null
done
log "  ${NAT_COUNT} NAT rules applied"

# ---------------------------------------------------------------------------
log "=== Phase 8: DNS ==="

DOH=$(jqc '.ip.dns."use-doh-server"')
log "Setting DoH upstream: ${DOH}"
post /ip/dns/set \
  "{\"use-doh-server\":\"${DOH}\",\"allow-remote-requests\":\"true\",\"verify-doh-cert\":\"false\",\"servers\":\"\"}" > /dev/null

DNS_COUNT=$(jqc '.ip.dns_static | length')
log "Adding ${DNS_COUNT} static DNS entries"
jqc -c '.ip.dns_static[] | select(.dynamic == "false")' | while IFS= read -r entry; do
  payload=$(echo "$entry" | jq 'del(.".id",.dynamic)')
  put /ip/dns/static "$payload" > /dev/null
done
log "  ${DNS_COUNT} static entries added"

# ---------------------------------------------------------------------------
log "=== Phase 9: DHCP ==="

# Remove factory default DHCP server, networks and pools
log "Removing factory DHCP config"
DEFCONF_ID=$(get /ip/dhcp-server | jq -r '.[] | select(.name == "defconf") | .".id"' || true)
[ -n "${DEFCONF_ID}" ] && del "/ip/dhcp-server/${DEFCONF_ID}" > /dev/null

get /ip/dhcp-server/network | jq -r '.[].".id"' | while IFS= read -r id; do
  del "/ip/dhcp-server/network/${id}" > /dev/null
done

get /ip/pool | jq -r '.[].".id"' | while IFS= read -r id; do
  del "/ip/pool/${id}" > /dev/null
done

# Add pool
POOL_NAME=$(jqc '.ip.pools[0].name')
POOL_RANGES=$(jqc '.ip.pools[0].ranges')
log "Adding DHCP pool: ${POOL_NAME} (${POOL_RANGES})"
put /ip/pool "{\"name\":\"${POOL_NAME}\",\"ranges\":\"${POOL_RANGES}\"}" > /dev/null

# Add DHCP server
SERVER_NAME=$(jqc '.dhcp.servers[0].name')
SERVER_IFACE=$(jqc '.dhcp.servers[0].interface')
SERVER_LEASE=$(jqc '.dhcp.servers[0]."lease-time"')
log "Adding DHCP server: ${SERVER_NAME} on ${SERVER_IFACE}"
put /ip/dhcp-server \
  "{\"name\":\"${SERVER_NAME}\",\"interface\":\"${SERVER_IFACE}\",\"address-pool\":\"${POOL_NAME}\",\"lease-time\":\"${SERVER_LEASE}\",\"disabled\":\"false\"}" > /dev/null

# Add DHCP network
NET_ADDR=$(jqc '.dhcp.networks[0].address')
NET_GW=$(jqc '.dhcp.networks[0].gateway')
NET_DNS=$(jqc '.dhcp.networks[0]."dns-server"')
log "Adding DHCP network: ${NET_ADDR} gw ${NET_GW}"
put /ip/dhcp-server/network \
  "{\"address\":\"${NET_ADDR}\",\"gateway\":\"${NET_GW}\",\"dns-server\":\"${NET_DNS}\"}" > /dev/null

# Add static leases only
STATIC_COUNT=$(jqc '[.dhcp.leases[] | select(.dynamic == "false")] | length')
log "Adding ${STATIC_COUNT} static DHCP leases"
jqc -c '.dhcp.leases[] | select(.dynamic == "false")' | while IFS= read -r lease; do
  payload=$(echo "$lease" | jq 'del(.".id",.dynamic,.status,."expires-after",
    ."active-address",."active-mac-address",."active-client-id",.age,."last-seen",.radius)')
  put /ip/dhcp-server/lease "$payload" > /dev/null
done
log "  ${STATIC_COUNT} static leases added"

# ---------------------------------------------------------------------------
log ""
log "=== Provisioning complete ==="
FINAL_ID=$(get /system/identity | jq -r '.name')
ROS_VER=$(get /system/resource | jq -r '.version')
log "Router: ${FINAL_ID} — ROS ${ROS_VER}"
log ""
log "Next steps:"
log "  1. Verify config via the web UI or further API queries"
log "  2. When ready to cut over:"
log "     a. Unplug current router (192.168.1.1)"
log "     b. Plug ether2 into ISP/modem"
log "     c. Plug switch cable into ether1 (2.5G) or ether3-5"
log "     d. Remove management IP: DELETE /rest/ip/address/<id-of-192.168.1.251>"
log "     e. The router will answer on 192.168.1.1 from bridgeLocal"
