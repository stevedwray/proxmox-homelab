#!/usr/bin/env bash
# Create a read-only (PVEAuditor) API token on pve-tiny and store it in OpenBao
# WITHOUT ever printing the secret: it exists only in shell variables between the
# Proxmox API response and the OpenBao write (openbao_write.py reads values from
# stdin when it is not a TTY).
#
#   export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
#   export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
#   scripts/pve-tiny-readonly-token.sh --check     # read-only: what exists, what would happen
#   scripts/pve-tiny-readonly-token.sh             # create + store
#   scripts/pve-tiny-readonly-token.sh --also-host-entry   # also write hosts/pve-tiny (catch-up 13.7)
#   unset BAO_TOKEN
#
# Creates user netbox-ro@pve and token netbox-ro@pve!readonly (privsep, PVEAuditor
# on both user and token -- effective rights are the intersection). It uses the
# pve-tiny deploy token (Administrator) through ./with-secrets-prod-tiny. If the
# token already exists its secret is unrecoverable: remove it first with
#   pveum user token remove netbox-ro@pve readonly
# Stored as services/netbox PVE_TINY_READONLY_TOKEN_ID/SECRET (the pve deploy profile
# cannot read hosts/pve-tiny). Add the field names to secrets/manifest.json only
# AFTER this succeeds -- the loader fails closed on fields missing from OpenBao.
set -euo pipefail

if [[ "${1:-}" == "--inner" ]]; then
  # Runs inside ./with-secrets-prod-tiny. stdout carries one sentinel line, nothing else secret.
  python3 -I - "${2:-}" <<'PY'
import json, os, ssl, sys, urllib.error, urllib.parse, urllib.request

CHECK = sys.argv[1] == "--check"
USER, TOKEN, ROLE = "netbox-ro@pve", "readonly", "PVEAuditor"
BASE = os.environ["TF_VAR_proxmox_api_url"].rstrip("/")
if not BASE.endswith("/api2/json"):
    BASE += "/api2/json"
NODE = os.environ["TF_VAR_proxmox_node"]
ADMIN = f"PVEAPIToken={os.environ['TF_VAR_pm_api_token_id']}={os.environ['TF_VAR_pm_api_token_secret']}"
CTX = ssl._create_unverified_context()  # node uses Proxmox's own self-signed cert; LAN only, as populate does


def call(auth, method, path, form=None):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "{}").get("data")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


s, ver = call(ADMIN, "GET", "/version")
if s != 200:
    die(f"cannot reach {BASE} with the deploy token (HTTP {s})")
s, perms = call(ADMIN, "GET", "/access/permissions?path=/")
need = {"Permissions.Modify", "User.Modify"}
if s != 200 or not need <= set((perms or {}).get("/", {})):
    die(f"deploy token lacks {sorted(need)} on /")
s, users = call(ADMIN, "GET", "/access/users")
user_exists = any(u["userid"] == USER for u in users)
s, toks = call(ADMIN, "GET", f"/access/users/{USER}/token") if user_exists else (200, [])
token_exists = any(t["tokenid"] == TOKEN for t in (toks or []))
print(f"pve-tiny {ver['version']} node={NODE}: user {USER} exists={user_exists}, token {TOKEN} exists={token_exists}", file=sys.stderr)
if token_exists:
    die(f"{USER}!{TOKEN} already exists and its secret cannot be recovered; remove it first: "
        f"pveum user token remove {USER} {TOKEN}")
if CHECK:
    print("CHECK OK: would create user (if missing), grant PVEAuditor, create the token, verify read-only", file=sys.stderr)
    sys.exit(0)

if not user_exists:
    s, r = call(ADMIN, "POST", "/access/users", {"userid": USER, "comment": "Read-only discovery (NetBox populate, live checks)"})
    if s != 200:
        die(f"create user failed: HTTP {s} {r}")
s, r = call(ADMIN, "PUT", "/access/acl", {"path": "/", "users": USER, "roles": ROLE})
if s != 200:
    die(f"grant {ROLE} to user failed: HTTP {s} {r}")
s, r = call(ADMIN, "POST", f"/access/users/{USER}/token/{TOKEN}", {"privsep": 1, "comment": "NetBox populate / read-only checks"})
if s != 200 or not r or "value" not in r:
    die(f"create token failed: HTTP {s} {str(r)[:120]}")
full_id, secret = r["full-tokenid"], r["value"]


def drop_token(reason):
    call(ADMIN, "DELETE", f"/access/users/{USER}/token/{TOKEN}")
    die(f"{reason}; token removed again, nothing stored")


s, r = call(ADMIN, "PUT", "/access/acl", {"path": "/", "tokens": full_id, "roles": ROLE})
if s != 200:
    drop_token(f"grant {ROLE} to token failed: HTTP {s}")
RO = f"PVEAPIToken={full_id}={secret}"
s, guests = call(RO, "GET", "/cluster/resources?type=vm")
if s != 200 or not isinstance(guests, list) or not guests:
    drop_token(f"new token cannot list guests (HTTP {s})")
# A write the token must NOT be allowed (nonexistent CT, so harmless even if it were).
s, _ = call(RO, "POST", f"/nodes/{NODE}/lxc/999999999/status/stop")
if s != 403:
    drop_token(f"new token is not read-only (write probe returned HTTP {s}, expected 403)")
print(f"verified: {full_id} lists {len(guests)} guests and is refused writes (403)", file=sys.stderr)
print(f"@@TOKEN@@ {full_id} {secret}")
PY
  exit $?
fi

cd "$(dirname "$0")/.."
export TASK_APPROVAL="${TASK_APPROVAL:-pve-tiny-readonly-token}"

if [[ "${1:-}" == "--check" ]]; then
  ./with-secrets-prod-tiny "$0" --inner --check
  exit $?
fi

: "${BAO_TOKEN:?export BAO_TOKEN first: bao login -method=oidc -no-store -token-only}"
export LAB_IP_OPENBAO="${LAB_IP_OPENBAO:-192.168.20.16}"

out="$(./with-secrets-prod-tiny "$0" --inner)" || { echo "token creation failed; nothing stored" >&2; exit 1; }
line="$(printf '%s\n' "$out" | sed -n 's/^@@TOKEN@@ //p')"
unset out
[[ -n "$line" ]] || { echo "no token returned; nothing stored" >&2; exit 1; }
read -r tok_id tok_secret < <(printf '%s\n' "$line")   # process substitution: a pipe, never a temp file
unset line

store_failed() {
  echo "TOKEN CREATED BUT NOT STORED (secret is unrecoverable). Remove it and re-run:" >&2
  echo "  ssh root@pve-tiny.gibbsgreatly.xyz pveum user token remove netbox-ro@pve readonly" >&2
  exit 1
}
printf '%s\n%s\n' "$tok_id" "$tok_secret" | scripts/openbao_write.py services/netbox PVE_TINY_READONLY_TOKEN_ID PVE_TINY_READONLY_TOKEN_SECRET || store_failed
if [[ "${1:-}" == "--also-host-entry" ]]; then
  printf '%s\n%s\n' "$tok_id" "$tok_secret" | scripts/openbao_write.py hosts/pve-tiny PROXMOX_READONLY_TOKEN_ID PROXMOX_READONLY_TOKEN_SECRET || store_failed
fi
unset tok_secret
echo "stored ${tok_id} in OpenBao. Next: add the field names to secrets/manifest.json (docs/netbox-pve-tiny/README.md step 3)."
