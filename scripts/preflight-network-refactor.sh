#!/usr/bin/env bash
# scripts/preflight-network-refactor.sh
#
# Network refactor preflight checks.
#
# Verifies that the router-centric provisioning prerequisites are in place
# before running a Terraform apply, teardown, or redeploy against pve-test.
#
# Usage:
#   ./with-secrets scripts/preflight-network-refactor.sh [OPTIONS] [GUEST_IP...]
#
# Options:
#   --save-evidence FILE   Write a copy of the output to FILE (timestamped by
#                          default when FILE is a directory).
#   --no-colour            Disable ANSI colour codes (useful for log capture).
#   --help                 Show this help.
#
# Positional arguments (optional):
#   GUEST_IP...   One or more representative guest IPs to probe on TCP:22.
#                 If none are given, a default candidate list is tried.
#                 At least one must be reachable for the check to pass.
#
# Expected invocation:
#   ./with-secrets scripts/preflight-network-refactor.sh
#   ./with-secrets scripts/preflight-network-refactor.sh 192.168.40.11 192.168.30.10
#   ./with-secrets scripts/preflight-network-refactor.sh \
#       --save-evidence docs/sessions/evidence/ 192.168.40.11
#
# Exit codes:
#   0  All required checks passed.
#   1  One or more required checks failed.
#
# This script is read-only and non-destructive.
# Reference: docs/network-refactor/validation-gate.md

set -euo pipefail

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
_COLOUR=true
if [[ ! -t 1 ]]; then _COLOUR=false; fi

# shellcheck disable=SC2015  # || true intentional: always succeed whether colour is on or off
colour_on()  { [[ "$_COLOUR" == true ]] && printf '%b' "$1" || true; }
RED=$(    colour_on '\033[0;31m')
GREEN=$(  colour_on '\033[0;32m')
YELLOW=$( colour_on '\033[1;33m')
BLUE=$(   colour_on '\033[0;34m')
CYAN=$(   colour_on '\033[0;36m')
BOLD=$(   colour_on '\033[1m')
RESET=$(  colour_on '\033[0m')

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_header()  { printf '\n%s%s%s\n' "${BOLD}${CYAN}" "$1" "${RESET}"; }
log_info()    { printf '%s[INFO]%s %s\n'    "${BLUE}"   "${RESET}" "$1"; }
log_pass()    { printf '%s[PASS]%s %s\n'    "${GREEN}"  "${RESET}" "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
log_warn()    { printf '%s[WARN]%s %s\n'    "${YELLOW}" "${RESET}" "$1"; WARN_COUNT=$((WARN_COUNT + 1)); }
log_fail()    { printf '%s[FAIL]%s %s\n'    "${RED}"    "${RESET}" "$1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
log_sep()     { printf '%s\n' "----------------------------------------------------------------------"; }
log_bigsep()  { printf '%s\n' "======================================================================"; }

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------
PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

# ---------------------------------------------------------------------------
# Evidence capture
# ---------------------------------------------------------------------------
EVIDENCE_FILE=""
EVIDENCE_LINES=()

evidence() { EVIDENCE_LINES+=("$1"); }

flush_evidence() {
    if [[ -z "$EVIDENCE_FILE" ]]; then return; fi
    printf '%s\n' "${EVIDENCE_LINES[@]}" > "$EVIDENCE_FILE"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
SAVE_EVIDENCE_ARG=""
GUEST_IPS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --save-evidence)
            SAVE_EVIDENCE_ARG="$2"; shift 2 ;;
        --no-colour)
            _COLOUR=false
            RED=""; GREEN=""; YELLOW=""; BLUE=""; CYAN=""; BOLD=""; RESET=""
            shift ;;
        --help)
            grep '^#' "$0" | grep -v '^#!/' | sed 's/^# //' | sed 's/^#//'
            exit 0 ;;
        --)
            shift; GUEST_IPS+=("$@"); break ;;
        -*)
            printf 'Unknown option: %s\n' "$1" >&2; exit 1 ;;
        *)
            GUEST_IPS+=("$1"); shift ;;
    esac
done

# ---------------------------------------------------------------------------
# Resolve evidence file path
# ---------------------------------------------------------------------------
if [[ -n "$SAVE_EVIDENCE_ARG" ]]; then
    if [[ -d "$SAVE_EVIDENCE_ARG" ]]; then
        EVIDENCE_FILE="${SAVE_EVIDENCE_ARG%/}/preflight-evidence-$(date +%Y%m%d-%H%M%S).txt"
    else
        EVIDENCE_FILE="$SAVE_EVIDENCE_ARG"
    fi
fi

# ---------------------------------------------------------------------------
# Network defaults (prefer injected env vars, then current pve-test defaults)
# ---------------------------------------------------------------------------
LAB_IP_APT_CACHER="${TF_VAR_lab_ip_apt_cacher:-${lab_ip_apt_cacher:-192.168.40.11}}"
LAB_IP_PROXY="${TF_VAR_lab_ip_proxy:-${lab_ip_proxy:-192.168.30.10}}"
LAB_IP_AUTHENTIK="${TF_VAR_lab_ip_authentik:-${lab_ip_authentik:-192.168.20.10}}"
LAB_IP_STEP_CA="${TF_VAR_lab_ip_step_ca:-${lab_ip_step_ca:-192.168.20.11}}"
LAB_IP_MONITORING="${TF_VAR_lab_ip_monitoring:-${lab_ip_monitoring:-192.168.20.12}}"
LAB_IP_HARBOR="${TF_VAR_lab_ip_harbor:-${lab_ip_harbor:-192.168.40.10}}"
LAB_IP_CI_RUNNER="${TF_VAR_lab_ip_ci_runner:-${lab_ip_ci_runner:-192.168.10.63}}"

LAB_GW_BUILD="${TF_VAR_lab_gw_build:-${lab_gw_build:-192.168.10.1}}"
LAB_GW_MGMT="${TF_VAR_lab_gw_mgmt:-${lab_gw_mgmt:-192.168.20.1}}"
LAB_GW_EDGE="${TF_VAR_lab_gw_edge:-${lab_gw_edge:-192.168.30.1}}"
LAB_GW_INFRA="${TF_VAR_lab_gw_infra:-${lab_gw_infra:-192.168.40.1}}"

# ---------------------------------------------------------------------------
# Default representative guest candidates (probed in order, first hit wins)
# ---------------------------------------------------------------------------
DEFAULT_GUEST_CANDIDATES=(
    "${LAB_IP_APT_CACHER}"   # apt-cacher-stack (infra_seg) — usually deployed first
    "${LAB_IP_PROXY}"        # proxy-stack / Traefik (edge_seg)
    "${LAB_IP_AUTHENTIK}"    # authentik-stack (mgmt_seg)
    "${LAB_IP_STEP_CA}"      # step-ca-stack (mgmt_seg)
    "${LAB_IP_MONITORING}"   # monitoring-stack (mgmt_seg)
    "${LAB_IP_HARBOR}"       # harbor-stack (infra_seg)
    "${LAB_IP_CI_RUNNER}"    # ci-runner-01 (build_seg)
)

# Use CLI-provided IPs if given; otherwise use defaults.
if [[ ${#GUEST_IPS[@]} -eq 0 ]]; then
    GUEST_IPS=("${DEFAULT_GUEST_CANDIDATES[@]}")
    USING_DEFAULT_GUESTS=true
else
    USING_DEFAULT_GUESTS=false
fi

# ---------------------------------------------------------------------------
# SDN gateway definitions
# ---------------------------------------------------------------------------
declare -A SDN_GATEWAYS=(
    [build_seg]="${LAB_GW_BUILD}"
    [mgmt_seg]="${LAB_GW_MGMT}"
    [edge_seg]="${LAB_GW_EDGE}"
    [infra_seg]="${LAB_GW_INFRA}"
)

# Primary DNS-check gateway (mgmt_seg — resolver used by management containers)
DNS_CHECK_GATEWAY="${LAB_GW_MGMT}"

# ---------------------------------------------------------------------------
# Internal DNS name to resolve (lab zone delegated through MikroTik)
# ---------------------------------------------------------------------------
INTERNAL_DNS_NAME="traefik.lab.gibbsgreatly.xyz"
PUBLIC_DNS_NAME="github.com"

# ---------------------------------------------------------------------------
# Utility: TCP probe
# ---------------------------------------------------------------------------
tcp_probe() {
    local host="$1" port="$2" timeout="${3:-3}"
    timeout "$timeout" bash -c "</dev/tcp/${host}/${port}" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Utility: ICMP ping (1 packet, short timeout)
# ---------------------------------------------------------------------------
ping_host() {
    local host="$1"
    ping -c 1 -W 3 "$host" &>/dev/null
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
RUN_TS="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
GIT_BRANCH="$(git -C "$(dirname "$0")/.." rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
HOSTNAME_SHORT="$(hostname -s)"

evidence "======================================================================"
evidence "NETWORK REFACTOR PREFLIGHT EVIDENCE"
evidence "Run: ${RUN_TS}"
evidence "Host: ${HOSTNAME_SHORT}"
evidence "Branch: ${GIT_BRANCH}"
evidence "======================================================================"

log_bigsep
log_header "NETWORK REFACTOR PREFLIGHT"
printf '%s  Run:    %s\n'    "${BOLD}" "${RESET}${RUN_TS}"
printf '%s  Host:   %s\n'    "${BOLD}" "${RESET}${HOSTNAME_SHORT}"
printf '%s  Branch: %s\n'    "${BOLD}" "${RESET}${GIT_BRANCH}"
log_bigsep

# ---------------------------------------------------------------------------
# CHECK 1: TF_VAR_proxmox_node must equal "pve-test"
# ---------------------------------------------------------------------------
log_header "CHECK 1: TF_VAR_proxmox_node targeting guard"
log_sep
evidence ""
evidence "[CHECK 1] TF_VAR_proxmox_node targeting guard"

PROXMOX_NODE_ACTUAL="${TF_VAR_proxmox_node:-}"
log_info "TF_VAR_proxmox_node = '${PROXMOX_NODE_ACTUAL}' (expected: pve-test)"
evidence "  TF_VAR_proxmox_node = '${PROXMOX_NODE_ACTUAL}'"

if [[ "$PROXMOX_NODE_ACTUAL" == "pve-test" ]]; then
    log_pass "TF_VAR_proxmox_node is pve-test — targeting is correct"
    evidence "  Status: PASS"
else
    log_fail "TF_VAR_proxmox_node is not 'pve-test' — stop and check your environment"
    evidence "  Status: FAIL — expected pve-test, got '${PROXMOX_NODE_ACTUAL}'"
    log_info "Hint: run this script via ./with-secrets scripts/preflight-network-refactor.sh"
fi

# ---------------------------------------------------------------------------
# CHECK 2: SDN gateway reachability from workstation
# ---------------------------------------------------------------------------
log_header "CHECK 2: SDN gateway reachability"
log_sep
evidence ""
evidence "[CHECK 2] SDN gateway reachability (ICMP ping, 3 s timeout)"

GW_PASS=0
GW_FAIL=0

for zone in build_seg mgmt_seg edge_seg infra_seg; do
    gw="${SDN_GATEWAYS[$zone]}"
    log_info "Pinging ${zone} gateway ${gw} ..."
    if ping_host "$gw"; then
        log_pass "${zone} gateway ${gw} reachable"
        evidence "  ${gw} (${zone}): PASS"
        GW_PASS=$((GW_PASS + 1))
    else
        log_fail "${zone} gateway ${gw} unreachable — MikroTik VLAN interface or route may be missing"
        evidence "  ${gw} (${zone}): FAIL"
        GW_FAIL=$((GW_FAIL + 1))
    fi
done

if [[ $GW_FAIL -eq 0 ]]; then
    evidence "  Overall: PASS (all 4 gateways reachable)"
else
    evidence "  Overall: FAIL (${GW_FAIL}/4 gateways unreachable)"
fi

# ---------------------------------------------------------------------------
# CHECK 3: DNS resolution through MikroTik
# ---------------------------------------------------------------------------
log_header "CHECK 3: DNS resolution via MikroTik gateway (${DNS_CHECK_GATEWAY})"
log_sep
evidence ""
evidence "[CHECK 3] DNS resolution via MikroTik gateway ${DNS_CHECK_GATEWAY}"

DNS_PASS=0
DNS_FAIL=0

# 3a: delegated internal name
log_info "Resolving ${INTERNAL_DNS_NAME} via ${DNS_CHECK_GATEWAY} ..."
if command -v dig &>/dev/null; then
    INTERNAL_RESULT="$(dig @"${DNS_CHECK_GATEWAY}" +short +timeout=5 +tries=1 "${INTERNAL_DNS_NAME}" 2>/dev/null | grep -v '^;' | head -1 || true)"
else
    INTERNAL_RESULT=""
    log_warn "dig not found — skipping DNS checks (install bind-tools or dnsutils)"
fi

if [[ -n "$INTERNAL_RESULT" ]]; then
    log_pass "${INTERNAL_DNS_NAME} resolved to ${INTERNAL_RESULT}"
    evidence "  ${INTERNAL_DNS_NAME}: ${INTERNAL_RESULT} — PASS"
    DNS_PASS=$((DNS_PASS + 1))
else
    log_fail "${INTERNAL_DNS_NAME} did not resolve via ${DNS_CHECK_GATEWAY}"
    evidence "  ${INTERNAL_DNS_NAME}: FAIL — no answer from ${DNS_CHECK_GATEWAY}"
    DNS_FAIL=$((DNS_FAIL + 1))
fi

# 3b: public name
log_info "Resolving ${PUBLIC_DNS_NAME} via ${DNS_CHECK_GATEWAY} ..."
if command -v dig &>/dev/null; then
    PUBLIC_RESULT="$(dig @"${DNS_CHECK_GATEWAY}" +short +timeout=5 +tries=1 "${PUBLIC_DNS_NAME}" 2>/dev/null | grep -E '^[0-9]+\.' | grep -v '^;' | head -1 || true)"
else
    PUBLIC_RESULT=""
fi

if [[ -n "$PUBLIC_RESULT" ]]; then
    log_pass "${PUBLIC_DNS_NAME} resolved to ${PUBLIC_RESULT} via ${DNS_CHECK_GATEWAY}"
    evidence "  ${PUBLIC_DNS_NAME}: ${PUBLIC_RESULT} — PASS"
    DNS_PASS=$((DNS_PASS + 1))
else
    log_fail "${PUBLIC_DNS_NAME} did not resolve via ${DNS_CHECK_GATEWAY} — MikroTik DNS forwarding may be broken"
    evidence "  ${PUBLIC_DNS_NAME}: FAIL — no answer from ${DNS_CHECK_GATEWAY}"
    DNS_FAIL=$((DNS_FAIL + 1))
fi

if [[ $DNS_FAIL -eq 0 ]]; then
    evidence "  Overall: PASS"
else
    evidence "  Overall: FAIL (${DNS_FAIL} DNS checks failed)"
fi

# ---------------------------------------------------------------------------
# CHECK 4: Direct guest reachability (TCP:22)
# ---------------------------------------------------------------------------
log_header "CHECK 4: Representative guest reachability (TCP:22)"
log_sep
evidence ""
evidence "[CHECK 4] Representative guest reachability (TCP:22, 3 s timeout)"

if [[ "$USING_DEFAULT_GUESTS" == true ]]; then
    log_info "No guest IPs specified — probing default candidates:"
    log_info "  ${GUEST_IPS[*]}"
    log_info "Pass --help to see how to specify explicit IPs."
else
    log_info "Probing operator-specified guest IPs: ${GUEST_IPS[*]}"
fi

GUEST_REACHABLE=()
GUEST_UNREACHABLE=()

for ip in "${GUEST_IPS[@]}"; do
    log_info "Probing ${ip} TCP:22 ..."
    if tcp_probe "$ip" 22 3; then
        log_pass "  ${ip} TCP:22 reachable"
        evidence "  ${ip} TCP:22: PASS"
        GUEST_REACHABLE+=("$ip")
    else
        log_info "  ${ip} TCP:22 not reachable (may not be deployed)"
        evidence "  ${ip} TCP:22: unreachable (not deployed or port blocked)"
        GUEST_UNREACHABLE+=("$ip")
    fi
done

if [[ ${#GUEST_REACHABLE[@]} -ge 1 ]]; then
    log_pass "At least one guest IP is reachable: ${GUEST_REACHABLE[*]}"
    evidence "  Overall: PASS (${#GUEST_REACHABLE[@]} reachable: ${GUEST_REACHABLE[*]})"
else
    if [[ "$USING_DEFAULT_GUESTS" == true ]]; then
        log_warn "No default candidate guest IPs are currently reachable"
        log_warn "This may mean no stacks are deployed on pve-test yet — not a blocking failure"
        log_warn "Re-run with explicit IPs once a stack is deployed: scripts/preflight-network-refactor.sh ${LAB_IP_APT_CACHER}"
        evidence "  Overall: WARN — no candidate guests reachable (may not be deployed)"
        WARN_COUNT=$((WARN_COUNT + 1))
        # Don't increment FAIL_COUNT for default candidates; warn only
    else
        log_fail "None of the specified guest IPs are reachable via TCP:22"
        evidence "  Overall: FAIL — specified guests unreachable"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log_bigsep
log_header "PREFLIGHT SUMMARY"
log_sep

evidence ""
evidence "[SUMMARY]"
evidence "  Checks passed: ${PASS_COUNT}"
evidence "  Warnings:      ${WARN_COUNT}"
evidence "  Checks failed: ${FAIL_COUNT}"

printf '  %s%-20s%s %s%d%s\n' "${BOLD}" "Checks passed:"  "${RESET}" "${GREEN}" "$PASS_COUNT"  "${RESET}"
printf '  %s%-20s%s %s%d%s\n' "${BOLD}" "Warnings:"       "${RESET}" "${YELLOW}" "$WARN_COUNT" "${RESET}"
printf '  %s%-20s%s %s%d%s\n' "${BOLD}" "Checks failed:"  "${RESET}" "${RED}" "$FAIL_COUNT"    "${RESET}"
log_sep

if [[ $FAIL_COUNT -eq 0 ]]; then
    if [[ $WARN_COUNT -eq 0 ]]; then
        log_pass "All preflight checks passed — Session 7 representative stack validation may proceed."
        evidence "Verdict: PASS — Session 7 may proceed"
    else
        log_warn "Preflight passed with warnings — review warnings before proceeding."
        log_warn "Session 7 may proceed for stacks in zones whose gateways passed."
        evidence "Verdict: PASS WITH WARNINGS — review before Session 7"
    fi
else
    log_fail "One or more required preflight checks failed — do not proceed until resolved."
    evidence "Verdict: FAIL — resolve failures before Session 7"
fi

log_bigsep

# ---------------------------------------------------------------------------
# Evidence file output
# ---------------------------------------------------------------------------
if [[ -n "$EVIDENCE_FILE" ]]; then
    flush_evidence
    log_info "Evidence written to: ${EVIDENCE_FILE}"
fi

# ---------------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------------
if [[ $FAIL_COUNT -gt 0 ]]; then
    exit 1
fi
exit 0
