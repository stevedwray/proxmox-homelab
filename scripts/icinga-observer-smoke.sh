#!/usr/bin/env bash
# Read-only verification of the Argon Pi Icinga/SmokePing observer
# (docs/icinga-pi-observability/). Run from the workstation:
#
#   scripts/icinga-observer-smoke.sh [group ...]
#
# Groups (default: base):
#   base       daemons, stray daemons gone, listeners, firewall, cluster link,
#              certificate validity, nothing on 0.0.0.0:80
#   dns        forward + reverse DNS for both Pis, smokeping.<lab domain> (Traefik)
#   smokeping  Traefik route (Authentik redirect) and the backend locked to Traefik
#   web        Icinga Web over HTTPS: publicly trusted (Let's Encrypt, not
#              step-ca/homelab) certificate, login page, direct (not via Traefik)
#
# Needs ssh to ansible@<pi> with passwordless sudo, dig, curl, openssl. Makes no
# changes. Exit status is the number of failed checks.
set -uo pipefail

LAB_DOMAIN="${LAB_DOMAIN:-lab.gibbsgreatly.xyz}"
A1_IP="${LAB_IP_ARGON_01:-192.168.1.22}"
A2_IP="${LAB_IP_ARGON_02:-192.168.1.23}"
A1_FQDN="${LAB_FQDN_ARGON_01:-argon-01.gibbsgreatly.xyz}"
A2_FQDN="${LAB_FQDN_ARGON_02:-argon-02.gibbsgreatly.xyz}"
DNS="${LAB_IP_TECHNITIUM:-192.168.20.15}"
TRAEFIK="${LAB_IP_PROXY:-192.168.30.10}"
ICINGA_FQDN="${LAB_FQDN_ICINGA:-icinga.${LAB_DOMAIN}}"
SMOKEPING_FQDN="${LAB_FQDN_SMOKEPING:-smokeping.${LAB_DOMAIN}}"
SMOKEPING_BACKEND_PORT="${SMOKEPING_BACKEND_PORT:-8081}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new)

fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
check() { local desc=$1; shift; if "$@" >/dev/null 2>&1; then pass "$desc"; else fail "$desc"; fi; }
remote() { local ip=$1; shift; ssh "${SSH_OPTS[@]}" "ansible@${ip}" "$@" 2>/dev/null; }
tcp_open() { timeout 4 bash -c "echo > /dev/tcp/$1/$2" 2>/dev/null; }

group_base() {
  echo "base"
  local ip name
  for pair in "argon-01 ${A1_IP} ${A2_IP}" "argon-02 ${A2_IP} ${A1_IP}"; do
    set -- $pair; name=$1; ip=$2; peer=$3
    check "$name: icinga2 active" remote "$ip" 'systemctl is-active --quiet icinga2'
    check "$name: apache2 and exim4 not installed" remote "$ip" '! dpkg -s apache2 >/dev/null 2>&1 && ! dpkg -s exim4-base >/dev/null 2>&1'
    check "$name: nothing listening on :25" remote "$ip" '! ss -ltn | grep -q ":25 "'
    check "$name: nothing listening on 0.0.0.0:80 or [::]:80" remote "$ip" '! ss -ltn | grep -E "(0\.0\.0\.0|\[::\]|\*):80 "'
    check "$name: ApiListener bound to its LAN address only" remote "$ip" "ss -ltn | grep -q '${ip}:5665 '"
    check "$name: 5665 allowed from peer ${peer} only" remote "$ip" \
      "sudo iptables -S INPUT | grep -q -- '-s ${peer}/32 -p tcp -m tcp --dport 5665 -j ACCEPT' && sudo iptables -S INPUT | grep -q -- '--dport 5665 -j REJECT'"
    check "$name: node certificate verifies against the shared CA" remote "$ip" \
      "sudo openssl verify -CAfile /var/lib/icinga2/certs/ca.crt /var/lib/icinga2/certs/${name}.crt"
    check "$name: node certificate valid for more than 30 days" remote "$ip" \
      "sudo openssl x509 -checkend 2592000 -noout -in /var/lib/icinga2/certs/${name}.crt"
    check "$name: icinga2 configuration validates" remote "$ip" 'sudo icinga2 daemon -C'
    check "$name: legacy /etc/icinga2/pki removed" remote "$ip" '[ ! -e /etc/icinga2/pki ]'
    check "$name: established cluster link to peer" remote "$ip" "ss -tn state established | grep -q '${peer}'"
  done
  check "argon-01: smokeping, nginx, fcgiwrap active" remote "$A1_IP" 'systemctl is-active --quiet smokeping nginx fcgiwrap'
  if tcp_open "$A1_IP" 5665; then fail "workstation (third host) can reach ${A1_IP}:5665"; else pass "workstation (third host) refused on ${A1_IP}:5665"; fi
}

group_dns() {
  echo "dns"
  local pair fqdn ip
  for pair in "${A1_FQDN} ${A1_IP}" "${A2_FQDN} ${A2_IP}"; do
    set -- $pair; fqdn=$1; ip=$2
    check "forward ${fqdn} -> ${ip} via Technitium" bash -c "[ \"\$(dig +short +time=3 +tries=2 @${DNS} ${fqdn} A)\" = '${ip}' ]"
    check "reverse ${ip} is exactly ${fqdn}. (single PTR) via Technitium" bash -c "[ \"\$(dig +short +time=3 +tries=2 @${DNS} -x ${ip})\" = '${fqdn}.' ]"
  done
  check "forward ${SMOKEPING_FQDN} -> Traefik ${TRAEFIK}" bash -c "[ \"\$(dig +short +time=3 +tries=2 @${DNS} ${SMOKEPING_FQDN} A)\" = '${TRAEFIK}' ]"
}

group_smokeping() {
  echo "smokeping"
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://${SMOKEPING_FQDN}/")
  [[ "$code" == "302" ]] && pass "https://${SMOKEPING_FQDN}/ redirects to Authentik (302)" || fail "https://${SMOKEPING_FQDN}/ returned ${code}, expected 302"
  if tcp_open "$A1_IP" "$SMOKEPING_BACKEND_PORT"; then fail "workstation can reach the backend ${A1_IP}:${SMOKEPING_BACKEND_PORT} directly"; else pass "backend ${A1_IP}:${SMOKEPING_BACKEND_PORT} not reachable from the workstation (Traefik only)"; fi
  check "firewall: ${SMOKEPING_BACKEND_PORT} allowed from Traefik ${TRAEFIK} only" remote "$A1_IP" \
    "sudo iptables -S INPUT | grep -q -- '-s ${TRAEFIK}/32 -p tcp -m tcp --dport ${SMOKEPING_BACKEND_PORT} -j ACCEPT' && sudo iptables -S INPUT | grep -q -- '--dport ${SMOKEPING_BACKEND_PORT} -j REJECT'"
  check "smokeping CGI answers on argon-01 itself" remote "$A1_IP" "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://${A1_IP}:${SMOKEPING_BACKEND_PORT}/smokeping/smokeping.cgi | grep -q 200"
}

group_web() {
  echo "web"
  local issuer code
  check "forward ${ICINGA_FQDN} -> ${A1_IP} via Technitium" bash -c "[ \"\$(dig +short +time=3 +tries=2 @${DNS} ${ICINGA_FQDN} A)\" = '${A1_IP}' ]"
  issuer=$(echo | openssl s_client -connect "${A1_IP}:443" -servername "${ICINGA_FQDN}" 2>/dev/null | openssl x509 -noout -issuer 2>/dev/null)
  if echo "$issuer" | grep -qi "Let's Encrypt"; then pass "certificate issuer is Let's Encrypt (${issuer#issuer=})"; else fail "certificate issuer is not Let's Encrypt: ${issuer:-none}"; fi
  if echo "$issuer" | grep -qi "homelab"; then fail "certificate chains to the homelab/step-ca CA (browser-facing certs must be Let's Encrypt)"; else pass "no step-ca certificate on the browser-facing endpoint"; fi
  check "certificate verifies with the system trust store for ${ICINGA_FQDN}" bash -c "curl -s -o /dev/null --max-time 10 --resolve ${ICINGA_FQDN}:443:${A1_IP} https://${ICINGA_FQDN}/"
  code=$(curl -sL --cookie '' -o /dev/null -w '%{http_code}' --max-time 10 --resolve "${ICINGA_FQDN}:443:${A1_IP}" "https://${ICINGA_FQDN}/icingaweb2/authentication/login")
  [[ "$code" == "200" ]] && pass "login page returns 200" || fail "login page returned ${code}"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve "${ICINGA_FQDN}:80:${A1_IP}" "http://${ICINGA_FQDN}/")
  [[ "$code" == "301" ]] && pass "http redirects to https (301)" || fail "http returned ${code}, expected 301"
  check "served directly by argon-01, not Traefik (${ICINGA_FQDN} resolves to ${A1_IP})" bash -c "[ \"\$(dig +short @${DNS} ${ICINGA_FQDN} A)\" = '${A1_IP}' ]"
  check "icingadb, mariadb, redis, php-fpm active" remote "$A1_IP" 'systemctl is-active --quiet icingadb mariadb redis-server php*-fpm'
  check "certbot renewal timer active" remote "$A1_IP" 'systemctl is-active --quiet certbot.timer'
  check "certificate valid for more than 30 days" bash -c "echo | openssl s_client -connect ${A1_IP}:443 -servername ${ICINGA_FQDN} 2>/dev/null | openssl x509 -noout -checkend 2592000"
  check "MariaDB and Redis listen on loopback/socket only" remote "$A1_IP" '! ss -ltn | grep -E "(0\.0\.0\.0|\[::\]|\*):(3306|6379) "'
}

groups=("$@"); [[ ${#groups[@]} -eq 0 ]] && groups=(base)
for g in "${groups[@]}"; do
  case "$g" in base|dns|smokeping|web) "group_$g" ;; *) echo "unknown group: $g" >&2; exit 2 ;; esac
done
echo; [[ $fails -eq 0 ]] && echo "all checks passed" || echo "${fails} check(s) FAILED"
exit "$fails"
