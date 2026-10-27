#!/usr/bin/env bash
# Restart wazuh-agent on every LXC whose agent the Wazuh manager shows as Disconnected.
#
# Why: when the manager's wazuh-remoted dies (it did on 2026-10-26 ~03:44 UTC with no log line), LXC agents
# keep a dead session, stop retrying, and stay "Disconnected" even after remoted is back (their ossec.log goes
# silent and reports "message queue is full"). A restart of the agent reconnects it immediately (verified on
# step-ca, 2026-10-27). Hosts that are not CTs on pve/pve-tiny are listed for manual handling.
#
#   scripts/wazuh-agents-restart.sh            dry run: print what would be restarted
#   scripts/wazuh-agents-restart.sh --apply    restart them, then show agent counts
set -euo pipefail

PVE=root@pve.gibbsgreatly.xyz
TINY=root@pve-tiny.gibbsgreatly.xyz
MANAGER_CT=40015          # wazuh-stack on pve
MANAGER_CONTAINER=wazuh-stack-manager
apply=0; [[ ${1:-} == --apply ]] && apply=1

ssh_() { ssh -o BatchMode=yes "$@"; }
manager() { ssh_ "$PVE" "pct exec $MANAGER_CT -- docker exec -i $MANAGER_CONTAINER $*"; }

status="$(manager /var/ossec/bin/wazuh-control status 2>&1 || true)"
grep -q 'wazuh-remoted is running' <<<"$status" || { echo "STOP: wazuh-remoted is not running on the manager; start it first (wazuh-control start)" >&2; exit 1; }

echo "== agents by status"
manager /var/ossec/bin/agent_control -l | awk -F', ' '/ID:/{print $NF}' | sort | uniq -c

mapfile -t down < <(manager /var/ossec/bin/agent_control -l | sed -nE 's/^ *ID: [0-9]+, Name: ([^,]+), IP: [^,]+, Disconnected$/\1/p' | sort -u)
echo "== Disconnected agents: ${#down[@]}"

declare -A where   # agent name -> "node vmid"
for node in pve pve-tiny; do
  host=$PVE; [[ $node == pve-tiny ]] && host=$TINY
  while read -r id name; do where[$name]="$node $id"; done < <(ssh_ "$host" "pct list | awk 'NR>1 && \$2==\"running\"{print \$1, \$NF}'")
done

manual=(); restarted=0
for name in "${down[@]}"; do
  if [[ -z ${where[$name]:-} ]]; then manual+=("$name"); continue; fi
  read -r node id <<<"${where[$name]}"
  host=$PVE; [[ $node == pve-tiny ]] && host=$TINY
  if ! ssh_ "$host" "pct exec $id -- systemctl cat wazuh-agent >/dev/null 2>&1"; then
    echo "skip   $name (CT $id on $node): no wazuh-agent installed (needs enrolment via provision)"; continue
  fi
  if (( apply )); then
    ssh_ "$host" "pct exec $id -- systemctl restart wazuh-agent" && { echo "restart $name (CT $id on $node)"; restarted=$((restarted + 1)); }
  else
    echo "would restart $name (CT $id on $node)"
  fi
done

if (( ${#manual[@]} )); then echo "== not a running CT on pve/pve-tiny (handle by hand): ${manual[*]}"; fi
if (( apply )); then
  echo "== restarted $restarted; waiting 60 s for reconnects"; sleep 60
  manager /var/ossec/bin/agent_control -l | awk -F', ' '/ID:/{print $NF}' | sort | uniq -c
else
  echo "(dry run: nothing changed; re-run with --apply)"
fi
