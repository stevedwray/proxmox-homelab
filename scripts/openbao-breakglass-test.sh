#!/bin/bash
# B4 break-glass test (OpenBao >= 2.5.3 flow, design doc 19):
#   breakglass AppRole login -> generate OTP -> start attempt -> recovery key
#   -> decode root token -> prove it works -> revoke it.
# Run from the repo root:
#     bash scripts/openbao-breakglass-test.sh
# Needs ~/.config/openbao/breakglass.{role-id,secret-id} (or the kit values
# exported as OPENBAO_BREAKGLASS_ROLE_ID / OPENBAO_BREAKGLASS_SECRET_ID),
# and OPENBAO_RECOVERY_KEY pasted at the hidden prompt.
set -euo pipefail
export BAO_ADDR=https://192.168.20.16:8200
export BAO_CACERT="$PWD/certs/homelab-root.crt"
unset BAO_TOKEN

RID=${OPENBAO_BREAKGLASS_ROLE_ID:-$(cat ~/.config/openbao/breakglass.role-id)}
SID=${OPENBAO_BREAKGLASS_SECRET_ID:-$(cat ~/.config/openbao/breakglass.secret-id)}
BAO_TOKEN=$(bao write -field=token auth/approle/login role_id="$RID" secret_id=- <<<"$SID")
export BAO_TOKEN
unset RID SID
echo "logged in as breakglass (policies: $(bao token lookup -format=json | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["policies"])'))"

STATUS=$(bao operator generate-root -status -format=json)
if python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1])["started"] else 1)' "$STATUS"; then
  echo "an attempt is already in progress; cancelling it first"
  bao operator generate-root -cancel >/dev/null
fi

OTP=$(bao operator generate-root -generate-otp)
INIT=$(bao operator generate-root -init -otp="$OTP" -format=json)
NONCE=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["nonce"])' "$INIT")

read -r -s -p "OPENBAO_RECOVERY_KEY: " RK; echo
RESP=$(printf '%s' "$RK" | bao operator generate-root -nonce="$NONCE" -format=json -) \
  || { bao operator generate-root -cancel >/dev/null; echo "recovery key rejected; attempt cancelled" >&2; exit 1; }
unset RK
ENC=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("encoded_token") or d.get("encoded_root_token") or "")' "$RESP")
[[ -n "$ENC" ]] || { bao operator generate-root -cancel >/dev/null; echo "no encoded token returned; attempt cancelled" >&2; exit 1; }

TOK=$(bao operator generate-root -decode="$ENC" -otp="$OTP" 2>/dev/null | tail -1 | awk '{print $NF}')
POL=$(BAO_TOKEN="$TOK" bao token lookup -format=json | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["policies"])')
echo "break-glass root token works, policies: $POL"
BAO_TOKEN="$TOK" bao token revoke -self >/dev/null
if BAO_TOKEN="$TOK" bao token lookup >/dev/null 2>&1; then echo "UNEXPECTED: root token still valid after revoke" >&2; exit 1; fi
unset TOK ENC OTP NONCE
bao token revoke -self >/dev/null   # the breakglass AppRole token too
echo "root token and breakglass token revoked. B4 break-glass: PASS"
