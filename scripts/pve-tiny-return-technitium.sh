#!/usr/bin/env bash
# Return CT 20017 (technitium-tiny-stack, a cluster SECONDARY) from pve to pve-tiny.
# Method A: fresh Terraform target + restore of the small config volume + full provision.
# See docs/pve-tiny-evacuation/return-plan.md. Run from the operator workstation.
#
# Phases (each is idempotent and refuses to run if the previous one is not done):
#   check      read-only: both nodes, both CTs, both resolvers, free space
#   copy       pve: baseline manifest, graceful stop, onboot=0, cold copy of the config volume
#   create     pve-tiny: destroy the STALE 20017, reviewed terragrunt plan, apply
#   restore    pve-tiny: put the config volume into the new CT, start it
#   provision  full scripts/provision.sh --stack technitium-tiny-stack (pve-tiny wrapper)
#   verify     resolvers, containers, manifest vs baseline
#   rollback   destroy the pve-tiny target, restart the pve copy
#
# Approval name for every phase: pve-tiny-return-technitium
set -euo pipefail

V=20017
STACK=technitium-tiny-stack
PVE=root@pve.gibbsgreatly.xyz
TINY=root@pve-tiny.gibbsgreatly.xyz
VOL=var/lib/docker/volumes/technitium-stack_technitium-config
RET_WT=/home/steve/git/proxmox-homelab/.worktrees/pve-tiny-return
STATE=${XDG_STATE_HOME:-$HOME/.local/state}/pve-tiny-return/$V
IPS=(192.168.20.15 192.168.20.17)
export TASK_APPROVAL=pve-tiny-return-technitium

p()  { ssh -o BatchMode=yes "$PVE" "$@"; }
t()  { ssh -o BatchMode=yes "$TINY" "$@"; }
say() { printf '\n== %s\n' "$*"; }
die() { echo "STOP: $*" >&2; exit 1; }
mark() { mkdir -p "$STATE"; chmod 700 "$STATE"; date -u +%FT%TZ >"$STATE/$1.done"; }
need() { [[ -e $STATE/$1.done ]] || die "phase '$1' has not completed; run it first"; }

manifest() {
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

dig_all() {
  local ip name
  for ip in "${IPS[@]}"; do
    for name in github.com technitium-tiny.cluster.lab.gibbsgreatly.xyz; do
      printf '%s %-44s UDP: %s\n' "$ip" "$name" "$(dig +short +time=3 +tries=1 @"$ip" "$name" | head -1)"
    done
    printf '%s %-44s TCP: %s\n' "$ip" github.com "$(dig +tcp +short +time=3 +tries=1 @"$ip" github.com | head -1)"
  done
}

phase_check() {
  say "check (read-only)"
  [[ $(p hostname) == pve ]] || die "first host is not pve"
  [[ $(t hostname) == pve-tiny ]] || die "second host is not pve-tiny"
  p "pct status $V" | grep -qE 'running|stopped' || die "CT $V not on pve"
  echo "pve   CT $V: $(p "pct status $V")"
  echo "tiny  CT $V: $(t "pct status $V") (stale source; rootfs: $(t "pct config $V | grep ^rootfs"))"
  if t "pct config $V | grep -E '^(rootfs|mp[0-9]+):' | grep -q 'nvme-lvm'"; then die "stale CT $V references nvme-lvm; review by hand"; fi
  echo "tiny local-lvm free: $(t "pvesm status | awk '\$1==\"local-lvm\"{printf \"%.1f GiB\", \$6/1048576}'")"
  [[ -d $RET_WT/terraform/lxc/environments/pve-tiny/$STACK/terraform.tfstate.d ]] || die "state missing in $RET_WT"
  [[ $(git -C "$RET_WT" branch --show-current) == work/pve-tiny-return ]] || die "return worktree not on work/pve-tiny-return"
  dig_all
  echo "OK: check passed"
}

phase_copy() {
  say "copy: baseline, stop pve CT $V, cold-copy the config volume"
  mkdir -p "$STATE"; chmod 700 "$STATE"
  [[ $(p "pct status $V") == "status: running" ]] || echo "note: pve CT $V is not running (rerun after a partial copy?)"
  if p "pct status $V" | grep -q running; then
    p "pct exec $V -- test -d /$VOL/_data" || die "config volume /$VOL/_data not found in the running CT; nothing was stopped"
    manifest | p "pct exec $V -- bash -s" >"$STATE/manifest-source.txt"
    echo "baseline manifest: $(wc -l <"$STATE/manifest-source.txt") lines"
    p "pct shutdown $V --timeout 90"
  fi
  [[ $(p "pct status $V") == "status: stopped" ]] || die "pve CT $V did not stop"
  p "pct set $V --onboot 0"
  p "set -e; mkdir -p /root/salvage-$V; chmod 700 /root/salvage-$V
     pct mount $V >/dev/null; trap 'pct unmount $V' EXIT
     mp=/var/lib/lxc/$V/rootfs
     test -d \$mp/$VOL/_data || { echo 'config volume not found under the mounted CT' >&2; exit 1; }
     tar --numeric-owner --xattrs --acls -czf /root/salvage-$V/config-volume.tgz -C \$mp $VOL
     cd /root/salvage-$V && sha256sum config-volume.tgz >SHA256SUMS"
  p "cat /root/salvage-$V/config-volume.tgz" >"$STATE/config-volume.tgz"
  local remote local_
  remote=$(p "cut -d' ' -f1 /root/salvage-$V/SHA256SUMS")
  local_=$(sha256sum "$STATE/config-volume.tgz" | cut -d' ' -f1)
  [[ $remote == "$local_" ]] || die "checksum mismatch ($remote vs $local_)"
  echo "$local_  config-volume.tgz" >"$STATE/SHA256SUMS"
  echo "archive: $(du -h "$STATE/config-volume.tgz" | cut -f1), sha256 $local_ (copies: pve:/root/salvage-$V and $STATE)"
  mark copy
}

phase_create() {
  need copy
  say "create: replace the stale pve-tiny CT $V with a Terraform-created target"
  [[ $(p "pct status $V") == "status: stopped" ]] || die "pve CT $V is not stopped"
  p "pct config $V | grep -q '^onboot: 0'" || die "pve CT $V onboot is not 0"
  if t "test -e /etc/pve/lxc/$V.conf"; then
    [[ $(t "pct status $V") == "status: stopped" ]] || die "stale CT $V is running on pve-tiny"
    t "pct destroy $V --purge"
  fi
  cd "$RET_WT/terraform/lxc/environments/pve-tiny/$STACK"
  # The state's null_resource triggers hold the main checkout's paths. From this worktree they differ,
  # Terraform would REPLACE it, and its destroy-time provisioner tries to delete the SDN vnet (the
  # network_sdn_allow_destroy guard blocks it, aborting the apply). Dropping it from the worktree's
  # state copy makes the plan a plain create without running that provisioner.
  local st=terraform.tfstate.d/pve-tiny/terraform.tfstate
  if grep -q configure_network_sdn_attachment "$st"; then
    cp -p "$st" "$st.pre-sdn-staterm-$(date +%s)"
    ../../../../../with-secrets-prod-tiny terragrunt state rm -no-color 'null_resource.configure_network_sdn_attachment[0]'
  fi
  local plan
  plan=$(../../../../../with-secrets-prod-tiny terragrunt plan -lock=false -no-color 2>&1 | sed 's/^[0-9:.]* STDOUT tofu: //')
  grep -E '^  # |Plan:|Error' <<<"$plan" || true
  if grep -E '^  # null_resource.*(destroyed|replaced)|^  # module.lxc.proxmox_virtual_environment_container.*(destroyed|replaced)' <<<"$plan"; then
    die "plan would destroy/replace the SDN attachment or a container; not applying"
  fi
  read -r -p "Plan above should only CREATE CT $V (no real guest destroyed). Type yes to apply: " ans
  [[ $ans == yes ]] || die "not applied"
  ../../../../../with-secrets-prod-tiny terragrunt apply -auto-approve -no-color
  t "pct status $V" | grep -q . || die "target CT $V not present after apply"
  mark create
}

phase_restore() {
  need create
  say "restore: config volume into the new CT, then start"
  sha256sum -c "$STATE/SHA256SUMS" --quiet --status || die "local archive checksum failed"
  t "pct stop $V 2>/dev/null || true"
  ssh -o BatchMode=yes "$TINY" "set -e; pct mount $V >/dev/null; trap 'pct unmount $V' EXIT
     mp=/var/lib/lxc/$V/rootfs
     mkdir -p \$mp/var/lib/docker/volumes
     tar --numeric-owner --xattrs --acls -xzf - -C \$mp
     test -d \$mp/$VOL/_data
     du -sh \$mp/$VOL" <"$STATE/config-volume.tgz"
  t "pct start $V"
  mark restore
}

phase_provision() {
  need restore
  say "provision: full playbook for $STACK via the pve-tiny production wrapper"
  cd "$RET_WT"
  ./with-secrets-prod-tiny scripts/provision.sh --stack "$STACK"
  mark provision
}

phase_verify() {
  need provision
  say "verify"
  t "pct status $V"
  t "pct exec $V -- docker ps --format '{{.Names}} {{.Status}}'"
  dig_all
  manifest | t "pct exec $V -- bash -s" >"$STATE/manifest-target.txt"
  if diff -u "$STATE/manifest-source.txt" "$STATE/manifest-target.txt"; then
    echo "MANIFEST-PARITY-OK"
  else
    echo "MANIFEST DIFF above: review each line (new target may add wazuh-agent/unattended-upgrades, which the stale/pve copies lacked)"
  fi
  echo "Next, by hand: primary UI Administration > Cluster must show 192.168.20.17 connected; take a backup of $V; refresh known_hosts."
  mark verify
}

phase_rollback() {
  say "rollback: remove the pve-tiny target, restart the pve copy"
  if t "test -e /etc/pve/lxc/$V.conf"; then t "pct stop $V 2>/dev/null || true; pct destroy $V --purge"; fi
  p "pct set $V --onboot 1 && pct start $V"
  sleep 10
  dig_all
  rm -f "$STATE"/create.done "$STATE"/restore.done "$STATE"/provision.done "$STATE"/verify.done
}

case ${1:-} in
  check) phase_check ;;
  copy) phase_check; phase_copy ;;
  create) phase_create ;;
  restore) phase_restore ;;
  provision) phase_provision ;;
  verify) phase_verify ;;
  rollback) phase_rollback ;;
  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
