#!/bin/bash
# OpenBao recovery drill (design doc 27.1; first passed 2026-09-28 as plan block E) (acceptance criterion "Backup", design doc 27.1).
# Proves: newest NAS Raft snapshot + offline seal key (USB B) + recovery key
# (kit) are enough to get the secrets back, on a fresh OpenBao.
#
# Throwaway LXC 20099 on pve: NO network, OpenBao listens on 127.0.0.1 only,
# destroyed at the end. Only hashes and counts are printed.
# Test-only deviation from production: the scratch listener re-enables the
# legacy unauthenticated generate-root endpoints, because the breakglass
# AppRole is bound to the workstation LAN and this container has no network.
#
# Prereqs: USB B (SanDisk, label BAOSEAL-B) plugged into pve; repo root as cwd.
# Run:  bash scripts/openbao-recovery-test.sh
# Prompts once (hidden) for OPENBAO_RECOVERY_KEY (from the Bitwarden kit note).
# shellcheck disable=SC2029  # client-side expansion into ssh commands is intended
set -euo pipefail
PVE=root@pve.gibbsgreatly.xyz
CT=20099
TGZ_URL=https://github.com/openbao/openbao/releases/download/v2.7.0/openbao_2.7.0_linux_amd64.tar.gz
TGZ_SHA=c3ab5de9e778223445487ccbfb16c291bf491642b688f3a3df5aeba23d9b3667
cx() { ssh -o BatchMode=yes "$PVE" "pct exec $CT -- env PATH=/usr/local/bin:/usr/bin:/bin BAO_ADDR=http://127.0.0.1:8200 $*"; }

echo "== preflight"
ssh "$PVE" "ls /dev/disk/by-id/ | grep -q 'usb-SanDisk_Cruzer_Blade_432171079EA39474-0:0-part1'" || { echo "USB B not plugged into pve" >&2; exit 1; }
ssh "$PVE" "pct status $CT >/dev/null 2>&1" && { echo "CT $CT already exists -- remove it first" >&2; exit 1; }
SNAP=$(ssh "$PVE" 'ls -1 /mnt/nas-backup/openbao-snapshots/openbao-*.snap | sort | tail -1')
echo "snapshot: $(basename "$SNAP")"
LIVE_HASH=$(./with-secrets-prod python3 -c 'import hashlib,os; print(hashlib.sha256(os.environ["GRAYLOG_ROOT_PASSWORD"].encode()).hexdigest())')
read -r -s -p "OPENBAO_RECOVERY_KEY: " RK; echo

cleanup() {
  echo "== cleanup"
  ssh "$PVE" "pct stop $CT >/dev/null 2>&1; pct destroy $CT --purge >/dev/null 2>&1; umount /mnt/usb-b 2>/dev/null; rm -f /tmp/openbao-rt.tgz /tmp/openbao-rt-bao; echo 'CT $CT destroyed'" || true
}
trap cleanup EXIT

echo "== create isolated CT $CT (no network)"
ssh "$PVE" "pct create $CT local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst --hostname openbao-recovery-test --unprivileged 1 --storage apps-containers --rootfs apps-containers:4 --memory 1024 --cores 1 --start 1 >/dev/null && sleep 5 && pct status $CT"

echo "== install bao (checksum-pinned tarball)"
ssh "$PVE" "curl -fsSLo /tmp/openbao-rt.tgz $TGZ_URL && echo '$TGZ_SHA  /tmp/openbao-rt.tgz' | sha256sum -c --quiet && tar -xzf /tmp/openbao-rt.tgz -C /tmp bao && mv /tmp/bao /tmp/openbao-rt-bao && pct push $CT /tmp/openbao-rt-bao /usr/local/bin/bao --perms 0755"

echo "== seal key from USB B + snapshot from NAS"
ssh "$PVE" "mkdir -p /mnt/usb-b && mount -o ro LABEL=BAOSEAL-B /mnt/usb-b && pct exec $CT -- mkdir -p /srv/openbao-seal /opt/openbao/data && pct push $CT /mnt/usb-b/homelab-2026-1.key /srv/openbao-seal/homelab-2026-1.key --perms 0400 && umount /mnt/usb-b && pct push $CT '$SNAP' /root/restore.snap"

echo "== config + start"
ssh "$PVE" "pct exec $CT -- sh -c 'cat > /etc/openbao-rt.hcl'" <<'HCL'
api_addr      = "http://127.0.0.1:8200"
cluster_addr  = "http://127.0.0.1:8201"
disable_mlock = true
storage "raft" {
  path    = "/opt/openbao/data"
  node_id = "openbao-recovery-test"
}
listener "tcp" {
  address         = "127.0.0.1:8200"
  cluster_address = "127.0.0.1:8201"
  tls_disable     = 1
  # TEST ONLY (no network, localhost listener): legacy unauth generate-root.
  disable_unauthed_generate_root_endpoints = false
}
seal "static" {
  current_key_id = "homelab-2026-1"
  current_key    = "file:///srv/openbao-seal/homelab-2026-1.key"
}
HCL
ssh "$PVE" "pct exec $CT -- systemd-run --unit openbao-rt /usr/local/bin/bao server -config=/etc/openbao-rt.hcl >/dev/null"
wait_rc() {  # wait until `bao status` exits with one of the given codes (0 unsealed, 2 sealed)
  local want="$1" rc
  for _ in $(seq 1 30); do
    rc=0; cx "bao status" >/dev/null 2>&1 || rc=$?
    [[ " $want " == *" $rc "* ]] && return 0
    sleep 1
  done
  echo "OpenBao did not reach status code(s) $want (last $rc). Diagnostics:" >&2
  cx "bao status" >&2 || true
  ssh -o BatchMode=yes "$PVE" "pct exec $CT -- journalctl -u openbao-rt -n 25 --no-pager -o cat" >&2 || true
  return 1
}
wait_rc "0 2"

echo "== init fresh instance, then restore the snapshot over it"
T0=$(cx "bao operator init -recovery-shares=1 -recovery-threshold=1 -format=json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["root_token"])')
wait_rc 0     # static seal auto-unseals the fresh instance
cx "BAO_TOKEN=$T0 bao operator raft snapshot restore -force /root/restore.snap"
unset T0
sleep 3
wait_rc 0     # restored data is sealed by the same key generation, so it auto-unseals again
cx "bao status -format=json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("after restore: initialized", d["initialized"], "sealed", d["sealed"])'

echo "== recover a root token with the ORIGINAL recovery key (from the kit)"
ATT=$(cx "bao write -format=json -f sys/generate-root/attempt")
NONCE=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print((d.get("data") or d)["nonce"])' "$ATT")
OTP=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print((d.get("data") or d).get("otp") or "")' "$ATT")
[[ -n "$OTP" ]] || { echo "server did not return an OTP for the legacy generate-root attempt" >&2; exit 1; }
UPD=$(printf '%s' "$RK" | ssh -o BatchMode=yes "$PVE" "pct exec $CT -- env PATH=/usr/local/bin:/usr/bin:/bin BAO_ADDR=http://127.0.0.1:8200 bao write -format=json sys/generate-root/update nonce=$NONCE key=-")
unset RK
ENC=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); d=d.get("data") or d; print(d.get("encoded_token") or d.get("encoded_root_token") or "")' "$UPD")
[[ -n "$ENC" ]] || { echo "recovery key did not complete root generation" >&2; exit 1; }
# Decode locally: `bao operator generate-root -decode` first calls the
# authenticated status endpoint (403 without a token), but decoding is just
# base64(token XOR otp). Throwaway-instance token only.
ROOT=$(python3 -c '
import base64, sys
enc, otp = sys.argv[1], sys.argv[2].encode()
raw = None
for dec in (base64.b64decode, base64.urlsafe_b64decode):
    try:
        raw = dec(enc + "=" * (-len(enc) % 4)); break
    except Exception:
        pass
if raw is None or len(raw) != len(otp):
    sys.exit(f"cannot decode (enc {len(raw) if raw else 0} bytes, otp {len(otp)} bytes)")
print(bytes(a ^ b for a, b in zip(raw, otp)).decode())' "$ENC" "$OTP")
cx "BAO_TOKEN=$ROOT bao token lookup -format=json" | python3 -c 'import json,sys; print("recovered token policies:", json.load(sys.stdin)["data"]["policies"])'

echo "== compare restored data with live"
ENTRIES=$(cx "BAO_TOKEN=$ROOT bao kv list -mount=kv -format=json services" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
REST_HASH=$(cx "BAO_TOKEN=$ROOT bao kv get -mount=kv -field=GRAYLOG_ROOT_PASSWORD services/graylog" | tr -d '\n' | sha256sum | cut -d' ' -f1)
echo "restored services/* entries: $ENTRIES (expect 22)"
echo "GRAYLOG_ROOT_PASSWORD sha256 restored: ${REST_HASH:0:16}...  live: ${LIVE_HASH:0:16}..."
if [[ "$REST_HASH" == "$LIVE_HASH" && "$ENTRIES" -eq 22 ]]; then
  echo "RECOVERY TEST: PASS"
else
  echo "RECOVERY TEST: FAIL" >&2; exit 1
fi
