#!/bin/bash
# Issue (or re-issue after a rebuild) the AppRole credentials OpenBao's
# clients hold. Idempotent: a SecretID that already exists is left alone.
#
#   workstation  ~/.config/openbao/deploy-<env>.{role-id,secret-id}
#                (deploy-dev plus one per node in terraform/PRODUCTION_NODES)
#   LXC          /etc/openbao-snapshot/{role-id,secret-id}  (snapshot job)
#                /etc/openbao-metrics/{role-id,secret-id}   (inventory exporter)
#
# The metrics identity is then PROVEN unable to read or change secret values
# before the exporter runs. SecretIDs go straight from `bao` into 0600 files;
# nothing is printed.
#
# Run from the repo root with an admin token exported in this shell only:
#   export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
#   export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
#   bash scripts/openbao-issue-credentials.sh
# Afterwards back up ~/.config/openbao/ to Bitwarden ("openbao deploy approles").
# The breakglass credentials are separate: see docs/reference/secrets-management.md.
set -euo pipefail
: "${BAO_TOKEN:?export an admin BAO_TOKEN in this shell first (OIDC, -no-store)}"
export BAO_ADDR="${BAO_ADDR:-https://192.168.20.16:8200}"
export BAO_CACERT="${BAO_CACERT:-$PWD/certs/homelab-root.crt}"
LXC=root@192.168.20.16

# issue ROLE DEST_DIR RUNNER: role-id always refreshed, secret-id only if missing.
# RUNNER is "local" or "ssh" (the LXC). Paths expand client-side on purpose.
# shellcheck disable=SC2029
issue() {
  local role=$1 dir=$2 where=$3 name=${4:-}
  local rid="$dir/${name}role-id" sid="$dir/${name}secret-id"
  if [[ $where == local ]]; then
    bao read -field=role_id "auth/approle/role/$role/role-id" | install -m 0600 /dev/stdin "$rid"
    if [[ -s $sid ]]; then echo "  $role: secret-id present, not re-issued"; return; fi
    bao write -f -field=secret_id "auth/approle/role/$role/secret-id" | install -m 0600 /dev/stdin "$sid"
  else
    bao read -field=role_id "auth/approle/role/$role/role-id" | ssh "$LXC" "install -m 0600 /dev/stdin $rid"
    if ssh "$LXC" "test -s $sid"; then echo "  $role: secret-id present, not re-issued"; return; fi
    bao write -f -field=secret_id "auth/approle/role/$role/secret-id" | ssh "$LXC" "install -m 0600 /dev/stdin $sid"
  fi
  echo "  $role: issued"
}

echo "== workstation deploy identities -> ~/.config/openbao/"
install -d -m 0700 ~/.config/openbao
mapfile -t nodes < <(grep -Ev '^[[:space:]]*(#|$)' terraform/PRODUCTION_NODES)
for env in dev "${nodes[@]}"; do
  issue "deploy-$env" ~/.config/openbao local "deploy-$env."
done

echo "== LXC identities"
ssh "$LXC" 'install -d -m 0700 /etc/openbao-snapshot /etc/openbao-metrics'
issue snapshot /etc/openbao-snapshot ssh
issue metrics /etc/openbao-metrics ssh

echo "== prove the metrics identity cannot read or change values (runs on the LXC)"
ssh "$LXC" 'bash -s' <<'REMOTE'
set -euo pipefail
A=https://192.168.20.16:8200; CA=/usr/local/share/ca-certificates/homelab-root.crt
BODY=$(printf '{"role_id":"%s","secret_id":"%s"}' "$(cat /etc/openbao-metrics/role-id)" "$(cat /etc/openbao-metrics/secret-id)")
TOK=$(curl -s --cacert $CA -X POST "$A/v1/auth/approle/login" -d "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["auth"]["client_token"])')
code() { curl -s -o /dev/null -w '%{http_code}' --cacert $CA -H "X-Vault-Token: $TOK" "$@"; }
fail=0
check() { if [[ $2 == "$1" ]]; then echo "  PASS $3 ($2)"; else echo "  FAIL $3 (got $2, want $1)"; fail=1; fi; }
check 403 "$(code "$A/v1/kv/data/services/graylog")"                          "read a secret VALUE (kv/data)"
check 403 "$(code -X POST "$A/v1/kv/data/services/graylog" -d '{"data":{}}')" "write a value"
check 403 "$(code -X DELETE "$A/v1/kv/metadata/services/graylog")"            "delete an entry's metadata"
check 200 "$(code -X LIST "$A/v1/kv/metadata/services")"                     "list entry names (kv/metadata)"
check 200 "$(code "$A/v1/kv/metadata/services/graylog")"                     "read version/timestamps (kv/metadata)"
curl -s -o /dev/null --cacert $CA -H "X-Vault-Token: $TOK" -X POST "$A/v1/auth/token/revoke-self"
exit $fail
REMOTE

echo "== run the snapshot job and the inventory exporter once"
ssh "$LXC" 'systemctl start openbao-snapshot@postwrite.service openbao-inventory.service \
  && journalctl -u openbao-snapshot@postwrite.service -u openbao-inventory.service -n 2 --no-pager -o cat'

echo "== boundary check"
LAB_IP_OPENBAO=192.168.20.16 python3 scripts/openbao_boundary_check.py | tail -8
echo "Done. Back up ~/.config/openbao/ to Bitwarden as 'openbao deploy approles'."
