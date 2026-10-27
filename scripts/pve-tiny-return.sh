#!/usr/bin/env bash
# Return one evacuated CT from pve to pve-tiny (method A: fresh Terraform target +
# restore of any listed data volumes + full provision). See
# docs/pve-tiny-evacuation/return-plan.md. Run from the operator workstation.
#
#   scripts/pve-tiny-return.sh <vmid> <phase>      guests: 20017, 50012, 50013
#
# Phases (each is idempotent and refuses to run if the previous one is not done):
#   check      read-only: both nodes, both CTs, free space, (DNS guests) resolvers
#   copy       pve: baseline manifest, graceful stop, onboot=0, cold copy of data volumes
#   create     pve-tiny: destroy a STALE CT if one exists, reviewed terragrunt plan, apply
#   restore    pve-tiny: put the data volumes into the new CT, start it
#   provision  full scripts/provision.sh --stack <stack> (pve-tiny wrapper)
#   verify     containers, units, resolvers, manifest vs baseline
#   rollback   destroy the pve-tiny target, restart the pve copy
#
# Approval name for every phase: pve-tiny-return-<stack minus "-stack">
set -euo pipefail

V=${1:?usage: $0 <vmid> <phase>}
PHASE=${2:-}

# Per-guest settings.
#  VOLS  paths relative to the CT root that hold data to carry over (empty = stateless)
#  IPS   resolver IPs to dig (DNS guests only)
#  UNITS systemd units that must be active after provisioning
#  QUIESCE a command run inside the running pve CT before shutdown; non-zero aborts (nothing stopped)
VOLS=(); IPS=(); UNITS=(); QUIESCE=
case $V in
  20017)
    STACK=technitium-tiny-stack
    VOLS=(var/lib/docker/volumes/technitium-stack_technitium-config)
    IPS=(192.168.20.15 192.168.20.17)
    UNITS=(docker wazuh-agent)
    ;;
  50012)
    STACK=secpipe-stack
    UNITS=(docker cve-enrichment-sync.timer tpot-findings-ingest.timer wazuh-agent)
    ;;
  50013)
    STACK=ai-services-stack
    # ai-services-deep-research-data is obsolete (renamed to -config 2026-09-22); deliberately not carried.
    VOLS=(
      var/lib/docker/volumes/ai-services-openwebui-data
      var/lib/docker/volumes/ai-services-deep-research-config
      var/lib/docker/volumes/ai-services-searxng-data
      var/lib/docker/volumes/eval-runner-hf
      srv/eval-runner
    )
    UNITS=(docker eval-runner-worker-runs eval-runner-worker-ctl wazuh-agent)
    QUIESCE="! docker ps --filter name=eval- --format '{{.Names}}' | grep -q ."
    ;;
  *) echo "no return settings for VMID $V" >&2; exit 2 ;;
esac

PVE=root@pve.gibbsgreatly.xyz
TINY=root@pve-tiny.gibbsgreatly.xyz
RET_WT=/home/steve/git/proxmox-homelab/.worktrees/pve-tiny-return
STATE=${XDG_STATE_HOME:-$HOME/.local/state}/pve-tiny-return/$V
export TASK_APPROVAL=pve-tiny-return-${STACK%-stack}

p()  { ssh -o BatchMode=yes "$PVE" "$@"; }
t()  { ssh -o BatchMode=yes "$TINY" "$@"; }
say() { printf '\n== %s\n' "$*"; }
die() { echo "STOP: $*" >&2; exit 1; }
mark() { mkdir -p "$STATE"; chmod 700 "$STATE"; date -u +%FT%TZ >"$STATE/$1.done"; }
need() { [[ -e $STATE/$1.done ]] || die "phase '$1' has not completed; run it first"; }
has_data() { (( ${#VOLS[@]} > 0 )); }

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
  (( ${#IPS[@]} > 0 )) || return 0
  for ip in "${IPS[@]}"; do
    for name in github.com technitium-tiny.cluster.lab.gibbsgreatly.xyz; do
      printf '%s %-44s UDP: %s\n' "$ip" "$name" "$(dig +short +time=3 +tries=1 @"$ip" "$name" | head -1)"
    done
    printf '%s %-44s TCP: %s\n' "$ip" github.com "$(dig +tcp +short +time=3 +tries=1 @"$ip" github.com | head -1)"
  done
}

phase_check() {
  say "check $V ($STACK) (read-only)"
  [[ $(p hostname) == pve ]] || die "first host is not pve"
  [[ $(t hostname) == pve-tiny ]] || die "second host is not pve-tiny"
  p "pct status $V" | grep -qE 'running|stopped' || die "CT $V not on pve"
  echo "pve   CT $V: $(p "pct status $V"), $(p "pct config $V | grep ^onboot || echo onboot-unset")"
  if t "test -e /etc/pve/lxc/$V.conf"; then
    echo "tiny  CT $V: STALE config present ($(t "pct status $V")); rootfs: $(t "pct config $V | grep ^rootfs")"
    if t "pct config $V | grep -E '^(rootfs|mp[0-9]+):' | grep -q 'nvme-lvm'"; then die "stale CT $V references nvme-lvm; remove the phantom config first"; fi
  else
    echo "tiny  CT $V: none (clean slate)"
  fi
  echo "tiny nvme-lvm free: $(t "pvesm status | awk '\$1==\"nvme-lvm\"{printf \"%.0f GiB\", \$6/1048576}'")"
  [[ -d $RET_WT/terraform/lxc/environments/pve-tiny/$STACK/terraform.tfstate.d ]] || die "state missing in $RET_WT"
  [[ $(git -C "$RET_WT" branch --show-current) == work/pve-tiny-return ]] || die "return worktree not on work/pve-tiny-return"
  dig_all
  echo "OK: check passed"
}

phase_copy() {
  say "copy: baseline, stop pve CT $V${VOLS[*]:+, cold-copy data}"
  mkdir -p "$STATE"; chmod 700 "$STATE"
  if p "pct status $V" | grep -q running; then
    local v
    for v in "${VOLS[@]}"; do
      p "pct exec $V -- test -d /$v" || die "data path /$v not found in the running CT; nothing was stopped"
    done
    if [[ -n $QUIESCE ]]; then
      p "pct exec $V -- bash -c \"$QUIESCE\"" || die "guest is busy (quiesce check failed); nothing was stopped"
    fi
    manifest | p "pct exec $V -- bash -s" >"$STATE/manifest-source.txt"
    echo "baseline manifest: $(wc -l <"$STATE/manifest-source.txt") lines"
    p "pct shutdown $V --timeout 90"
  fi
  [[ $(p "pct status $V") == "status: stopped" ]] || die "pve CT $V did not stop"
  [[ -s $STATE/manifest-source.txt ]] || die "no baseline manifest recorded"
  p "pct set $V --onboot 0"
  if has_data; then
    local list="${VOLS[*]}"
    p "set -e; mkdir -p /root/salvage-$V; chmod 700 /root/salvage-$V
       pct mount $V >/dev/null; trap 'pct unmount $V' EXIT
       mp=/var/lib/lxc/$V/rootfs
       for v in $list; do test -d \$mp/\$v || { echo \"\$v not found under the mounted CT\" >&2; exit 1; }; done
       tar --numeric-owner --xattrs --acls -czf /root/salvage-$V/data.tgz -C \$mp $list
       cd /root/salvage-$V && sha256sum data.tgz >SHA256SUMS"
    p "cat /root/salvage-$V/data.tgz" >"$STATE/data.tgz"
    local remote local_
    remote=$(p "cut -d' ' -f1 /root/salvage-$V/SHA256SUMS")
    local_=$(sha256sum "$STATE/data.tgz" | cut -d' ' -f1)
    [[ $remote == "$local_" ]] || die "checksum mismatch ($remote vs $local_)"
    echo "$local_  data.tgz" >"$STATE/SHA256SUMS"
    echo "archive: $(du -h "$STATE/data.tgz" | cut -f1), sha256 $local_ (copies: pve:/root/salvage-$V and $STATE)"
  else
    echo "stateless guest: no data copied"
  fi
  mark copy
}

phase_create() {
  need copy
  say "create: pve-tiny target for CT $V from Terraform"
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
  # state copy makes the plan a plain create without running that provisioner. It is the only resource
  # with a destroy-time provisioner (checked: grep 'when = destroy' in terraform/lxc), so other
  # null_resource replacements (e.g. the legacy provisioner-less stack_cleanup) are harmless.
  local st=terraform.tfstate.d/pve-tiny/terraform.tfstate
  if grep -q configure_network_sdn_attachment "$st"; then
    cp -p "$st" "$st.pre-sdn-staterm-$(date +%s)"
    ../../../../../with-secrets-prod-tiny terragrunt state rm -no-color 'null_resource.configure_network_sdn_attachment[0]'
  fi
  local plan
  plan=$(../../../../../with-secrets-prod-tiny terragrunt plan -lock=false -no-color 2>&1 | sed 's/^[0-9:.]* STDOUT tofu: //')
  grep -E '^  # |Plan:|Error' <<<"$plan" || true
  if grep -E '^  # null_resource.configure_network_sdn_attachment.*(destroyed|replaced)|^  # module.lxc.proxmox_virtual_environment_container.*(destroyed|replaced)' <<<"$plan"; then
    die "plan would destroy/replace the SDN attachment or a container; not applying"
  fi
  grep -q 'docker_host will be created' <<<"$plan" || die "plan does not create the container; not applying"
  read -r -p "Plan above should only CREATE CT $V (no real guest destroyed). Type yes to apply: " ans
  [[ $ans == yes ]] || die "not applied"
  ../../../../../with-secrets-prod-tiny terragrunt apply -auto-approve -no-color
  t "pct status $V" | grep -q . || die "target CT $V not present after apply"
  mark create
}

phase_restore() {
  need create
  say "restore: data volumes into the new CT"
  if has_data; then
    (cd "$STATE" && sha256sum -c SHA256SUMS --quiet) || die "local archive checksum failed"
    local list="${VOLS[*]}"
    t "pct stop $V 2>/dev/null || true"
    ssh -o BatchMode=yes "$TINY" "set -e; pct mount $V >/dev/null; trap 'pct unmount $V' EXIT
       mp=/var/lib/lxc/$V/rootfs
       mkdir -p \$mp/var/lib/docker/volumes
       tar --numeric-owner --xattrs --acls -xzf - -C \$mp
       for v in $list; do test -d \$mp/\$v && du -sh \$mp/\$v; done" <"$STATE/data.tgz"
    t "pct start $V"
  else
    echo "stateless guest: nothing to restore"
    t "pct status $V" | grep -q running || t "pct start $V"
  fi
  mark restore
}

phase_provision() {
  need restore
  say "provision: full playbook for $STACK via the pve-tiny production wrapper"
  cd "$RET_WT"
  mkdir -p "$STATE"
  if ./with-secrets-prod-tiny scripts/provision.sh --stack "$STACK" 2>&1 | tee "$STATE/provision.log"; then
    mark provision
  elif grep -q 'roles/wazuh_agent/' "$STATE/provision.log" && grep -qE 'failed=1\b' "$STATE/provision.log"; then
    echo
    echo "WARN: the only failure is the Wazuh agent enrolment (manager fault). Marking provision done."
    echo "      Pending, to batch later: wazuh_agent and the plays after it (unattended-upgrades)."
    echo "      Re-run this phase after Wazuh is fixed."
    mark provision
    echo "wazuh-pending" >"$STATE/provision.warn"
  else
    die "provision failed (see $STATE/provision.log)"
  fi
}

extra_verify() {
  case $V in
    50013)
      local ep
      for ep in 8081 8082; do
        printf 'http://192.168.50.11:%s -> %s\n' "$ep" "$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "http://192.168.50.11:$ep/" || echo fail)"
      done
      echo "eval-run results (historical section must be present):"
      t "pct exec $V -- /usr/local/bin/eval-run results" 2>&1 | grep -E '^historical|^  bfcl-|runs? ' | head -4 || true
      t "pct exec $V -- bash -c 'ls /srv/eval-runner/results | wc -l; ls /srv/eval-runner/results/_historical | wc -l'"
      ;;
  esac
  [[ ! -e $STATE/provision.warn ]] || echo "NOTE: provision completed with the Wazuh enrolment pending (see $STATE/provision.warn)"
}

phase_verify() {
  need provision
  say "verify"
  t "pct status $V"
  t "pct exec $V -- docker ps --format '{{.Names}} {{.Status}}'"
  local u
  for u in "${UNITS[@]}"; do printf '%-34s %s\n' "$u" "$(t "pct exec $V -- systemctl is-active $u" || true)"; done
  dig_all
  extra_verify
  manifest | t "pct exec $V -- bash -s" >"$STATE/manifest-target.txt"
  if diff -u "$STATE/manifest-source.txt" "$STATE/manifest-target.txt"; then
    echo "MANIFEST-PARITY-OK"
  else
    echo "MANIFEST DIFF above: review each line (new target may add wazuh-agent/unattended-upgrades/cadvisor, which the pve copy lacked)"
  fi
  echo "Next, by hand: guest-specific consumer checks (return-plan matrix), take a backup of $V, refresh known_hosts."
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

case $PHASE in
  check) phase_check ;;
  copy) phase_check; phase_copy ;;
  create) phase_create ;;
  restore) phase_restore ;;
  provision) phase_provision ;;
  verify) phase_verify ;;
  rollback) phase_rollback ;;
  *) sed -n '2,17p' "$0"; exit 2 ;;
esac
