#!/usr/bin/env bash
# Method-B rehearsal for the pve-tiny return (docs/pve-tiny-evacuation/return-plan.md, R2).
#
# Backs up one running pve CT to the pbs-usb-staging storage, restores it on
# pve-tiny as a throwaway CT with NO network, compares a parity manifest of
# source and copy, then removes the copy and the staging snapshot.
#
# Run from the operator workstation (SSH to root on both nodes). Nothing is
# copied between sessions by hand: the snapshot is found by listing the
# staging storage, which this script requires to hold no snapshot of the
# guest beforehand.
#
#   scripts/pve-tiny-return-rehearsal.sh --dry-run 50012   # read-only checks
#   scripts/pve-tiny-return-rehearsal.sh 50012             # run the rehearsal
#   scripts/pve-tiny-return-rehearsal.sh --use-existing 50012  # step 1 already done by hand
#   scripts/pve-tiny-return-rehearsal.sh --cleanup-only 50012
set -euo pipefail

PVE=root@pve.gibbsgreatly.xyz
TINY=root@pve-tiny.gibbsgreatly.xyz
STAGING=pbs-usb-staging
NS=return-staging
PBS_REPO=root@pam@192.168.1.12:usb-backup
RESTORE_STORAGE=nvme-lvm

mode=run
existing=0
while [[ ${1:-} == --* ]]; do
  case $1 in
    --dry-run) mode=dry ;;
    --cleanup-only) mode=cleanup ;;
    --use-existing) existing=1 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
SRC=${1:?usage: $0 [--dry-run|--cleanup-only] <vmid>}
[[ $SRC =~ ^[0-9]+$ ]] || { echo "vmid must be numeric" >&2; exit 2; }
TEST=9$SRC

p()  { ssh -o BatchMode=yes "$PVE" "$@"; }
t()  { ssh -o BatchMode=yes "$TINY" "$@"; }
say() { printf '\n== %s\n' "$*"; }
die() { echo "STOP: $*" >&2; exit 1; }

# Source side: single snapshot of $SRC in the staging storage, newest first.
staged_volids() {
  p "pvesm list $STAGING --vmid $SRC 2>/dev/null | awk 'NR>1{print \$1}' | sort"
}

cleanup() {
  say "cleanup: test CT $TEST and staging snapshot(s) of $SRC"
  if t "test -e /etc/pve/lxc/$TEST.conf"; then
    t "pct stop $TEST 2>/dev/null || true; pct destroy $TEST --purge"
  else
    echo "test CT $TEST already absent"
  fi
  local v ts
  for v in $(staged_volids); do
    ts=${v##*/}
    t "export PBS_PASSWORD=\"\$(cat /etc/pve/priv/storage/pbs-iscsi.pw)\" PBS_REPOSITORY=$PBS_REPO;
       proxmox-backup-client forget ct/$SRC/$ts --ns $NS"
  done
  [[ -z $(staged_volids) ]] || die "staging snapshot of $SRC still present"
  t "test ! -e /etc/pve/lxc/$TEST.conf" || die "test CT $TEST still present"
  echo "cleanup verified: no test CT, no staging snapshot"
}

preflight() {
  say "preflight (read-only)"
  [[ $(p "hostname") == pve ]] || die "first host is not pve"
  [[ $(t "hostname") == pve-tiny ]] || die "second host is not pve-tiny"
  p "pct status $SRC" | grep -q running || die "source CT $SRC is not running on pve"
  p "pvesm status | awk '\$1==\"$STAGING\"{print \$3}'" | grep -q active || die "$STAGING not active on pve"
  t "pvesm status | awk '\$1==\"$STAGING\"{print \$3}'" | grep -q active || die "$STAGING not active on pve-tiny"
  t "pvesm status | awk '\$1==\"$RESTORE_STORAGE\"{print \$3}'" | grep -q active || die "$RESTORE_STORAGE not active on pve-tiny"
  t "test ! -e /etc/pve/lxc/$TEST.conf" || die "test VMID $TEST already exists on pve-tiny"
  p "test ! -e /etc/pve/lxc/$TEST.conf && ! pct status $TEST >/dev/null 2>&1" || die "test VMID $TEST exists on pve"
  if (( existing )); then
    [[ $(staged_volids | wc -l) -eq 1 ]] || die "--use-existing needs exactly one staged snapshot of $SRC"
    echo "using existing snapshot: $(staged_volids)"
  else
    [[ -z $(staged_volids) ]] || die "staging already holds a snapshot of $SRC; use --use-existing or --cleanup-only"
  fi
  echo "source: $(p "pct config $SRC | grep -E '^(hostname|rootfs|mp0)'" | tr '\n' ' ')"
  echo "OK: all preflight checks passed"
}

manifest() { # stdin script for the guest
  cat <<'EOF'
systemctl list-unit-files --state=enabled --no-legend | awk '{print $1}' | sort
echo ---volumes
docker volume ls -q 2>/dev/null | sort
echo ---dirs
ls /opt /srv /usr/local/bin 2>/dev/null | sort
echo ---etc
ls /etc | sort
EOF
}

case $mode in
  cleanup) cleanup; exit 0 ;;
  dry) preflight; echo "(dry run: nothing changed)"; exit 0 ;;
esac

preflight
trap 'echo; echo "FAILED. Test CT may remain; run: $0 --cleanup-only $SRC" >&2' ERR

say "1/5 backup of running CT $SRC to $STAGING (snapshot mode, no downtime)"
b0=$(date +%s)
if (( existing )); then
  echo "skipped: using the snapshot taken earlier"
else
  p "vzdump $SRC --storage $STAGING --mode snapshot --notes-template 'R2 rehearsal {{guestname}}'" 2>&1 | tail -8
fi
b1=$(date +%s)
vols=$(staged_volids)
[[ $(wc -l <<<"$vols") -eq 1 && -n $vols ]] || die "expected exactly one staged snapshot, got: $vols"
VOLID=$vols
echo "snapshot: $VOLID"
p "pvesm list $STAGING --vmid $SRC | awk 'NR>1{printf \"size: %.2f GiB\\n\", \$4/1073741824}'"

say "2/5 restore on pve-tiny as $TEST (no network)"
r0=$(date +%s)
t "pct restore $TEST $VOLID --storage $RESTORE_STORAGE --unprivileged 1" 2>&1 | tail -5
r1=$(date +%s)
echo "restore took $((r1 - r0))s"
t "pct set $TEST --delete net0 --onboot 0 --hostname r2-rehearsal --tags r2-rehearsal"
if t "pct config $TEST | grep -q '^net[0-9]'"; then
  die "test CT $TEST still has a network interface; not starting it"
fi
echo "verified: $TEST has no network interface, onboot=0"

say "3/5 start test CT"
t "pct start $TEST"
for _ in $(seq 1 30); do
  if t "pct exec $TEST -- true" 2>/dev/null; then break; fi
  sleep 2
done
t "pct status $TEST"

say "4/5 parity manifest: source vs copy"
srcf=$(mktemp -t r2-src.XXXXXX); cpyf=$(mktemp -t r2-copy.XXXXXX)
manifest | p "pct exec $SRC -- bash -s" >"$srcf"
manifest | t "pct exec $TEST -- bash -s" >"$cpyf"
echo "manifest lines: source $(wc -l <"$srcf"), copy $(wc -l <"$cpyf")"
if diff -u "$srcf" "$cpyf"; then
  echo "PARITY-OK"
else
  echo "PARITY-DIFF above: review before trusting the method (nothing is cleaned up until you say so)" >&2
fi
rm -f "$srcf" "$cpyf"

say "5/5 cleanup"
trap - ERR
cleanup

say "result"
if (( existing )); then bt="not measured here"; else bt="$((b1 - b0))s"; fi
echo "backup: $bt, restore: $((r1 - r0))s; record these in return-plan.md (sizing)"
