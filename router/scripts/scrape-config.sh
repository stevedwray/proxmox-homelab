#!/usr/bin/env bash
# Scrapes the current MikroTik router config via REST API and writes structured JSON.
# Usage: MIKROTIK_HOST=router.example.test MIKROTIK_USER=api-user MIKROTIK_PASSWORD=xxx ./scrape-config.sh [host]
#
# Credentials can also be sourced from SOPS:
#   eval "$(sops -d terraform/secrets.common.enc.yaml | grep MIKROTIK | sed 's/: /=/;s/^/export /')"

set -euo pipefail

HOST="${1:-${MIKROTIK_HOST:?MIKROTIK_HOST not set}}"
USER="${MIKROTIK_USER:?MIKROTIK_USER not set}"
PASS="${MIKROTIK_PASSWORD:?MIKROTIK_PASSWORD not set}"
OUT_DIR="$(cd "$(dirname "$0")/../config" && pwd)"
OUT_FILE="${OUT_DIR}/current-config.json"

BASE="https://${HOST}/rest"

get() {
  local path="$1"
  curl -sf -k -u "${USER}:${PASS}" "${BASE}${path}" 2>/dev/null || echo "null"
}

echo "Scraping MikroTik config from ${HOST} ..."

jq -n \
  --argjson system_resource    "$(get /system/resource)" \
  --argjson system_identity    "$(get /system/identity)" \
  --argjson system_ntp         "$(get /system/ntp/client)" \
  --argjson interfaces         "$(get /interface)" \
  --argjson iface_ethernet     "$(get /interface/ethernet)" \
  --argjson iface_bridge       "$(get /interface/bridge)" \
  --argjson iface_bridge_port  "$(get /interface/bridge/port)" \
  --argjson iface_vlan         "$(get /interface/vlan)" \
  --argjson iface_pppoe        "$(get /interface/pppoe-client)" \
  --argjson ip_address         "$(get /ip/address)" \
  --argjson ip_route           "$(get /ip/route)" \
  --argjson ip_pool            "$(get /ip/pool)" \
  --argjson ip_dns             "$(get /ip/dns)" \
  --argjson ip_dns_static      "$(get /ip/dns/static)" \
  --argjson ip_service         "$(get /ip/service)" \
  --argjson dhcp_server        "$(get /ip/dhcp-server)" \
  --argjson dhcp_network       "$(get /ip/dhcp-server/network)" \
  --argjson dhcp_lease         "$(get /ip/dhcp-server/lease)" \
  --argjson fw_filter          "$(get /ip/firewall/filter)" \
  --argjson fw_nat             "$(get /ip/firewall/nat)" \
  --argjson fw_mangle          "$(get /ip/firewall/mangle)" \
  --argjson fw_address_list    "$(get /ip/firewall/address-list)" \
  --argjson fw_conn_tracking   "$(get /ip/firewall/connection-tracking)" \
  --argjson ppp_profile        "$(get /ppp/profile)" \
  --argjson ipv6_address       "$(get /ipv6/address)" \
  --argjson ipv6_route         "$(get /ipv6/route)" \
  --argjson ipv6_pool          "$(get /ipv6/pool)" \
  --argjson ipv6_dhcp_client   "$(get /ipv6/dhcp-client)" \
  --argjson ipv6_dhcp_server   "$(get /ipv6/dhcp-server)" \
  --argjson ipv6_nd            "$(get /ipv6/nd)" \
  --argjson ipv6_fw_filter     "$(get /ipv6/firewall/filter)" \
  --argjson ipv6_fw_addr_list  "$(get /ipv6/firewall/address-list)" \
  --argjson wifi_iface         "$(get /interface/wifi 2>/dev/null || echo null)" \
  --argjson wifi_security      "$(get /interface/wifi/security 2>/dev/null || echo null)" \
  --argjson wifi_config        "$(get /interface/wifi/configuration 2>/dev/null || echo null)" \
  --argjson wifi_wireless      "$(get /interface/wireless 2>/dev/null || echo null)" \
  --argjson wifi_sec_profiles  "$(get /interface/wireless/security-profiles 2>/dev/null || echo null)" \
  '{
    scrape_meta: {
      host: $system_identity.name,
      scrape_time: now | todate,
      ros_version: $system_resource.version,
      board: $system_resource."board-name"
    },
    system: {
      identity: $system_identity,
      resource: $system_resource,
      ntp: $system_ntp
    },
    interfaces: {
      all: $interfaces,
      ethernet: $iface_ethernet,
      bridge: $iface_bridge,
      bridge_ports: $iface_bridge_port,
      vlan: $iface_vlan,
      pppoe_client: $iface_pppoe
    },
    ip: {
      addresses: $ip_address,
      routes: $ip_route,
      pools: $ip_pool,
      dns: $ip_dns,
      dns_static: $ip_dns_static,
      services: $ip_service
    },
    dhcp: {
      servers: $dhcp_server,
      networks: $dhcp_network,
      leases: $dhcp_lease
    },
    firewall: {
      filter: $fw_filter,
      nat: $fw_nat,
      mangle: $fw_mangle,
      address_lists: $fw_address_list,
      connection_tracking: $fw_conn_tracking
    },
    ppp: {
      profiles: $ppp_profile
    },
    ipv6: {
      addresses: $ipv6_address,
      routes: $ipv6_route,
      pools: $ipv6_pool,
      dhcp_client: $ipv6_dhcp_client,
      dhcp_server: $ipv6_dhcp_server,
      nd: $ipv6_nd,
      firewall: {
        filter: $ipv6_fw_filter,
        address_lists: $ipv6_fw_addr_list
      }
    },
    wifi: {
      interfaces: $wifi_iface,
      security_profiles: $wifi_security,
      configurations: $wifi_config,
      wireless_interfaces: $wifi_wireless,
      wireless_security_profiles: $wifi_sec_profiles
    }
  }' > "${OUT_FILE}"

echo "Written to ${OUT_FILE}"
echo "Top-level keys: $(jq 'keys[]' "${OUT_FILE}" | tr '\n' ' ')"
