# pve-tiny temporary evacuation to pve

Status: **execution in progress.** OpenSearch CT 40014 is fully migrated to
`pve`, backed up there, and retained stopped on `pve-tiny` for rollback.
Secpipe CT 50012 is running only on `pve`, has target autostart and a fresh
PBS backup, and its managed roles were reconciled. Its CVE enrichment has a
recorded pre-existing stale target credential issue; it was observed but not
changed during this migration. The remaining six guests have not started
cutover.

This worktree's pve profile formerly requested retired `services/pentagi`,
which was correctly removed from OpenBao during the PentAGI teardown. The
stale manifest entry and profile references have been removed; the production
wrapper now loads successfully.
No Terraform state was changed during these cold-copy/reconciliation actions;
the target CT runtime state must be reconciled with reviewed Terraform plans
before later infrastructure changes.

The [execution runbook](runbook.md) defines the per-guest sequence, storage
profiles, data to preserve, verification, and rollback. Its restore and
inventory gates must be completed before any guest approval.

## Objective and scope

Move the eight currently running LXCs from standalone `pve-tiny` to `pve`
before shutting down `pve-tiny` for several days and returning its failing
Kingston NV3 NVMe for RMA. Keep each service's VMID and IP. The stopped
`mcp-utility-stack` copy on `pve-tiny` is not a live service; the current
copy already runs on `pve`.

Work in `work/pve-tiny-evacuation` only. No development on `stable` or `main`.
Every production mutation requires a separate preflight, operator approval,
`TASK_APPROVAL`, and an after-action summary under `AGENTS.md`.

## Read-only baseline, 2026-10-24

The Proxmox APIs reported 8.55 GiB combined guest memory use on `pve-tiny`.
`pve` had 42.41 GiB available RAM, leaving about 33.86 GiB at that workload
level. This is a point-in-time capacity check, not a peak guarantee.

| VMID | Guest | IP / zone | Live memory | Source disks | Target preparation |
|---|---|---|---:|---|---|
| 40014 | opensearch-stack | 192.168.40.14 / infra_seg | 4.53 GiB | NVMe root, Docker, 150G data mount | Completed 2026-10-24: target running/onboot, service and consumer checks passed, fresh pve PBS backup; source stopped/onboot disabled |
| 50013 | ai-services-stack | 192.168.50.11 / ai_seg | 1.90 GiB | NVMe root and Docker | Stopped pve copy exists; refresh OpenWebUI, SearXNG, research volumes |
| 50012 | secpipe-stack | 192.168.50.12 / ai_seg | 0.17 GiB | NVMe root and Docker | Completed 2026-10-24: source stopped/onboot disabled; target running/onboot and freshly backed up; T-Pot ingestion passed; pre-existing stale CVE credential issue recorded, not changed |
| 40072 | pentest-runner | 192.168.100.72 / cse_seg | 0.32 GiB | NVMe root and Docker | No stack definition found; establish owner and restore method |
| 40070 | cse-controller | 192.168.100.70 / cse_seg | 0.41 GiB | Boot SSD root/Docker; NVMe 100G data mount | Preserve run state and private cse-kali SSH key |
| 100071 | cse-code-eval | 192.168.100.71 / cse_seg | 0.25 GiB | Boot SSD root/Docker; NVMe 50G data mount | Data mount has backup=0; decide whether scratch may be rebuilt |
| 20030 | cse-panel-stack | 192.168.20.30 / mgmt_seg | 0.42 GiB | Boot SSD root and Docker | Preserve Redis AOF and panel state |
| 20017 | technitium-tiny-stack | 192.168.20.17 / mgmt_seg | 0.56 GiB | Boot SSD root and Docker | Secondary DNS; verify cluster and client resolution |

The `pve-tiny` NVMe has documented media errors and already made CT 50011's
PBS backup fail. A backup listing alone cannot prove recoverability. Check
the latest backup result and perform a test restore or verified cold copy
for each stateful guest. Stop if reads or integrity checks fail; determine a
salvage path before overwriting the last good copy.

The latest `pve-tiny` vzdump task, at 18:30 NZDT on 2026-10-23, reports
success for all eight running guests. The preceding daily tasks failed on
the stopped CT 50011's NVMe Docker volume, while the eight running guests
completed. The read-only PVE token returned an empty PBS content listing,
so these logs establish backup task success but **not** that snapshots can be
listed or restored from `pve`. A test restore remains a hard gate.

`pve`'s current daily PBS job is `all=1`. The completed 40014 cutover removed
only 40014 from its exclusion list and recorded a successful fresh backup.
It still excludes 50011, 50012 and 50013. VMID 50011 is a separate existing
backup gap; keep it out of this migration scope. Do not remove 50012's
exclusion until its bounded Secpipe validation succeeds, and then require a
fresh backup under its own scoped approval.

`pve` retains stopped stale copies of VMIDs 50012 and 50013 from the earlier
move. Do not start 50013 before source shutdown and state refresh. CT 50012
is now the sole running instance while its final validation remains pending.
CT 40014 has been refreshed and is running on pve. The `pve` default
infrastructure pool had only about 92 GiB free at baseline. Choose target
pools per volume; do not sum storage aliases that refer to the same backing
pool.

Terragrunt uses local state in each stack's environment directory. The
original checkout has state for the three stopped pve copies and the seven
managed pve-tiny guests; the isolated worktree does not. Before any plan or
apply, copy the exact state files and workspace directories into this
worktree as ignored, access-restricted local files, record checksums, and
confirm the copied state corresponds to the live VMIDs. Never plan a live
guest from an empty state directory, and never symlink writable state back
into the other checkout. Refresh each state copy immediately before that
guest's cutover; stop if its checksum changed unexpectedly.

`pentest-runner` has no tracked stack definition or usable state in either
checkout. The local original-checkout directory contains inventory and
cache files, but its `pve-tiny` state directory is empty. Treat VMID 40072
as manually managed until its creation and restore path is established.

A read-only pve API check on 2026-10-24 found no `tvcse` zone or VNet and
no pending zone/VNet/subnet changes (all 10 current VNets checked).
`vmbr0` is VLAN-aware with bridge VID range
2–4094. This does not prove the external switch path for VLAN 100; test it
after creating the pve-side VNet and before moving CSE guests.

## Phase 0: production preflight, read-only

1. Confirm node names, VMIDs, IPs, autostart flags, mount layouts, idmaps,
   guest health, guest used bytes, source backup coverage and last successful
   backup. Confirm the failed NVMe's SMART/media-error status without causing
   another heavy scan.
2. Check capacity and free space on each intended `pve` pool, allowing for
   root, Docker and data mounts plus backup/snapshot headroom. Confirm pve's
   `vm.max_map_count` still meets OpenSearch's requirement.
3. Check the actual Terraform state and `terragrunt plan` for both nodes and
   every managed guest. The separate nodes cannot do a Proxmox live migration.
   A cutover must not accidentally destroy a source or overwrite pve's stale
   copy before its rollback role is understood.
4. Confirm current PBS namespace and restore access. `cse-code-eval`'s data
   mount is excluded from backup. Document whether that data is disposable;
   copy it separately if it is to survive.
5. Confirm `pentest-runner` ownership, image, mounts, persistence and
   provision/restore commands. It is running but has no stack definition in
   this repo; do not silently treat it as a managed disposable guest.
6. Check pve and pve-tiny network/SDN state and pending changes. The `cse_seg`
   VLAN 100 VNet exists only on pve-tiny in the current source. Establish it
   on pve and prove its gateway and required cross-zone paths before moving
   VMIDs 40070, 100071 or 40072.
7. Baseline service-level checks and decide a cutover window with no PBS
   backup/verify or CSE job in progress. Record the exact rollback trigger for
   each service.

### Target storage candidates; confirm with plans and free-space checks

| Guest | Proposed pve placement | Reason / gate |
|---|---|---|
| 40014 opensearch | Reuse existing stopped pve root and Docker on `monitoring-containers`, data mount on `storage-containers` | Refresh the data mount from a verified current source; retain old data separately until validated |
| 50012 secpipe, 50013 ai-services | Reuse existing stopped pve volumes on `infrastructure-containers` | Ensure the 92 GiB pool headroom remains adequate; refresh AI named volumes, provision current code |
| 40070, 100071 CSE | New root/Docker on `apps-containers`; data mounts on `storage-containers` | Confirm both pools' physical free space and create pve Terraform state; code-eval's data may be rebuilt only if no needed run state remains |
| 20030 panel | New root/Docker on `apps-containers` | Preserve Redis AOF and queue state after draining jobs |
| 20017 Technitium secondary | New root/Docker on `monitoring-containers` | Keep the distinct `.17` IP; confirm cluster state and DNS client paths |
| 40072 pentest runner | Whole-CT PBS restore to `apps-containers`, subject to a successful isolated test restore | No tracked source definition or state; retain manual ownership and verify root plus Docker recovery |

These are candidates, not permissions to resize or overwrite volumes. Check
the actual backend allocations and ZFS headroom immediately before each
cutover. Restore/copy methods and Terraform plans must match the selected
pool; otherwise stop and revise this table.

### Cutover readiness gates

The pve-side `tvcse` SDN change has a scoped preflight and rollback above.
The guest cutovers do **not** yet have an approved, executable command set.
Before seeking approval for any guest, record all of the following in this
plan or its runbook:

1. A restorable source backup (including every persistent mount) or a
   verified cold-copy procedure, with the exact snapshot/volume identifier
   and a test restore. State which mounts are intentionally disposable.
2. The selected target storage IDs and required free bytes, the exact guest
   config and volume layout, and an independently retained rollback copy.
3. A private, verified Terraform state handoff or import plan for that VMID,
   with a reviewed `terragrunt plan` that shows no unapproved replacement or
   destruction. For 40072, validate the whole-CT restore and retain manual
   ownership pending a separate IaC project.
4. Exact source stop, transfer/restore, target start, service verification,
   backup, and rollback commands. Include the timeout and trigger for
   returning the original source online, and account for any writes made on
   pve before reversal.
5. For 40014, 50012 and 50013, reconcile the stopped target copies and
   remove their backup-job exclusions before accepting the cutover. Confirm
   the first new backup completes.

Do not shut down `pve-tiny` while any of these gates remains open.

## Phase 1: prepare source-controlled target definitions

Add `cse_seg` to pve's network manifest as an additive VLAN 100 zone/VNet,
matching the existing MikroTik subnet and isolation. The VLAN zone is applied
by `ansible/00-initial-setup/proxmox-sdn-setup.yml`, not Terraform. Scope its
run to `tvcse`, reject unrelated pending SDN state, and leave the cluster
firewall untouched. Review the read-only API diff and rollback path before
applying it. Map each moved stack's storage
profile to an appropriate pve pool, and prepare pve Terragrunt entrypoints
without changing live ownership yet. Update `network/pve.yaml` membership
only after each cutover. Keep `pve-tiny` entrypoints until their state and
live resources have been reconciled under the approved decommission phase.

Avoid a simultaneous management claim over the same VMID on one node. The
three stale pve copies need an explicit choice: refresh them from the live
source or create replacement guests after preserving/decommissioning the
stale copies. Test each resulting plan for unexpected changes or deletions.

### First production mutation: pve-side `tvcse` only

Preflight target: `pve`. Mutating objects: one `tvcse` VLAN zone on `vmbr0`
for node `pve`, one `tvcse` VNet tagged 100, subnet `192.168.100.0/24` with
gateway `192.168.100.1` and SNAT disabled, followed by SDN apply. Existing
VNets, firewall configuration, guests and `pve-tiny` are out of scope.

After a fresh read-only SDN check, operator approval and setting
`TASK_APPROVAL=pve-tiny-evacuation-sdn`, run from this worktree:

```bash
./with-secrets-prod ansible-playbook -i 'pve.gibbsgreatly.xyz,' -u root \
  -e '{"target_hosts":"all","requested_sdn_vnets":["tvcse"],"reject_pending_sdn_changes":true,"manage_cluster_firewall":false}' \
  ansible/00-initial-setup/proxmox-sdn-setup.yml
```

Require zero failed tasks, `tvcse` only among changes, and unchanged
existing zones/VNets. Before a CSE guest moves, confirm the VLAN 100 route
to `192.168.100.1` from a temporary pve-side source after checking that its
test IP is unused; then check the intended CSE-to-Harbor, Framework and
panel paths plus one adjacent pve network consumer. The temporary IP action
requires its own scoped approval if performed separately.

Rollback before any guest attaches: on `pve`, read the actual `tvcse` subnet
identifier from `/cluster/sdn/vnets/tvcse/subnets`, delete that subnet,
delete `/cluster/sdn/vnets/tvcse`, delete `/cluster/sdn/zones/tvcse`, and
apply `/cluster/sdn`. Do not run rollback if a guest is attached; stop and
move it first under its own approval. Preserve the preflight SDN inventory
for comparison. These rollback commands are production mutations and require
the task approval, too.

## Phase 2: approved cold cutovers, one service at a time

For each guest: publish the exact source and target commands and rollback;
obtain per-task approval; quiesce writes; stop source and set `onboot=0`;
take and verify a final copy; restore target on its chosen pool; start only
the target; reconcile its playbook; verify service, consumers, backup and
resource use; record an after-action summary. Keep the source stopped and
intact through the soak. If a gate fails, stop the target and either fix the
issue under the same scope or return to the source after accounting for any
new writes. Do not run duplicate IPs.

Suggested order, respecting dependencies and the failing NVMe:

1. `opensearch-stack`: move index data, validate index/document counts,
   security index, Dashboards/OIDC, Harbor/GVM ingestion and Grafana readers.
2. `secpipe-stack`: validate its actual OpenSearch and MCP enrichment path
   with a bounded sample, not an unbounded full sync.
3. `ai-services-stack`: compare OpenWebUI users/chats, verify SearXNG, research
   state, model route and real login/ingress.
4. `pentest-runner`: use its confirmed owner/restore method; validate a
   bounded real job. This remains blocked until Phase 0 establishes it.
5. Pause new CSE jobs and drain current work. Move `cse-code-eval`, then
   `cse-controller`, then `cse-panel-stack`; validate CSE isolation, worker,
   Redis queue, panel login and one small evaluation. Preserve the dedicated
   cse-kali SSH key and any current run records.
6. Move `technitium-tiny-stack` last. Check cluster synchronization and DNS
   UDP/TCP at 192.168.20.17, direct queries to the primary at .15, router
   DHCP's two resolver addresses and actual client resolution. Both DNS
   instances will then reside on pve, so node-level redundancy is lost
   during the shutdown period.

### Current execution state

| Guest | State | Remaining gate |
|---|---|---|
| 40014 OpenSearch | Complete on `pve`; source retained stopped | Soak and later Terraform reconciliation only |
| 50012 Secpipe | Complete on `pve`; source stopped/onboot disabled; target `onboot=1`; fresh PBS backup | Track the observed pre-existing stale CVE credential separately; do not change it as part of migration |
| 50013, 40072, 40070, 100071, 20030, 20017 | Not started | Resolve normal per-guest gates after the production wrapper is restored |

## Phase 3: shutdown and RMA gate

After every target has passed smoke tests and a backup, check pve memory,
pool headroom, guest autostart, monitoring, DNS, routes and scheduled jobs.
Only then approve shutdown of pve-tiny. Keep its boot SSD and stopped guests
untouched until the rollback window closes. After migration and backup gates,
erase the failing NVMe from a USB-booted Linux system with a supported NVMe
controller erase and verify its final success status before sending it for
RMA. A failed erase is not evidence that the drive is clean.

## Completion criteria

All eight services run only on pve, retain their intended IPs, pass their
real consumer checks, have successful new backups, and survive a controlled
reboot/autostart check. Terraform plans for managed guests and SDN match the
actual target state. The old node is shut down only after these conditions
are met. Promotion to `stable` and `main` follows the branch gates in
`AGENTS.md`; no merge target is assumed here.
