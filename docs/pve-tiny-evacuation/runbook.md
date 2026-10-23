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

Create a pve `terragrunt.hcl` for each of the four managed guests absent on
pve (`cse-controller`, `cse-code-eval`, `cse-panel-stack`,
`technitium-tiny-stack`) by copying the shape of its pve-tiny entrypoint.
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
| 40072 | `apps-containers` for both volumes | none | Manual guest: restore the verified whole-CT PBS backup (10G root, 30G Docker) to pve; retain manual ownership pending a later IaC task |

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

For **40072**, the read-only source config confirms an unprivileged Debian
LXC, 10G NVMe root, 30G NVMe Docker mount (included in backup), `tvcse`
at `192.168.100.72/24`, 8192 MiB memory, 4 cores and no extra mount.
Use a **whole-CT PBS restore** to an otherwise absent VMID 40072 on pve,
mapping root and Docker to `apps-containers`, with its original network
configuration and start disabled until inspected. First test that exact
backup on an unused VMID and isolated interface, then destroy the test CT.
For the real restore, stop/onboot-disable the source, restore on pve, compare
`pct config` field by field with the saved source config, explicitly set the
bridge to pve's `tvcse` if needed, then start and test. Do not use Terraform
on this CT until a separately reviewed import/provisioning project defines
it. If the PBS restore is unavailable or omits Docker, block this guest's
cutover rather than improvising a manual `pct create` during downtime.

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
