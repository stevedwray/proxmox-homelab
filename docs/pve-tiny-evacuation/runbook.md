# pve-tiny evacuation: execution runbook

Use with [plan.md](plan.md). This is a sequence of **separate production
tasks**, not blanket approval. Run from the `work/pve-tiny-evacuation`
worktree. For each mutation, post the AGENTS.md preflight (node, objects,
commands, exclusions), obtain chat approval, set the named `TASK_APPROVAL`,
execute only that task, and post an after-action summary. Read-only commands
also use the matching production wrapper. Never run an apply against an empty
or unverified local state file.

## 0. Prepare the worktree and a recovery record (no production mutation)

### Completed recovery evidence

On 2026-10-24, `pbs-iscsi:backup/ct/40072/2026-10-23T05:31:48Z`
was restored on pve as temporary stopped CT 940072 with root and Docker
volumes on `apps-containers`. The restore completed successfully (4.266 GiB
read), and offline inspection found a populated Docker tree including
`overlay2`, `containers`, `image`, `volumes`, and `swarm`. The temporary CT,
its temporary pve-only PBS mapping, and its copied mapping credential were
then removed successfully. No source CT was stopped or modified.

The temporary CT could not mount with its restored `tvcse` network config
because pve does not yet have that bridge. It was kept stopped, its autostart
was disabled, and its bridge was changed temporarily to `vmbr0` solely for
the offline filesystem check. Complete the separate `tvcse` task before
any real CSE or pentest-runner cutover.

### Completed pve VLAN 100 provisioning

On 2026-10-24, the approved `pve-tiny-evacuation-sdn` task created and
applied the pve-only `tvcse` VLAN zone/VNet on `vmbr0`, VLAN tag 100, with
subnet `192.168.100.0/24`, gateway `192.168.100.1`, and SNAT disabled.
The playbook made only those three intended changes and did not alter the
cluster firewall or any existing SDN object. Post-change inspection confirmed
that Linux bridge `tvcse` is up and its Proxmox subnet matches the declared
configuration. Network reachability still requires the separate temporary
source test below before a CSE guest can move.

### CSE path validation — Framework availability gate

On 2026-10-24, temporary address `192.168.100.250/24` was attached to
`tvcse` on pve after confirming no Proxmox guest claimed it. It reached the
gateway (`192.168.100.1`, 3/3 ICMP replies), proving VLAN 100 reaches the
MikroTik. The initial Harbor 404 and panel timeout used the wrong Harbor
hostname and a panel HTTP path that CSE is not intended to use; the address
was removed in the same task and verified absent.

A subsequent read-only router audit confirmed all intended CSE allow rules
exist ahead of CSE's default deny: CSE-to-Traefik/Harbor on TCP 80/443,
CSE-to-Framework on TCP 8080, and controller `.70` to panel Redis `.30:6379`.
The running source controller verified Harbor health (HTTP 200 via
`harbor.lab.gibbsgreatly.xyz`) and panel Redis reachability. Its Framework
connection still failed because Framework had no port 8080 listener.
`llama-swap.service` was active but no managed llama-server model was loaded.

The approved `pve-tiny-evacuation-framework-model-start` task then started
`llama-swap-preload.service` on Framework. The normal one-shot preload
completed, `llama-swap.service` remained active, and the intended model
listener appeared on `0.0.0.0:8080`. Framework's local `/v1/models` and the
source controller's request to `http://framework.gibbsgreatly.xyz:8080/v1/models`
both returned the expected unauthenticated `401`, which confirms the actual
CSE-to-Framework route and service path now work. No MikroTik rule change is
required. Repeat the brief pve-side test using the corrected Harbor hostname
and the now-live Framework endpoint before moving a CSE guest.

The approved `pve-tiny-evacuation-cse-network-retest` repeated that pve-side
test with temporary address `192.168.100.250/24`. The address reached the
gateway with 3/3 replies, Harbor's health API returned a healthy response via
the correct hostname, and Framework's model endpoint returned `401` as
expected without credentials. The cleanup trap removed the address, and a
post-test address check confirmed it was absent. VLAN 100's pve-side CSE
paths are therefore ready for guest cutover; panel Redis remains separately
covered by the successful controller `.70` check because the router rule is
source-address-specific.

### OpenSearch CT 40014 preflight — blocked

On 2026-10-24, the approved `pve-tiny-evacuation-opensearch-preflight` task
confirmed that source CT 40014 is running with its expected 16G root, 20G
Docker mount, 150G OpenSearch-data mount, 6 GiB memory, two cores, `tvinfra`
network, unprivileged mode and nesting. The stopped pve target matches those
runtime settings and mount sizes, uses its intended `monitoring-containers`
and `storage-containers` pools, and has `onboot=0`. At the check time those
pve pools had about 437 GiB and 1.48 TiB free respectively.

The source OpenSearch container reported healthy, but its Dashboards container
reported unhealthy before any migration action. Direct unauthenticated HTTP
requests to local port 9200 returned an empty reply, so they do not provide a
valid cluster/index or authenticated-login baseline. A best-effort live
filesystem size scan also raced active OpenSearch writes and encountered one
vanished segment; it is not a final cold-copy manifest. No workload was
stopped and no files were changed.

Diagnosis established that OIDC deliberately makes Dashboards return `401`
for an unauthenticated `/api/status` request, while its managed health check
accepted only `200` or `302`. The health check was corrected in
`deploy-opensearch-stack.yml` and syntax-checked. The normal single-stack
orchestrator could not apply it because this worktree has no generated stack
inventory. A direct managed playbook run rendered the corrected Compose file
but did not recreate the existing Dashboards container. The approved scoped
`pve-tiny-evacuation-opensearch-dashboard-compose-recreate` task then recreated
only that service from `/opt/opensearch-stack/docker-compose.yml`. OpenSearch
and Dashboards both reported healthy afterwards, and Dashboards' status
endpoint returned the expected `401`. Repeat the authenticated service and
consumer baseline before starting the 40014 cutover; the live filesystem scan
is still not a final cold-copy manifest.

The approved `pve-tiny-evacuation-opensearch-final-baseline` task then passed
the authenticated checks. OpenSearch was `yellow`, the acceptable baseline for
its single-node topology: 121 active primary shards, no pending tasks, and 98
unassigned replica shards. The data included current `tpot-events`, security
audit, Harbor and Wazuh findings, CVE exposure, GVM findings, saved-object and
security indices. Dashboards reported `green`; both OpenSearch and Dashboards
Docker containers reported healthy. Used persistent storage was about 1.28 GiB
under `/var/lib/opensearch-data` and 6.25 GiB under `/var/lib/docker`. These
are the service baseline and planning figures only: take the exact cold-copy
manifest after writers are quiesced and the source is stopped.

### OpenSearch CT 40014 cutover — completed

On 2026-10-24, `pve-tiny-evacuation-opensearch-cutover` created pve snapshot
`pre-evacuation-20261024` of the stopped target before source downtime. The
source CT was then stopped and set to `onboot=0`. Its cold
`/var/lib/opensearch-data` archive preserved numeric ownership, ACLs and
xattrs. A temporary extraction on pve contained 6,387 regular files and its
per-file SHA-256 manifest matched the stopped source:
`981cdd388f570dc4b8befef51a4965b00c9ed75c2ee3174e25a0e68c4042febe`.
The restored target had the same count, manifest and `101000:101000` top-level
ownership. The staged archive remains on the target root volume alongside the
pve snapshot and untouched stopped source as rollback/recovery evidence.

The target started alone on pve and was reconciled with the managed Dashboards
health-check fix. Both Docker services are healthy, OpenSearch is the expected
single-node `yellow`, the preserved Harbor/Wazuh/GVM index counts match the
baseline, and Dashboards is `green`. Target `onboot=1`; source remains stopped
with `onboot=0`. The approved backup enrollment removed only 40014 from pve
job `backup-8b90fc3e-c3a5`, retaining exclusions for 50011, 50012 and 50013.
A fresh `pbs-iscsi` snapshot backup succeeded as
`ct/40014/2026-10-24T01:05:16Z`.

### AI Services CT 50013 cutover — completed

On 2026-10-24, the approved AI Services cutover stopped CT 50013 on
`pve-tiny`, disabled source autostart, cold-copied the three persistent Docker
volumes (OpenWebUI, SearXNG and deep-research configuration), and restored
them on the existing pve target. The target is the sole running instance,
has `onboot=1`, and its OpenWebUI (`:8081`) and SearXNG (`:8082`) endpoints
returned HTTP 200. A new snapshot backup completed as
`pbs-iscsi:ct/50013/2026-10-24T03:05:31Z`. The pve backup job now excludes
only unrelated VMID 50011.

### CSE code-eval CT 100071 cutover — completed

On 2026-10-24, the approved CSE code-eval cutover drained the idle source,
stopped CT 100071 on `pve-tiny`, and disabled source autostart. Its excluded
`/srv/cyberseceval` mount was cold-archived with numeric ownership, ACLs and
xattrs; the archive SHA-256 is
`faac9cd7bb842ac96412553ccf2d97496b85f9bf01069ae737b5eb6c89faf31f`.
The archive was relayed through the operator workstation because node-to-node
SCP authentication was unavailable; no host authorization was changed.

A reviewed pve Terraform plan created CT 100071 with root and Docker storage
on `apps-containers`, the durable mount on `storage-containers`, and its
original `tvcse` address `192.168.100.71`. The durable mount was restored,
the target started alone, and `onboot=1` is set. The `cse-code-eval` and
Portainer-agent containers are running. Direct checks confirmed gcc/g++, CMake,
the pinned CybersecurityBenchmarks command-line runner, the restored durable
mount, and the route to cse-controller. A TCP probe to cse-controller port
8000 was refused because cse-controller intentionally exposes no listener on
that port; this was an invalid validation assumption, recorded without a
service or network change. The playbook's Step CA reachability check timed out
and was skipped by the role; this pre-existing condition was observed but not
changed.

A new snapshot backup completed as
`pbs-iscsi:ct/100071/2026-10-24T03:20:06Z`; it correctly excludes the durable
mount, whose cold archive remains the recovery copy. The stopped source is
retained for rollback soak.

### CSE controller CT 40070 cutover — completed

On 2026-10-24, the approved CSE controller cutover first confirmed all Celery
queues had no active or reserved work. The source was gracefully stopped and
set to `onboot=0`; its complete `/srv/cyberseceval` mount was cold-archived
with numeric ownership, ACLs and xattrs (SHA-256
`144151e007bb956ef18c5c4c0bf683ed72da6750eee9a8b32c30dec1a05820d0`).
The pve target was created on `apps-containers` with its durable mount on
`storage-containers`, restored through the operator workstation without
changing node-to-node SSH authorization, and started as the sole owner of
`192.168.100.70`.

The target profile initially omitted the existing `services/cse-panel` secret
reference required for the controller worker's Redis credential. That omission
was introduced by target migration configuration and was corrected by adding
the reference to the pve profile; the worker subsequently connected to Redis
and became ready. Step CA's timeout was observed and skipped by the role, with
no unrelated repair. The target has `onboot=1`; a fresh backup completed as
`pbs-iscsi:ct/40070/2026-10-24T03:31:19Z`, including root, Docker and the
durable mount. Retain the stopped source for rollback soak.

### CSE panel CT 20030 cutover — completed

On 2026-10-24, the approved panel cutover stopped CT 20030 on `pve-tiny`,
disabled source autostart, and cold-archived the complete root and Docker
state. Archive SHA-256:
`0abcd07e1fd46470c80483c2f064b0cc4df9ca031d9a30ed83a113959dc854e3`.
The managed pve target on `apps-containers` had its Redis AOF and panel state
restored before starting as sole owner of `192.168.20.30`. The panel UI on
port 8050 returned HTTP 200 and Redis was ready. The root panel-web endpoint's
HTTP 404 is existing route behaviour. Target `onboot=1`; source remains
stopped with `onboot=0`. A fresh backup completed as
`pbs-iscsi:ct/20030/2026-10-24T03:37:21Z`.

### Technitium CT 20017 cutover — completed

On 2026-10-24, the approved Technitium cutover stopped CT 20017 on
`pve-tiny`, disabled source autostart, and restored its cold root and Docker
archive on the managed pve target. Archive SHA-256:
`ad70c5be77b19d40756a06ccbcd6c9b91e72293ca397118c3ccb455af44fcd4d`.
An interrupted provision left `combined-ca.crt` as an empty target directory;
that migration-created artifact was removed before the scoped role resumed.
Technitium then served a recursive `github.com` A lookup and its HTTPS API
returned HTTP 200 on port 53443. Target `onboot=1`; source remains stopped
with `onboot=0`. A fresh backup completed as
`pbs-iscsi:ct/20017/2026-10-24T04:23:55Z`.

The resumed role later failed while enrolling the ancillary Wazuh agent. DNS
service health was unaffected; this pre-existing ancillary issue was recorded
without repair under the migration scope rule.

### Pentest runner CT 40072 cutover — completed

The imported stack definition, pve entrypoint and pve storage compatibility
mapping produce a reviewed target plan: five creates, zero changes and zero
destroys. It creates CT 40072 with four cores, 8192 MiB memory, 10G root and
30G Docker storage on `apps-containers`, with `tvcse` address
`192.168.100.72/24`. The migration entrypoint explicitly keeps it stopped and
with autostart disabled for the cold restore. The VMID is absent from pve and
`apps-containers` has about 382 GiB free.

The live source has no active Strix or BoxPwnr workload. Its enabled viewer
supervisor listens on port 18820; the observed Strix processes are old defunct
children. Preserve the complete root filesystem and separate Docker mount,
including about 676 MiB under `/opt/BoxPwnr`, 15 MiB under
`/root/strix_runs`, and 413 MiB of Docker state. The prior PBS test restore
remains the recovery fallback if a final cold read fails.

The approved cutover stopped source CT 40072 and set `onboot=0`, created the
managed pve target stopped, and cold-restored its complete root and Docker
filesystems with numeric ownership, ACLs and xattrs. The completed root archive
was 4.30 GiB with 159,217 entries (SHA-256
`3a32b0bad2977e5e22cc9a73145a050ca4c7663eff01a370f10504acc19421c1`);
the Docker archive was 207 MiB with 348 entries (SHA-256
`8b98a8cc7951214160ebb0734d11163de27147faeb2e341fc231577f10303533`).
After restoration, Terraform made its reviewed single in-place update to set
the target running and `onboot=1`.

The target viewer supervisor is active and enabled, `/healthz` returns
`{"ok": true}`, Portainer agent is running, all 80 preserved Strix run
directories remain present, and the Framework port 8080 route succeeds. The
source remains stopped with `onboot=0`; target state has a zero-change
Terraform plan. A new backup completed successfully as
`pbs-iscsi:ct/40072/2026-10-24T04:36:03Z`, including root and Docker.

### Secpipe CT 50012 preflight — passed

On 2026-10-24, `pve-tiny-evacuation-secpipe-preflight` found the source CVE
enrichment and T-Pot ingest timers active and waiting, with successful last
runs. The CVE service last ran successfully on the prior scheduled window;
the T-Pot ingest service last ran successfully nine minutes before the check.
The source's only inspected local state candidates were small managed
`/opt/cve-enrichment-sync` (172,032 bytes) and
`/opt/tpot-findings-ingest` (32,768 bytes) directories. The pve target is
stopped and matches source CPU, memory, root/Docker mount sizes, unprivileged
mode and `tvai` addressing; its `infrastructure-containers` pool had about
92 GiB free.

Using secpipe's scoped OpenSearch credential from the running source, a
read-only request to the migrated pve OpenSearch returned the expected
`unified-cve-exposure` count of 15,361. That scoped writer identity lacks
cluster-monitor permission, so it does not return the cluster-health field;
the permitted index read confirms the actual secpipe-to-OpenSearch path.
No persistent application data needs a cold copy. Re-provision the target
from managed secrets/configuration before enabling its timers, and run one
bounded enrichment only after the source stays stopped.

### Secpipe CT 50012 cutover — completed with recorded pre-existing issue

On 2026-10-24, the approved `pve-tiny-evacuation-secpipe-cutover` task stopped
the source CVE-enrichment and T-Pot-ingest timers, stopped source CT 50012,
and set its `onboot=0`. The existing pve target was then started alone, so the
shared address was never active on both nodes.

The normal provisioning path could not complete in this worktree because its
ignored generated inventory is absent, and direct foreground playbook runs are
limited by the interactive execution window before they reach the role tasks.
A temporary, scoped role reconciliation placed in the canonical playbook
directory used the feature flags declared for this stack and completed with
`ok=38 changed=13 failed=0`. It installed and enabled the CVE-enrichment,
deep-dive, and T-Pot-ingest managed services and timers, including their
managed credentials. The temporary reconciliation playbook was removed after
the successful run.

The initial finalization attempt found the obsolete `services/pentagi` profile
reference, not a missing OpenBao secret. That stale entry was removed from the
manifest and profiles, and the pve production wrapper then loaded normally.
The target's T-Pot tunnel key was initially empty because `services/tpot` was
also absent from the pve profile. Adding the required profile entry and
reconciling only the T-Pot role restored it. A manual T-Pot run established its
tunnel, processed and indexed 16,590 events with zero errors, and advanced its
cursor.

The bounded, non-writing CVE check reached the target OpenSearch but received
401 responses while aggregating the Harbor, GVM and Wazuh findings indices.
The OpenSearch role exists and is assigned to the service account; the target
has a stale credential file from its prior stopped copy. Per operator
direction, this pre-existing credential issue was recorded and was not rotated
or otherwise repaired during migration. A proposed live capped enrichment was
not run because it could send derived vulnerability findings to Anthropic.

The target now runs with `onboot=1`; source remains stopped with `onboot=0`.
Only 50012 was removed from pve backup job `backup-8b90fc3e-c3a5`'s exclusion
list, retaining 50011 and 50013. A new snapshot backup completed successfully
as `pbs-iscsi:ct/50012/2026-10-24T02:48:01Z`. Retain both CTs for rollback and
track the CVE credential issue separately from this evacuation.

1. Record branch/HEAD and freeze concurrent Terraform work on these eight
   VMIDs. Copy only the **real leaf** `terraform.tfstate.d` directories from
   the original checkout into the matching ignored worktree directories.
   There are source states for seven guests; pve target states exist only
   for 40014, 50012 and 50013. Do not copy `.terragrunt-cache` or generated
   inventories as the source of truth. Use `umask 077`, preserve file modes,
   calculate SHA-256 on source and copy, and keep a second private backup of
   each state before any operation that can write it. Check state resource
   VMID/node against the live API. Never put states, checksums of secret
   values, backup archives, or logs containing credentials in Git.
2. Save read-only `pct config` equivalents for each guest on both nodes:
   rootfs, every `mpN` including `backup=`, `net0`, `onboot`, idmap, features,
   tags and mount sizes. Save running status, source disk used bytes, target
   pool available bytes, and pve memory. The read-only API can provide these
   without SSH; use the production wrapper and read-only token. Compare the
   eight source configs with the table below before proceeding.
3. Confirm PBS datastore/namespace and actual backup volume IDs from the
   backup owner account. The latest task log alone is insufficient. Do a
   **test restore to an unused VMID on isolated networking**, then inspect
   included mounts and service data; destroy the test guest under its own
   scoped approval. If PBS access cannot be established, stage a verified
   cold archive for each stateful path before erasing or shutting down any
   source. Keep archives outside the repo with mode 0700 directories and
   0600 files.
4. Capture health baselines: OpenSearch cluster/index counts and security
   login; secpipe timer and last successful sync; OpenWebUI login/chats;
   CSE queue depth and active jobs; Technitium `.15` and `.17` UDP/TCP
   answers plus cluster status. Write down a rollback decision time and
   maximum acceptable outage per guest before its approval. Do not invent
   these limits during an outage.
5. Verify `vm.max_map_count >= 262144` on pve and actual VLAN 100 reachability
   after the separately approved `tvcse` SDN task in plan.md. Confirm an
   unused temporary test IP before any temporary VLAN test guest/interface.

## 1. Source definitions and capacity choices

Create a pve `terragrunt.hcl` for each managed guest absent on pve by copying
the shape of its pve-tiny entrypoint. This now includes `pentest-runner`.
Keep the pve-tiny entrypoints and state for rollback. Update stack storage
profiles **one guest at a time immediately before its pve plan**: the
pve-tiny-only `platform-nvme`/`durable-nvme` names do not exist in
`storage/pve.yaml`. Record the old values and use these pve profiles:

| VMID | pve root/Docker profile | pve data profile | Provision/restore decision |
|---|---|---|---|
| 40014 | `platform-monitoring-zfs` (matches stopped pve copy) | `durable-zfs` | Refresh `/var/lib/opensearch-data`; do not reuse its stale contents |
| 50012 | `platform-default` (matches stopped pve copy) | none | Re-provision systemd pipeline; verify no local state was added since earlier move |
| 50013 | `platform-default` (matches stopped pve copy) | none | Refresh the three named Docker volumes below |
| 40070 | `platform-apps-zfs` | `durable-zfs` | Copy `/srv/cyberseceval` including private SSH key and results |
| 100071 | `platform-apps-zfs` | `durable-zfs` | Rebuild `/srv/cyberseceval` only after confirming no valuable current run data; its mount is excluded from PBS |
| 20030 | `platform-apps-zfs` | none | Copy `/srv/cse-panel/redis-data` after stopping Redis and draining jobs |
| 20017 | `platform-monitoring-zfs` | none | Re-provision and rejoin secondary to primary; verify whether local config needs a copy first |
| 40072 | `platform-nvme` compatibility mapping to `apps-containers` for both volumes | none | Create the managed pve baseline, then restore the stopped source's full root and Docker contents; retain the verified PBS restore as recovery evidence |

Confirm real free bytes and backend identity immediately before cutover.
Do not count the same ZFS pool through two aliases. Reserve room for the
restored volumes, snapshots and a new backup; a mere thin allocation total
is not a capacity proof. If a selected pool lacks space, choose a different
profile and review a new Terraform plan before approval.

## 2. Rehearse the two Terraform paths

For **40014/50012/50013**, copy the existing pve state into the worktree.
The stopped pve CT remains Terraform owned by that state. Inspect its exact
live config, update the stack profile to match its existing root/Docker/data
storages, and run a pve `terragrunt plan` with the copied state. Permit only
documented inventory/provisioner changes; any replacement, deletion, or
volume move is a stop. Keep its old data volume untouched until the current
source has been copied and verified. Do not create another CT with its VMID.

For **40070/100071/20030/20017**, the new pve environment starts with no
pve state and no pve CT. Only after confirming both absences, run a pve
`terragrunt plan` expecting one new CT and related local/runtime resources.
Review all resolved storage IDs, sizes, network bridge, IP and onboot.
The pve-tiny state stays separate. After source stop and final export,
`terragrunt apply` creates the new CT. The provider starts it, so verify
the old source is stopped and cannot autostart **before** apply. A failed
apply may have created a partial CT; inspect API and state before retrying.

For all managed plans use the appropriate production wrapper and explicit
`TF_WORKSPACE=pve` or `pve-tiny`, and the per-environment
`terraform/lxc/environments/<node>/<stack>` working directory. A plan is
read-only; an apply is a separately approved production mutation. Do not
import a pve-tiny state file into the pve workspace: it names another node
and would make the pve plan try to relocate/replace a live source.

For **40072**, the merged stack definition and playbook now provide the pve
baseline. The read-only source config confirms an unprivileged Debian LXC,
10G NVMe root, 30G NVMe Docker mount, `tvcse` at `192.168.100.72/24`, 8192
MiB memory, 4 cores and no extra mount. The exact PBS snapshot was already
test-restored successfully, but the real cutover preserves the current state:
stop and disable source autostart, apply the reviewed pve plan with target
autostart disabled, cold-archive the complete root filesystem and the Docker
mount separately with numeric ownership, ACLs and xattrs, restore both into
the stopped target, compare `pct config` field by field, then start and test.
The `platform-nvme` stack profile maps to `apps-containers` only on pve, so
the source definition remains valid until cutover. If either source archive
has a read or integrity error, stop and restore the already-tested PBS backup
instead of starting a partial target.

## 3. Per-guest approved cutover transaction

Use one approval name `pve-tiny-evacuation-<stack>` per guest. Preflight
names **both** nodes, the VMID, target pools, final archive path, commands,
and rollback trigger. Production commands use `./with-secrets-prod-tiny`
for pve-tiny and `./with-secrets-prod` for pve; root SSH/PCT is mutating
and remains behind the same approval flow. An approval does not cover a
different VMID or unrelated backup/SDN changes.

1. Finish a bounded service baseline. Quiesce the application: stop new CSE
   jobs and drain the queue for CSE, stop the secpipe timer, stop writes to
   OpenSearch/OpenWebUI, and confirm no PBS job is touching the CT. Record
   the last application consistency point.
2. Stop source with `pct shutdown <VMID> --timeout 180`; if it does not stop,
   investigate rather than force-stop a database. Set `pct set <VMID>
   --onboot 0`, verify `pct status` is stopped, then verify its IP no longer
   answers. This is the start of downtime.
3. Make the final **cold** copy from source. For a managed LXC use
   `pct mount <VMID>` on pve-tiny, archive the precise persistent paths with
   `tar --numeric-owner --xattrs --acls`, then `pct unmount`. Verify tar exit
   status, SHA-256, file count, byte count and readable sample files. Keep
   the source mounted read-only in intent: do not delete or overwrite any
   source file. If any NVMe read fails, stop and evaluate the latest verified
   PBS restore; do not proceed with a partial archive.
4. For an existing stopped pve copy, keep a separate snapshot/archive of
   its stale contents before replacing application data. For a new guest,
   apply the reviewed pve plan now, then stop the newly created CT before
   importing files. Mount target with `pct mount`, restore archives using
   `tar --numeric-owner --xattrs --acls`, check ownership and contents, and
   unmount. Confirm matching unprivileged/default idmap on source and target
   before using a host-side numeric-owner tar; otherwise use a documented
   UID/GID translation. Do not replace an entire Docker root with an archive
   from another Docker version.
5. Start only the pve CT. Run `./with-secrets-prod scripts/provision.sh
   --stack <stack>` for the actual managed stack (after its pve inventory
   exists), then run the specific health checks below. If the playbook could
   reset imported state, import after initial provisioning and rerun only
   the idempotent parts verified safe for that stack. Capture a bounded
   Terraform plan after provisioning and check it has no destructive drift.
6. Observe the service through its real consumer path, not just `pct status`.
   Check pve memory, storage and error logs. Run a fresh pve backup and
   verify its task and presence in PBS. For the three old pve copies, first
   remove VMIDs 40014/50012/50013 from pve's exclusion list under a
   **separate scoped backup-job approval**; do not change 50011 within this
   task. Record the backup ID/namespace.
7. Report success or rollback before moving to the next guest. Keep the
   source stopped, `onboot=0`, and its state/volumes/backup intact throughout
   the soak. Never allow both guests with the same IP to run.

**Rollback:** stop the pve CT and set its onboot to 0; confirm its IP is
silent. If pve accepted writes, export them or explicitly accept their loss
before reversal. Start the untouched pve-tiny CT and restore onboot only
after its service check passes. Verify the consumer path and record the
data reconciliation still needed. Do not destroy either CT during rollback.
If the failing NVMe prevents the source from starting, use the verified PBS
restore/cold archive path instead; the old source is not a dependable sole
rollback copy.

## 4. Service-specific proof, in cutover order

| Order | VMID | Quiesce and data | Passing proof | Rollback trigger |
|---|---:|---|---|---|
| 1 | 40014 | Stop ingestion; cold copy the full 150G mount's used data at `/var/lib/opensearch-data` | Cluster green/yellow as baseline; compare index names/document counts and security index; Dashboards Authentik login; Harbor/GVM ingestion and Grafana reads | Missing index/security state or consumer failure |
| 2 | 50012 | Stop secpipe timer; confirm its role has no locally persistent state before re-provision | Timer/unit healthy; one bounded CVE enrichment reaches OpenSearch and MCP without duplicate full sync | Sync fails or writes wrong index |
| 3 | 50013 | Stop app writes; copy `ai-services-openwebui-data/_data`, `ai-services-searxng-data/_data`, `ai-services-deep-research-config/_data` under `/var/lib/docker/volumes` | OpenWebUI users/chats and login, SearXNG query, research state, model route and ingress | Missing user/chat/research state or broken login |
| 4 | 100071 | Confirm no active evaluation; `/srv/cyberseceval` is documented disposable, but inspect current runs before deciding rebuild | Pinned checkout/toolchain and one bounded isolated evaluation; forbidden network paths remain blocked | Isolation failure or required run state missing |
| 5 | 40070 | Drain jobs; cold copy `/srv/cyberseceval`, including `runs/`, `results/`, `reports/`, config and SSH key | Worker reaches Framework and Harbor on allowed paths, key usable, prior results visible | Key/results missing or worker cannot execute |
| 6 | 20030 | Drain jobs; stop Redis cleanly; copy `/srv/cse-panel/redis-data` and any other live state found in root/Docker | Redis AOF loads, queue/Flower consistent, panel Authentik login and one small end-to-end evaluation | AOF/queue mismatch or login failure |
| 7 | 40072 | Inspect application/process inventory and owner; test full PBS restore of root and Docker first, then restore the same backup to pve | One bounded real pentest job and required network isolation | Any missing state, job failure or isolation failure |
| 8 | 20017 | Confirm primary `.15` healthy; stop secondary; decide copy versus rejoin from cluster contract | `.17` UDP and TCP DNS, authoritative zone and recursive answers, cluster sync, client/router resolution; primary `.15` still healthy | Wrong answers, failed sync, or client resolution failure |

Keep secpipe paused during the OpenSearch cutover; never run its test
against stale OpenSearch data. CSE guest order may be adjusted only after
verifying controller/panel dependencies and draining jobs. Do not treat
the table as permission to skip those checks.

## 5. Shutdown and closeout

After all eight targets have passed service checks, have fresh pve backups,
and survived the agreed soak, check source CTs remain stopped/onboot=0,
target autostart and pve headroom. Schedule a controlled pve reboot check
only if its blast radius is separately approved; otherwise mark that
completion criterion pending. Approve pve-tiny shutdown as its own task.
Keep its boot SSD and stopped CT metadata intact during the RMA window.
NVMe erasure and RMA are separate destructive tasks after recoverability
is proven. Reconcile the surviving pve Terraform plans and update network
membership; retire pve-tiny state only in a later approved decommission.
