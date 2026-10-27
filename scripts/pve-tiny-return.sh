#!/usr/bin/env bash
# Return one evacuated CT from pve to pve-tiny (method A: fresh Terraform target +
# restore of any listed data volumes + full provision). See
# docs/pve-tiny-evacuation/return-plan.md. Run from the operator workstation.
#
#   scripts/pve-tiny-return.sh <vmid> <phase>      guests: 20017, 50012, 50013, 40072, 100071, 40070, 20030, 40014
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
# Full output of every phase is kept in ~/.local/state/pve-tiny-return/<vmid>/logs/.
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
#  EXCLUDES tar --exclude paths (relative to the CT root) left out of the data archive
#  MERGE_KEYS an authorized_keys file whose lines are MERGED into the new CT's copy (never overwritten),
#             so the fresh guest keeps the operator key that Ansible needs
#  EXTRA_ARCHIVE a verified tarball on pve-tiny (with SHA256SUMS beside it) extracted over the new CT after VOLS
#  BASELINE a script run inside the pve CT before shutdown; verify re-runs it on the new CT for comparison
#  pre_hook/post_hook run once around the move: pre before the pve CT is stopped, post after provisioning
#             (and from rollback)
VOLS=(); IPS=(); UNITS=(); QUIESCE=; EXCLUDES=(); MERGE_KEYS=; EXTRA_ARCHIVE=; BASELINE=
pre_hook() { :; }
post_hook() { :; }
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
  40072)
    STACK=pentest-runner
    # Everything not reproducible by the playbook: strix runs, raw model traffic, caches, tool state,
    # the shannon fixture source, the BoxPwnr clone and the Temporal volume. /root/.ssh is merged, not copied.
    VOLS=(root home/shannon opt/BoxPwnr var/lib/docker/volumes/infra_temporal-data)
    EXCLUDES=(root/.ssh root/.ansible)
    MERGE_KEYS=root/.ssh/authorized_keys
    UNITS=(docker pentest-viewer-supervisor prometheus-node-exporter)
    QUIESCE='! ps -eo args --no-headers | grep -E "boxpwnr|strix" | grep -vE "grep|view" | grep -q .'
    ;;
  100071)
    STACK=cse-code-eval
    # Disposable scratch by design (backup_policy: exclude): PurpleLlama clone + work area. Carried anyway
    # (318 MB) to keep any run records; lost+found belongs to the new ext4 mount and stays.
    VOLS=(srv/cyberseceval)
    EXCLUDES=(srv/cyberseceval/lost+found)
    UNITS=(docker)
    QUIESCE='! ps -eo args --no-headers | grep -E "CybersecurityBenchmarks|canary|run-autonomous|gcc|g\+\+|cmake" | grep -vE "grep" | grep -q .'
    ;;
  40070)
    STACK=cse-controller
    # /srv/cyberseceval is hand-maintained (pinned PurpleLlama checkout + cse-lab branch, venv, manifests):
    # the playbook only clones when the repo is absent, so this MUST be restored before provisioning.
    VOLS=(srv/cyberseceval)
    EXCLUDES=(srv/cyberseceval/lost+found)
    # Pentest keys/launcher data, node_exporter cert and step, salvaged from the stopped pve-tiny source on
    # 2026-10-27 (also copied on pve). Neither is reproducible by the playbook.
    EXTRA_ARCHIVE=/root/salvage-40070/cse-controller-40070-salvage.tgz
    UNITS=(docker node-exporter-cert-renew.timer)
    # shellcheck disable=SC2016  # runs remotely on stdin; must not expand locally
    QUIESCE='w=cse-controller-worker
docker inspect "$w" >/dev/null 2>&1 || { echo "worker container missing"; exit 1; }
o=$(docker exec -w /srv/cyberseceval/repo/PurpleLlama "$w" /srv/cyberseceval/.venv/bin/celery -A cse_tasks inspect active -t 6 --json 2>&1)
if echo "$o" | grep -q "celery@"; then
  if echo "$o" | grep -q "\"id\""; then echo "busy: active Celery task"; exit 1; fi
  echo "worker replied: idle"
else
  echo "worker did not answer inspect (disconnected from Redis?); checking processes and CPU instead"
  n=$(docker top "$w" -eo pid,args | tail -n +2 | grep -c .)
  if [ "$n" -lt 1 ]; then echo "cannot list the worker processes; not assuming idle"; exit 1; fi
  extra=$(docker top "$w" -eo pid,args | tail -n +2 | grep -vc "celery -A cse_tasks worker")
  if [ "$extra" != 0 ]; then echo "busy: $extra non-celery process(es)"; exit 1; fi
  t1=$(docker top "$w" -eo pid,time | tail -n +2 | tr "\n" " "); sleep 5
  t2=$(docker top "$w" -eo pid,time | tail -n +2 | tr "\n" " ")
  if [ "$t1" != "$t2" ]; then echo "busy: CPU time is changing"; exit 1; fi
  echo "idle by process/CPU check"
fi
exit 0'
    ;;
  20030)
    STACK=cse-panel-stack
    # Redis AOF (queued/recent job state). The app code dirs and redis.conf are rewritten by the playbook.
    VOLS=(srv/cse-panel/redis-data)
    UNITS=(docker)
    # shellcheck disable=SC2016  # runs remotely on stdin; must not expand locally
    QUIESCE='for k in active reserved scheduled; do
  o=$(docker exec cse-panel-flower sh -c "celery -b \"\$CELERY_BROKER_URL\" inspect $k -t 8 --json" 2>&1)
  workers=$(echo "$o" | grep -oE "\"[a-z]+@[A-Za-z0-9._-]+\"" | sort -u | tr "\n" " ")
  echo "$k: workers replying: ${workers:-none}"
  if [ -z "$workers" ]; then echo "no worker answered $k; cannot confirm the queues are idle"; exit 1; fi
  if echo "$o" | grep -q "\"id\""; then echo "busy: $k tasks exist"; exit 1; fi
done
exit 0'
    # shellcheck disable=SC2016
    BASELINE='echo "redis dbsize: $(docker exec cse-panel-redis sh -c '"'"'redis-cli -a "$(awk "/^requirepass/{print \$2}" /usr/local/etc/redis/redis.conf)" --no-auth-warning dbsize'"'"')"'
    # This Redis is the Celery broker for the controller (40070) and eval-runner (50013) workers. They wedged
    # after the 2026-10-24 Redis restart and never reconnected, so stop them before Redis goes down and start
    # them only once the new Redis is up.
    pre_hook() {
      echo "stopping Celery workers that use this Redis (40070 controller + pentest workers, 50013 eval-runner)"
      t "pct exec 40070 -- docker stop cse-controller-worker cse-controller-pentest-worker cse-controller-pentest-research-worker"
      t "pct exec 50013 -- systemctl stop eval-runner-worker-runs eval-runner-worker-ctl"
    }
    post_hook() {
      echo "starting the Celery workers against the new Redis"
      t "pct exec 40070 -- docker start cse-controller-worker cse-controller-pentest-worker cse-controller-pentest-research-worker"
      t "pct exec 50013 -- systemctl start eval-runner-worker-runs eval-runner-worker-ctl"
    }
    ;;
  40014)
    STACK=opensearch-stack
    # Index data (the security index with users/roles lives in it). Only about 0.9 GB is used of the 150 GB
    # mount, so a plain cold copy is quick; images are re-pulled from Harbor.
    VOLS=(var/lib/opensearch-data)
    EXCLUDES=(var/lib/opensearch-data/lost+found)
    UNITS=(docker wazuh-agent)
    # shellcheck disable=SC2016  # runs remotely on stdin; must not expand locally
    QUIESCE='c=opensearch-stack-opensearch
o=$(docker exec $c sh -c "curl -sk --max-time 15 -u \"admin:\$OPENSEARCH_INITIAL_ADMIN_PASSWORD\" https://localhost:9200/_cluster/health" 2>&1)
echo "health: $(echo "$o" | grep -oE "\"status\":\"[a-z]+\"|\"(relocating|initializing)_shards\":[0-9]+" | tr "\n" " ")"
if ! echo "$o" | grep -q "\"status\""; then echo "no health answer; not assuming the cluster is quiet"; exit 1; fi
if echo "$o" | grep -q "\"status\":\"red\""; then echo "cluster is red"; exit 1; fi
n=$(echo "$o" | grep -oE "\"(relocating|initializing)_shards\":0" | wc -l)
if [ "$n" != 2 ]; then echo "shards are relocating or initializing"; exit 1; fi
exit 0'
    # shellcheck disable=SC2016
    BASELINE='c=opensearch-stack-opensearch
today=$(date -u +%Y.%m.%d)
docker exec $c sh -c "curl -sk --max-time 20 -u \"admin:\$OPENSEARCH_INITIAL_ADMIN_PASSWORD\" \"https://localhost:9200/_cat/indices?h=index,docs.count&s=index\"" | grep -vE "^(security-auditlog-$today|docker-live-usage) " '
    # Secpipe (50012) is the main writer (CVE sync daily, T-Pot ingest every 10 min). Pause its timers for the
    # move and let any running run finish. Other writers (Harbor, GVM, Graylog) are not paused; they retry.
    pre_hook() {
      echo "pausing secpipe timers on 50012"
      t "pct exec 50012 -- systemctl stop cve-enrichment-sync.timer tpot-findings-ingest.timer cve-deep-dive.timer"
      for _ in $(seq 1 24); do
        t "pct exec 50012 -- systemctl is-active --quiet cve-enrichment-sync.service tpot-findings-ingest.service cve-deep-dive.service" || break
        sleep 5
      done
      if t "pct exec 50012 -- systemctl is-active --quiet tpot-findings-ingest.service"; then die "a secpipe run is still active after 2 minutes"; fi
    }
    post_hook() {
      echo "resuming secpipe timers on 50012"
      t "pct exec 50012 -- systemctl start cve-enrichment-sync.timer tpot-findings-ingest.timer cve-deep-dive.timer"
    }
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
  if [[ -e $STATE/create.done ]]; then
    echo "tiny  CT $V: the returned target ($(t "pct status $V"), created $(cat "$STATE/create.done"))"
  elif t "test -e /etc/pve/lxc/$V.conf"; then
    echo "tiny  CT $V: STALE config present ($(t "pct status $V")); rootfs: $(t "pct config $V | grep ^rootfs")"
    if t "pct config $V | grep -E '^(rootfs|mp[0-9]+):' | grep -q 'nvme-lvm'"; then
      echo "      note: half-phantom (a volume was on the replaced NVMe); create removes it by hand, after verifying each volume"
    fi
  else
    echo "tiny  CT $V: none (clean slate)"
  fi
  echo "tiny nvme-lvm free: $(t "pvesm status | awk '\$1==\"nvme-lvm\"{printf \"%.0f GiB\", \$6/1048576}'")"
  if [[ -n $EXTRA_ARCHIVE ]]; then
    local d f want have
    d=$(dirname "$EXTRA_ARCHIVE"); f=$(basename "$EXTRA_ARCHIVE")
    t "cd $d && sha256sum -c --quiet SHA256SUMS" || die "salvage archive on pve-tiny failed its checksum ($EXTRA_ARCHIVE)"
    want=$(t "cut -d' ' -f1 $d/SHA256SUMS")
    have=$(p "sha256sum $d/$f | cut -d' ' -f1")
    [[ $want == "$have" ]] || die "pve's copy of the salvage archive differs from pve-tiny's"
    echo "salvage archive: verified on pve-tiny and identical on pve (${want:0:12}...)"
  fi
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
      # Sent on stdin: no ssh/shell quoting layer can split or reinterpret the check's own quotes and pipes.
      printf '%s\n' "$QUIESCE" | p "pct exec $V -- bash -s" || die "guest is busy (quiesce check failed); nothing was stopped"
    fi
    if [[ -n $MERGE_KEYS ]]; then
      p "pct exec $V -- cat /$MERGE_KEYS" >"$STATE/merge-keys.txt"
      [[ -s $STATE/merge-keys.txt ]] || die "could not read /$MERGE_KEYS; nothing was stopped"
      echo "authorized keys captured: $(grep -c '^ssh-' "$STATE/merge-keys.txt") key line(s)"
    fi
    pre_hook
    trap 'echo "copy failed after pre_hook; run: $0 $V rollback (restarts the pve copy and the paused workers/timers)" >&2' ERR
    if [[ -n $BASELINE ]]; then
      printf '%s\n' "$BASELINE" | p "pct exec $V -- bash -s" >"$STATE/baseline.txt"
      echo "baseline recorded: $(wc -l <"$STATE/baseline.txt") line(s)"
    fi
    manifest | p "pct exec $V -- bash -s" >"$STATE/manifest-source.txt"
    echo "baseline manifest: $(wc -l <"$STATE/manifest-source.txt") lines"
    p "pct shutdown $V --timeout 90"
  fi
  [[ $(p "pct status $V") == "status: stopped" ]] || die "pve CT $V did not stop"
  [[ -s $STATE/manifest-source.txt ]] || die "no baseline manifest recorded"
  p "pct set $V --onboot 0"
  if has_data; then
    local list="${VOLS[*]}" excl="" x
    for x in "${EXCLUDES[@]}"; do excl+=" --exclude=$x"; done
    p "set -e; mkdir -p /root/salvage-$V; chmod 700 /root/salvage-$V
       pct mount $V >/dev/null; trap 'pct unmount $V' EXIT
       mp=/var/lib/lxc/$V/rootfs
       for v in $list; do test -d \$mp/\$v || { echo \"\$v not found under the mounted CT\" >&2; exit 1; }; done
       tar --numeric-owner --xattrs --acls$excl -czf /root/salvage-$V/data.tgz -C \$mp $list
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

# A stale pve-tiny CT with one volume on the replaced NVMe (gone) and the rest on the boot SSD.
# pct destroy can stop on the missing volume, so verify every volume by exact name, then remove the
# boot-SSD LVs and the config by hand. Only names of the form vm-<this vmid>-disk-N are ever touched.
destroy_half_phantom() {
  local refs r stor name
  refs=$(t "pct config $V | grep -E '^(rootfs|mp[0-9]+):' | grep -oE '(local-lvm|nvme-lvm):vm-$V-disk-[0-9]+'")
  [[ -n $refs ]] || die "could not parse the stale CT's volumes"
  for r in $refs; do
    stor=${r%%:*}; name=${r#*:}
    if [[ $stor == nvme-lvm ]]; then
      if t "lvs --noheadings nvme-lvm/$name >/dev/null 2>&1"; then die "nvme-lvm/$name exists; not a phantom, review by hand"; fi
    else
      t "lvs --noheadings pve/$name >/dev/null 2>&1" || die "pve/$name not found on pve-tiny"
    fi
  done
  echo "removing stale boot-SSD volumes and config of CT $V:"
  for r in $refs; do
    stor=${r%%:*}; name=${r#*:}
    if [[ $stor == local-lvm ]]; then echo "  lvremove pve/$name"; t "lvremove -y pve/$name"; else echo "  (already gone: nvme-lvm/$name)"; fi
  done
  t "rm /etc/pve/lxc/$V.conf"
  t "test ! -e /etc/pve/lxc/$V.conf" || die "stale config still present"
}

phase_create() {
  need copy
  say "create: pve-tiny target for CT $V from Terraform"
  [[ $(p "pct status $V") == "status: stopped" ]] || die "pve CT $V is not stopped"
  p "pct config $V | grep -q '^onboot: 0'" || die "pve CT $V onboot is not 0"
  if t "test -e /etc/pve/lxc/$V.conf"; then
    [[ $(t "pct status $V") == "status: stopped" ]] || die "stale CT $V is running on pve-tiny"
    if t "pct config $V | grep -E '^(rootfs|mp[0-9]+):' | grep -q 'nvme-lvm'"; then
      destroy_half_phantom
    else
      t "pct destroy $V --purge"
    fi
  fi
  cd "$RET_WT/terraform/lxc/environments/pve-tiny/$STACK"
  # The state's null_resource triggers hold the main checkout's paths. From this worktree they differ,
  # Terraform would REPLACE it, and its destroy-time provisioner tries to delete the SDN vnet (the
  # network_sdn_allow_destroy guard blocks it, aborting the apply). Dropping it from the worktree's
  # state copy makes the plan a plain create without running that provisioner. It is the only resource
  # with a destroy-time provisioner (checked: grep 'when = destroy' in terraform/lxc), so other
  # null_resource replacements (e.g. the legacy provisioner-less stack_cleanup) are harmless.
  local st=terraform.tfstate.d/pve-tiny/terraform.tfstate
  # Look for the actual resource entry: the name also appears in other resources' "dependencies" lists.
  if [[ -f $st ]] && python3 -I -c 'import json,sys; sys.exit(0 if any(r["type"]=="null_resource" and r["name"]=="configure_network_sdn_attachment" for r in json.load(open(sys.argv[1]))["resources"]) else 1)' "$st"; then
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
       for v in $list; do test -d \$mp/\$v && du -sh \$mp/\$v; done
       # tar runs as real root on the host, so any parent directory it had to create is owned by uid 0, which an
       # unprivileged CT sees as nobody (its root, uid 100000, then cannot write there). Re-own those parents.
       if pct config $V | grep -q '^unprivileged: 1'; then
         for v in $list; do
           d=\$(dirname \$v)
           while [ \"\$d\" != . ] && [ \"\$d\" != / ]; do
             if [ \"\$(stat -c %u \$mp/\$d)\" = 0 ]; then chown 100000:100000 \$mp/\$d; echo \"re-owned implicitly created parent: \$d\"; fi
             d=\$(dirname \$d)
           done
         done
       fi
       if [ -n '$EXTRA_ARCHIVE' ]; then
         (cd \$(dirname '$EXTRA_ARCHIVE') && sha256sum -c --quiet SHA256SUMS)
         tar --numeric-owner --xattrs --acls -xzf '$EXTRA_ARCHIVE' -C \$mp
         echo 'extra archive extracted:'; ls -ld \$mp/srv/pentest-worker \$mp/etc/node_exporter | cut -c1-70
       fi" <"$STATE/data.tgz"
    t "pct start $V"
  else
    echo "stateless guest: nothing to restore"
    t "pct status $V" | grep -q running || t "pct start $V"
  fi
  if [[ -n $MERGE_KEYS ]]; then
    need copy
    for _ in $(seq 1 30); do t "pct exec $V -- true" 2>/dev/null && break; sleep 2; done
    t "pct exec $V -- bash -c 'f=/$MERGE_KEYS; mkdir -p \$(dirname \$f); touch \$f; while IFS= read -r l; do [ -z \"\$l\" ] || grep -qxF \"\$l\" \$f || echo \"\$l\" >> \$f; done; chmod 600 \$f'" <"$STATE/merge-keys.txt"
    echo "authorized_keys now has $(t "pct exec $V -- grep -c '^ssh-' /$MERGE_KEYS") key line(s)"
  fi
  local gw
  gw=$(t "pct config $V | grep '^net0:' | grep -o 'gw=[0-9.]*' | cut -d= -f2")
  [[ -n $gw ]] || die "could not read the gateway from net0 of CT $V"
  for _ in $(seq 1 15); do t "pct exec $V -- ping -c1 -W2 $gw >/dev/null 2>&1" && break; sleep 2; done
  t "pct exec $V -- ping -c2 -W2 $gw >/dev/null 2>&1" || die "new CT cannot reach its gateway $gw; check the VNet/VLAN on pve-tiny before provisioning"
  echo "gateway $gw reachable from the new CT"
  mark restore
}

phase_provision() {
  need restore
  say "provision: full playbook for $STACK via the pve-tiny production wrapper"
  cd "$RET_WT"
  mkdir -p "$STATE"
  rm -f "$STATE/provision.warn"
  # WAZUH=skip skips only the wazuh_agent_rollout play (tagged in every stack playbook) so a broken
  # Wazuh manager does not abort the plays that follow it (e.g. eval-runner on ai-services-stack).
  # It is explicit, never inferred from a failure: the enrolment stays pending until re-run without it.
  if [[ ${WAZUH:-} == skip ]]; then
    export ANSIBLE_SKIP_TAGS=wazuh_agent_rollout
    echo "NOTE: skipping the Wazuh agent play (ANSIBLE_SKIP_TAGS=$ANSIBLE_SKIP_TAGS)"
  fi
  if ./with-secrets-prod-tiny scripts/provision.sh --stack "$STACK" 2>&1 | tee "$STATE/provision.log"; then
    :
  else
    die "provision failed (see $STATE/provision.log); fix the cause, or if it is the Wazuh manager re-run with WAZUH=skip"
  fi
  # tee masks the exit status in some shells; confirm from the recap.
  grep -qE 'failed=0\b' "$STATE/provision.log" || die "recap does not show failed=0 (see $STATE/provision.log)"
  [[ ${WAZUH:-} != skip ]] || echo "wazuh-pending" >"$STATE/provision.warn"
  mark provision
  post_hook
}

extra_verify() {
  case $V in
    40014)
      t "pct exec $V -- bash -s" <<'REMOTE'
docker ps --format '{{.Names}} {{.Status}}'
c=opensearch-stack-opensearch
docker exec $c sh -c 'curl -sk --max-time 15 -u "admin:$OPENSEARCH_INITIAL_ADMIN_PASSWORD" https://localhost:9200/_cluster/health' | tr ',' '\n' | grep -E '"status"|number_of_nodes|active_shards"|unassigned_shards"'
echo "security index docs: $(docker exec $c sh -c 'curl -sk --max-time 15 -u "admin:$OPENSEARCH_INITIAL_ADMIN_PASSWORD" "https://localhost:9200/_cat/count/.opendistro_security?h=count"')"
echo "dashboards :5601 -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:5601/api/status)"
echo "data mount: $(mountpoint -q /var/lib/opensearch-data && echo yes || echo NO), used $(du -sh /var/lib/opensearch-data | cut -f1)"
REMOTE
      ;;
    20030)
      t "pct exec $V -- bash -s" <<'REMOTE'
docker ps --format '{{.Names}} {{.Status}}'
echo "panel-ui :8050 -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8050/)"
echo "redis dbsize: $(docker exec cse-panel-redis sh -c 'redis-cli -a "$(awk "/^requirepass/{print \$2}" /usr/local/etc/redis/redis.conf)" --no-auth-warning dbsize')"
for k in active; do
  o=$(docker exec cse-panel-flower sh -c "celery -b \"\$CELERY_BROKER_URL\" inspect $k -t 10 --json" 2>&1)
  echo "workers answering via the new Redis: $(echo "$o" | grep -oE '"[a-z]+@[A-Za-z0-9._-]+"' | sort -u | wc -l) (expect 5)"
done
REMOTE
      ;;
    40070)
      t "pct exec $V -- bash -s" <<'REMOTE'
docker ps --format '{{.Names}} {{.Status}}'
echo "worker log: $(docker logs --tail 40 cse-controller-worker 2>&1 | grep -E 'Connected to redis|ready\.' | tail -2 | cut -c1-110 | tr '\n' ' ')"
echo "worker answers inspect: $(docker exec -w /srv/cyberseceval/repo/PurpleLlama cse-controller-worker /srv/cyberseceval/.venv/bin/celery -A cse_tasks inspect ping -t 8 2>&1 | grep -c 'pong') pong(s)"
echo "mountpoint /srv/cyberseceval: $(mountpoint -q /srv/cyberseceval && echo yes || echo NO)"
echo "repo branch: $(git -C /srv/cyberseceval/repo/PurpleLlama branch --show-current 2>&1)"
echo "key files: $(stat -c '%a %n' /srv/pentest-worker/id_pentest_runner /srv/pentest-research/id_gvm_research_gateway 2>&1 | tr '\n' ';')"
echo "run-manifests: $(ls /srv/pentest-worker/run-manifests 2>/dev/null | wc -l)"
echo "step: $(/usr/local/bin/step version 2>&1 | head -1)"
echo "node_exporter cert files: $(ls /etc/node_exporter 2>/dev/null | wc -l)"
ssh -i /srv/pentest-worker/id_pentest_runner -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/tmp/r2-kh root@192.168.100.72 'echo "controller -> pentest-runner ssh: ok"' 2>&1 | tail -1
REMOTE
      ;;
    100071)
      t "pct exec $V -- bash -s" <<'REMOTE'
echo "mountpoint /srv/cyberseceval: $(mountpoint -q /srv/cyberseceval && echo yes || echo NO)"
echo "repo: $(ls /srv/cyberseceval/repo 2>/dev/null | head -3 | tr '\n' ' ')"
docker ps --format '{{.Names}} {{.Status}}'
echo "gcc: $(docker exec cse-code-eval gcc --version 2>&1 | head -1)"
echo "cmake: $(docker exec cse-code-eval cmake --version 2>&1 | head -1)"
ping -c2 -W2 192.168.100.70 >/dev/null 2>&1 && echo "route to cse-controller 192.168.100.70: ok" || echo "route to cse-controller 192.168.100.70: NO REPLY"
REMOTE
      ;;
    40072)
      printf 'viewer healthz -> %s\n' "$(t "pct exec $V -- curl -s --max-time 8 http://192.168.100.72:18820/healthz" || echo fail)"
      t "pct exec $V -- bash -s" <<'REMOTE'
echo "strix_runs: $(ls /root/strix_runs | wc -l)"
echo "model-traffic: $(du -sh /root/model-traffic | cut -f1)"
echo "authorized key comments:"
awk '{print $NF}' /root/.ssh/authorized_keys
getent hosts github.com | head -1
REMOTE
      ;;
    50013)
      local ep
      for ep in 8081 8082; do
        printf 'http://192.168.50.11:%s -> %s\n' "$ep" "$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "http://192.168.50.11:$ep/" || echo fail)"
      done
      t "pct exec $V -- test -x /usr/local/bin/eval-run" || echo "FAIL: /usr/local/bin/eval-run missing: the eval-runner play did not run"
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
  if [[ -n $BASELINE ]]; then
    printf '%s\n' "$BASELINE" | t "pct exec $V -- bash -s" >"$STATE/baseline-target.txt"
    if diff -u "$STATE/baseline.txt" "$STATE/baseline-target.txt"; then echo "BASELINE-MATCH ($(wc -l <"$STATE/baseline.txt") line(s) identical before and after)"; else echo "BASELINE DIFF above: review (live writers can legitimately change counts)"; fi
  fi
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
  post_hook
  dig_all
  rm -f "$STATE"/create.done "$STATE"/restore.done "$STATE"/provision.done "$STATE"/verify.done
}

# Every phase writes its full output to a log, so nothing has to be pasted back: tell the assistant
# the phase finished and it reads the newest log (ls -t "$STATE/logs"). Mode 700 like the rest of $STATE.
if [[ -n $PHASE ]]; then
  mkdir -p "$STATE/logs"; chmod 700 "$STATE" "$STATE/logs"
  LOG="$STATE/logs/$(date +%Y%m%dT%H%M%S)-$PHASE.log"
  exec > >(tee -a "$LOG") 2>&1
  echo "[log: $LOG]"
fi

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
