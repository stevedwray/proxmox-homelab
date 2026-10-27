#!/usr/bin/env bash
# Functional sweep of the eight guests returned to pve-tiny. Read-only. Prints PASS / WARN / FAIL per check
# and a summary. Safe to re-run (after re-provisions, a reboot, etc.).
#
#   scripts/pve-tiny-return-sweep.sh
set -uo pipefail

PVE=root@pve.gibbsgreatly.xyz
TINY=root@pve-tiny.gibbsgreatly.xyz
DOMAIN=lab.gibbsgreatly.xyz
GUESTS="20017 50012 50013 40072 100071 40070 20030 40014"
pass=0; warn=0; fail=0
ok()   { printf 'PASS  %s\n' "$*"; pass=$((pass + 1)); }
wr()   { printf 'WARN  %s\n' "$*"; warn=$((warn + 1)); }
bad()  { printf 'FAIL  %s\n' "$*"; fail=$((fail + 1)); }
sec()  { printf '\n== %s\n' "$*"; }
t() { ssh -o BatchMode=yes "$TINY" "$@"; }
p() { ssh -o BatchMode=yes "$PVE" "$@"; }
tin() { local id=$1; shift; t "pct exec $id -- bash -s" <<<"$*"; }   # run a script on a pve-tiny CT via stdin
pin() { local id=$1; shift; p "pct exec $id -- bash -s" <<<"$*"; }

sec "1. Placement: each guest runs on pve-tiny with autostart; the pve copy is stopped with autostart off"
for id in $GUESTS; do
  ts=$(t "pct status $id" 2>/dev/null | cut -d' ' -f2); to=$(t "pct config $id 2>/dev/null | awk '/^onboot:/{print \$2}'")
  ps=$(p "pct status $id" 2>/dev/null | cut -d' ' -f2); po=$(p "pct config $id 2>/dev/null | awk '/^onboot:/{print \$2}'")
  if [[ $ts == running && $to == 1 && $ps == stopped && ${po:-0} == 0 ]]; then ok "CT $id: tiny running onboot=1; pve $ps onboot=${po:-0}"
  else bad "CT $id: tiny=$ts onboot=${to:-?}; pve=$ps onboot=${po:-?}"; fi
done

sec "2. Health inside each guest: failed units, unhealthy or restarting containers"
for id in $GUESTS; do
  out=$(tin $id '
f=$(systemctl --failed --no-legend 2>/dev/null | wc -l)
u=$(docker ps --filter health=unhealthy --format "{{.Names}}" 2>/dev/null | tr "\n" " ")
r=$(docker ps --filter status=restarting --format "{{.Names}}" 2>/dev/null | tr "\n" " ")
s=$(docker ps --filter health=starting --format "{{.Names}}" 2>/dev/null | tr "\n" " ")
echo "$f|$u|$r|$s"')
  IFS='|' read -r f u r s <<<"$out"
  if [[ $f == 0 && -z $u && -z $r && -z $s ]]; then ok "CT $id: no failed units, no unhealthy/restarting containers"
  else
    [[ $f != 0 ]] && bad "CT $id: $f failed unit(s)"
    [[ -n $u ]] && bad "CT $id: unhealthy container(s): $u"
    [[ -n $r ]] && bad "CT $id: restarting container(s): $r"
    [[ -n $s ]] && wr "CT $id: container(s) still 'starting': $s"
  fi
done

sec "3. DNS (20017 + the primary)"
for ip in 192.168.20.15 192.168.20.17; do
  a=$(dig +short +time=3 +tries=1 @"$ip" github.com | head -1); i=$(dig +short +time=3 +tries=1 @"$ip" harbor.$DOMAIN | head -1)
  tcp=$(dig +tcp +short +time=3 +tries=1 @"$ip" github.com | head -1)
  [[ -n $a && -n $i && -n $tcp ]] && ok "$ip answers external ($a), internal harbor ($i), and TCP" || bad "$ip DNS incomplete (ext='$a' int='$i' tcp='$tcp')"
done

sec "4. Ingress routes (through Traefik/Authentik; 200 or a redirect to login is healthy)"
for h in openwebui searxng deep-research deep-research-files cse-panel cse-panel-flower cse-panel-api cse-pentest-viewer-1 dashboards; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://$h.$DOMAIN/")
  case $code in 200|301|302|303|307|401) ok "https://$h.$DOMAIN -> $code";; *) bad "https://$h.$DOMAIN -> $code";; esac
done

sec "5. Functional paths"
# ai-services
c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://192.168.50.11:8082/search?q=test\&format=json)
[[ $c == 200 ]] && ok "SearXNG JSON search -> 200" || wr "SearXNG JSON search -> $c (format=json may be disabled)"
c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://192.168.50.11:8081/); [[ $c == 200 ]] && ok "OpenWebUI :8081 -> 200" || bad "OpenWebUI :8081 -> $c"
r=$(tin 50013 '/usr/local/bin/eval-run results 2>&1 | grep -c "^  bfcl-\|^  agentbench-\|^  gemma4-26b:"')
[[ ${r:-0} -ge 10 ]] && ok "eval-run results shows the historical set ($r historical rows)" || bad "eval-run historical set missing or short ($r rows)"
# panel + framework
fw=$(curl -s --max-time 10 http://192.168.20.30:8000/framework)
chk=$(grep -oE '"checked":"[^"]+"' <<<"$fw" | head -1 | cut -d'"' -f4)
if [[ -n $chk ]]; then age=$(( $(date -u +%s) - $(date -u -d "$chk" +%s) )); (( age < 600 )) && ok "panel /framework fresh (checked ${age}s ago; model $(grep -oE '"model":"[^"]+"' <<<"$fw" | cut -d'"' -f4))" || wr "panel /framework last checked ${age}s ago"
else bad "panel /framework returned no 'checked'"; fi
# Celery workers via the new Redis
w=$(tin 20030 'docker exec cse-panel-flower sh -c "celery -b \"\$CELERY_BROKER_URL\" inspect ping -t 10 --json" 2>&1 | grep -oE "\"[a-z]+@[A-Za-z0-9._-]+\"" | sort -u | wc -l')
[[ $w == 5 ]] && ok "5 Celery workers answer through the new Redis" || bad "$w Celery worker(s) answer (expected 5)"
# controller -> runner
r=$(tin 40070 'ssh -i /srv/pentest-worker/id_pentest_runner -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/tmp/sweep-kh root@192.168.100.72 echo ok 2>&1 | tail -1')
[[ $r == ok ]] && ok "controller -> pentest-runner SSH works" || bad "controller -> runner SSH: $r"
h=$(tin 40072 'curl -s --max-time 8 http://192.168.100.72:18820/healthz'); grep -q '"ok": *true' <<<"$h" && ok "pentest-runner viewer healthz ok" || bad "runner healthz: $h"
# code-eval
g=$(tin 100071 'docker exec cse-code-eval gcc --version 2>&1 | head -1'); [[ $g == gcc* ]] && ok "code-eval toolchain: $g" || bad "code-eval gcc: $g"
# opensearch
os=$(tin 40014 'docker exec opensearch-stack-opensearch sh -c '"'"'curl -sk --max-time 15 -u "admin:$OPENSEARCH_INITIAL_ADMIN_PASSWORD" https://localhost:9200/_cluster/health'"'"' | grep -oE "\"status\":\"[a-z]+\""')
case $os in *green*|*yellow*) ok "OpenSearch cluster $os";; *) bad "OpenSearch health: ${os:-no answer}";; esac
# secpipe
r=$(tin 50012 'systemctl show tpot-findings-ingest.service -p Result --value; systemctl list-timers --no-legend | grep -c "tpot\|cve-deep"')
res=$(head -1 <<<"$r"); [[ $res == success ]] && ok "secpipe tpot ingest last result: success" || bad "secpipe tpot ingest result: $res"
en=$(tin 50012 'systemctl is-enabled cve-enrichment-sync.timer 2>&1'); [[ $en == disabled ]] && ok "cve-enrichment-sync.timer is disabled (as requested)" || wr "cve-enrichment-sync.timer is $en"

sec "6. Cross-zone reachability that the node_exporter TLS and the controller depend on"
for id in 50012 50013 40072 100071 40070 40014; do
  c=$(tin $id 'curl -sk -o /dev/null -w "%{http_code}" --max-time 6 https://192.168.20.11/health || echo timeout')
  [[ $c == 200 ]] && ok "CT $id -> step-ca :443 -> 200" || bad "CT $id -> step-ca :443 -> $c"
done

sec "7. Wazuh"
cnt=$(p 'pct exec 40015 -- docker exec -i wazuh-stack-manager /var/ossec/bin/agent_control -l' 2>/dev/null | awk -F', ' '/ID:/{print $NF}' | sort | uniq -c | tr -s ' ' | tr '\n' ';')
rem=$(p 'pct exec 40015 -- docker exec -i wazuh-stack-manager /var/ossec/bin/wazuh-control status' 2>/dev/null | grep -c 'remoted is running')
[[ $rem == 1 ]] && ok "wazuh-remoted running" || bad "wazuh-remoted NOT running"
echo "      agents:$cnt"
dis=$(grep -oE '[0-9]+ Disconnected' <<<"$(p 'pct exec 40015 -- docker exec -i wazuh-stack-manager /var/ossec/bin/agent_control -l' 2>/dev/null | awk -F', ' '/ID:/{print $NF}' | sort | uniq -c)" | cut -d' ' -f1)
(( ${dis:-0} <= 8 )) && ok "Disconnected agents: ${dis:-0}" || wr "Disconnected agents: ${dis:-0} (restarts may still be running)"

sec "8. Capacity and pve side"
t 'echo "mem: $(free -m | awk "/Mem:/{printf \"%d/%d MiB used, %d available\", \$3, \$2, \$7}")"; echo "thin pools: $(lvs --noheadings -o lv_name,data_percent pve/data nvme-lvm/nvme-lvm 2>/dev/null | tr -s " " | tr "\n" ";")"; uptime'
excl=$(p "pvesh get /cluster/backup --output-format json" | python3 -c "
import sys,json
want={'20017','20030','40014','40070','40072','50012','50013','100071'}
for j in json.load(sys.stdin):
    ex=set(str(j.get('exclude','')).split(','))
    print('yes' if want<=ex else 'no')" | head -1)
[[ $excl == yes ]] && ok "pve backup job excludes all eight stopped copies" || bad "pve backup job does not exclude all eight copies"
tj=$(t "pvesh get /cluster/backup --output-format json" | python3 -c "
import sys,json
for j in json.load(sys.stdin): print(j.get('schedule'), 'all='+str(j.get('all')), 'exclude='+str(j.get('exclude')))" | head -1)
echo "      pve-tiny backup job: $tj  (the moved guests get their first backup there; none exists yet)"

printf '\n== SUMMARY: %d pass, %d warn, %d fail\n' "$pass" "$warn" "$fail"
exit $(( fail > 0 ))
