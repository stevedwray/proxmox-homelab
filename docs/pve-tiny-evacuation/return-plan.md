# Return to pve-tiny after the NVMe replacement

Status: **plan only; nothing executed.** Written 2026-10-24 from the
evacuation plan/runbook, the issues met during it, and a parity audit of
the stopped pve-tiny sources against the live pve targets. Revised
2026-10-27 after review: added the branch/Terraform-state handoff, VMID
collision handling, edge/firewall/monitoring items, sizing, and a gate
checklist (below). Step-level commands are still parameterised; see
"What this plan does not yet fix".

## Decisions

- **All eight evacuated guests return** (40014, 50012, 50013, 40072, 40070,
  100071, 20030, 20017), keeping VMIDs and IPs.
- **The pve-side `tvcse` SDN zone/VNet stays** after the return. Removing it
  would be a separate, later task.

## What the evacuation taught us

| # | Issue | Cause | Return-plan answer |
|---|---|---|---|
| 1 | eval-runner was missing on 50013 and the panel showed "no model loaded" | Cutover refreshed 3 Docker volumes on an older stopped pve copy; units, `/etc`, `/opt` state were not in the checklist | Parity manifest of the live source before it is stopped (R3 step 1) |
| 2 | Smoke checks tested each guest alone | The panel reads a key that another guest writes | Consumer-path matrix (below) |
| 3 | Stale stopped copies used as targets | Secpipe kept a stale CVE credential file | Create fresh targets; never reuse a stale copy |
| 4 | Profile gaps in `secrets/manifest.json` | pve profile lacked `services/cse-panel` and `services/tpot`; a stale `pentagi` entry | Verify the pve-tiny profile loads and has every `services/*` the eight stacks use before R3 |
| 5 | No generated inventory in the worktree | `provision.sh --stack` could not run; temporary playbooks were used | Generate inventory first; use only `scripts/provision.sh` |
| 6 | Host keys changed | Guests rebuilt or restored | Refresh `known_hosts` deliberately, comparing fingerprints with `pct exec` |
| 7 | Ancillary failures mixed in | Step CA timeout, Wazuh enrollment, stale CVE credential | Fix or log them before R3 so they are not confused with migration faults |
| 8 | **The evacuation branch is 159 commits behind `stable`** | Targets were provisioned from it | Return from a branch cut from current `stable` (see Parity audit) |

## Parity audit, 2026-10-24 (read-only)

Method: each stopped source's root and Docker volumes were mounted
read-only (`ro,noload`) on pve-tiny and compared with its live target:
enabled units and timers, custom unit files, `/opt`, `/srv`,
`/usr/local/bin`, cron, Docker volume names and `/etc`. The mounts were
removed afterwards. Checked: file presence, not file contents.

| VMID | Result |
|---|---|
| 40014 opensearch | Matches |
| 40072 pentest-runner | Matches |
| 100071 code-eval | Matches |
| 50013 ai-services | Matches **after** the 2026-10-24 redeploy; the target had none of the eval-runner units, `/etc/eval-runner` or `/opt/eval-runner*` before it |
| 50012 secpipe | Target lacks `wazuh-agent` |
| 20030 cse-panel | Target lacks the `docker-live-usage-report` timer, service and `/opt/docker-live-usage-reporter` |
| 20017 technitium-tiny | Target lacks `docker-live-usage-report` (timer and script), `/opt/cadvisor`, `wazuh-agent` and `unattended-upgrades` |
| **40070 cse-controller** | **Target lacks: the `node-exporter-cert-renew` timer and `/etc/node_exporter` (TLS cert, renewal script), `/usr/local/bin/step`, `/srv/pentest-worker` (SSH key `id_pentest_runner`, launcher, run-manifests, venv), `/srv/pentest-research` and `/srv/pentest-target-guard` (51 MB each)** |

For 40070 the live source also ran three containers the target does not
have: `cse-controller-pentest-worker`, `-pentest-research-worker` and
`-pentest-viewer-proxy`. The `pentest-*` stack code is on `stable` but not
on `work/pve-tiny-evacuation`, so the target was provisioned without it.

### Open items before the NVMe is erased

These live only on the stopped sources and are lost on erase:

1. 40070: `/srv/pentest-*` (key, run-manifests, venv, research data).
2. 40070: `/etc/node_exporter` (cert, `provisioner-password.txt`,
   `renew-cert.sh`).
3. 20017, 20030: reporter scripts and timer units (reproducible from
   playbooks; confirm by running the full stack provision).
4. Wazuh agent enrollment on 50012 and 20017.
5. 50013: eval-runner history and results under `/opt/eval-runner*` and
   the Docker volumes. The audit shows the units and env files were
   present; confirm where result history lives.

Recovery path for 1-3: re-run the full `scripts/provision.sh --stack
cse-controller` (and the other stacks) from a branch cut from current
`stable`, and copy anything not reproducible out of the stopped source
before the erase. **Do not approve the pve-tiny shutdown or the NVMe erase
until every item above is closed or explicitly accepted as lost.**

## Facts the return depends on

- The stopped sources' NVMe volumes (`nvme-lvm`) die with the erase. After
  that, pve copies and PBS are the only copies. The "stopped source as
  rollback" model ends.
- Four guests keep root and Docker on the boot SSD (`local-lvm`): 100071,
  40070, 20030, 20017. Their stopped sources survive but are stale.
- pve accepted writes during the gap (OpenSearch indices, Redis queue and
  results, Technitium zones, OpenWebUI chats). Every return starts from a
  fresh cold copy of the pve guest, never from the old source.
- Stack profiles name `platform-nvme` and `durable-nvme`. The new drive
  reuses those storage IDs, or every profile is remapped.

## Phases

### R1. pve-tiny rebuild (when the new NVMe arrives)

- SMART baseline for the new NVMe; wipe-verify of the old one is a
  separate, later task.
- Recreate storage `nvme-lvm` (same ID) on the new drive.
- Remove stale CT configs on pve-tiny that point at the erased volumes;
  then reset or `terraform state rm` the matching state so a plan cannot
  see phantom guests. Reviewed `terragrunt plan` before any apply.
- Confirm the `pve-tiny` profile in `secrets/manifest.json` loads and holds
  every secret the eight stacks need.
- Generate the inventory for pve-tiny before starting.
- Restore the pve-tiny PBS job and its exclusions; confirm a backup runs.
- Confirm `cse_seg`/VLAN 100 is intact on pve-tiny.

### R1 read-only baseline, 2026-10-27 (pve-tiny just booted)

- Kernel `7.0.14-20-pve`. API reachable; pve-tiny is up with all ten CTs
  **stopped** (40070, 100071, 50012, 40014, 20030, 20017, 50013, 40072,
  50011, 910).
- New NVMe `/dev/nvme0n1` (Kingston SNV3S2000G, 2 TB): SMART PASSED, 0 power-on
  hours, 0 data written, 0 media errors, 100% spare, 27 C. Blank: no LVM or
  partitions listed.
- Storage `nvme-lvm` is defined (lvmthin) but **inactive**, 0 bytes. It must
  be recreated on the new drive with the same ID. `local-lvm` has about
  28 GB free; boot SSD wearout 88% remaining.
- The pve-tiny PBS job runs 12:30 daily and excludes only 910; it will fail
  or skip guests until their volumes exist, so expect noise until R3.
- The stopped CT configs still reference the lost NVMe volumes (cleanup in
  R1). No guest has been started.

### R1 progress, 2026-10-27

- **Done (operator-run):** PV/VG `nvme-lvm` on `/dev/nvme0n1` and thin pool
  `nvme-lvm` (1.77 TiB, 16G metadata, 0.00% used); `pvesm status` shows the
  storage `active`. The classifier blocks agent-run remote writes on
  pve-tiny, so the operator runs mutating commands there.
- **Stale CT configs (read-only look):**
  - 40014, 50012, 50013, 40072: every volume is on the lost `nvme-lvm`.
    Their configs are phantom and safe to remove once nothing needs them.
  - **40070 and 100071** also have an `nvme-lvm` data mount at
    `/srv/cyberseceval` (lost), but root and Docker are on `local-lvm` and
    **survive**.
  - **20030 and 20017**: root and Docker are on `local-lvm` and survive.
  - So the four boot-SSD sources are the only remaining copy of open items
    1-4 (40070 `/srv/pentest-*` and `/etc/node_exporter`; reporter scripts;
    Wazuh enrolment state). **Salvage those before destroying them**, and
    do not start them (their 40070/100071 configs reference a missing mount).
  - Only 50013's eval-runner history (open item 5) was on the lost drive;
    the pve copy is now its sole authority.

### Open item 5 resolved, 2026-10-27: eval-runner history was NOT carried over

Read-only check of CT 50013 on pve:

- `/srv/eval-runner/results/` holds only runs made since the cutover
  (2026-10-24 on: gemma4 and glm-5.3-flash pilots, `_publish-state.json`).
- **`/srv/eval-runner/results/_historical/` is missing.** It held the
  imported Ollama-era GPQA/IFEval files (36 files, about 42 MB) plus the
  BFCL and AgentBench imports. The cutover copied only three Docker volumes;
  `/srv/eval-runner` was not in the checklist, and the NVMe copy is gone.
- Recovery sources, best first:
  1. PBS snapshots of 50013 in the `pve-tiny` namespace:
     `pbs-iscsi:backup/ct/50013/2026-10-23T05:32:21Z` and
     `...2026-10-23T23:33:12Z` (pre-cutover; the newer is the final state).
  2. Re-import from framework/garuda using the two "Operator" blocks in
     `docs/eval-runner/plan.md` (GPQA/IFEval from `~/eval-harnesses/results`;
     BFCL and AgentBench via `import_history.py`).
- Restore is additive into `_historical/`; it must not touch the newer
  run directories. It is a pve production write and needs its own approval.
- **Restored 2026-10-27.** `_historical/` extracted from
  `ct/50013/2026-10-23T23:33:12Z` (pve-tiny namespace, `root.pxar`,
  pattern `/srv/eval-runner/results/_historical/**`; 56 files, 42 MB) on
  pve-tiny, streamed to CT 50013 on pve by the operator, owner 1000:1000.
  `/usr/local/bin/eval-run results` shows the historical section again.
  The temp directory on pve-tiny was removed. Note: `eval-run` is not on
  the PATH under `pct exec`; call it by full path.
- Lesson for the return: add `/srv/<stack>` data directories to the parity
  manifest, not only `/opt`, `/etc`, units and Docker volumes.

### Open items 1-2 salvaged, 2026-10-27 (40070)

- The stopped 40070 root volume (`pve/vm-40070-disk-0`, boot SSD) was
  activated and mounted read-only (`ro,noload`), then unmounted and
  deactivated. Nothing on it was modified.
- Archived with `tar --numeric-owner --xattrs --acls`: `/srv/pentest-worker`
  (SSH key `id_pentest_runner`, launcher, 19 run-manifests, `.venv`),
  `/srv/pentest-research` (GVM gateway key, `known_hosts`, snapshots, M01
  research data), `/srv/pentest-target-guard`, `/etc/node_exporter` and
  `/usr/local/bin/step`: 8,862 entries, 38 MB.
- Copies, both mode 0600 in a 0700 directory, identical SHA-256
  `acf58478bd05276b4a7910d8dc6e57da4b03be6b364af88609956a95b94d4b05`:
  `pve-tiny:/root/salvage-40070/` and `pve:/root/salvage-40070/`.
- The live pve 40070 has **none** of these (only `/srv/cyberseceval`), so the
  pentest worker, research worker and node_exporter cert are absent on the
  live controller today. Restoring them on whichever node runs 40070 is part
  of R3 for that guest (extract the archive, then the full stack provision).
- Items 3-4 (reporter scripts, Wazuh enrolment) remain reproducible from
  playbooks; no copy taken.

### R1 progress, 2026-10-27 (continued)

- **Phantom CT configs removed (operator-run):** 40014, 50012, 50013 and
  40072 configs were checked (stopped, only `nvme-lvm` volumes), backed up
  to `pve-tiny:/root/phantom-ct-configs-2026-10-27/`, then deleted.
  `pct list` now shows 910, 20017, 20030, 40070, 50011, 100071.
- **Return worktree:** `.worktrees/pve-tiny-return`, branch
  `work/pve-tiny-return` cut from `origin/stable` (344a50f5). Stable already
  has `environments/pve-tiny/*` for all eight stacks.
- **State copied** (ignored files) for seven stacks from the main checkout;
  `pentest-runner` has no pve-tiny state. SHA-256 of all seven copies match
  the originals. Source state was not modified.
- **Read-only plans** (`./with-secrets-prod-tiny terragrunt plan
  -lock=false`; this also proves the pve-tiny profile loads):

  | Stack | Result |
  |---|---|
  | opensearch-stack, secpipe-stack | container "has been deleted" outside Terraform, so it is **created**; 5 add, 4 destroy |
  | ai-services-stack | same; 6 add, 5 destroy (adds `stack_cleanup`) |
  | pentest-runner | no state; 5 add, 0 destroy |

  The "destroys" are only generated inventory/SDN vars and bookkeeping
  resources being replaced (`local_file`, `null_resource`,
  `terraform_data`), not a guest. No `state rm` is needed: the plan already
  treats the missing containers as absent. Review each plan again right
  before its apply; the plan output path in `network.intent` changes
  with the worktree.
- Plans for 40070, 100071, 20030 and 20017 were not run: their stale
  sources still exist on the boot SSD and are handled in R3 (VMID collision
  section).

### Method per guest (provisional, decided 2026-10-27)

Method A = fresh Terraform target + cold data copy + full provision.
Method B = fresh backup of the stopped pve CT, restore on pve-tiny, import
into state, then full provision. Both start from a fresh copy of the pve
guest taken after its writers are quiet; never from an older backup.

| Order | Guest | Method | Note |
|---|---|---|---|
| 1 | 20017 Technitium | A | Small |
| 2 | 50012 secpipe | A | Stateless |
| 3 | 50013 ai-services | A, revisit after R2 | B possible if volumes are large |
| 4 | 40072 pentest-runner | A | Restore root/Docker over the fresh target |
| 5 | 100071, 40070, 20030 | A | 40070 also gets the salvage archive |
| 6 | 40014 opensearch | B, revisit after R2 | 150G data mount; needs the PBS namespace question settled; ingestion paused first |

Note: node-to-node SSH is not available, so cold copies relay through the
operator workstation. That makes the 150G OpenSearch copy slow; it is the
main argument for B.

### PBS targets for method B (read from the PBS server, 2026-10-27)

- Datastores: `iscsi-backup` (primary; about 115 GiB free of 1.0 TiB, GC
  03:00, verify-new on) and `usb-backup` (path `/mnt/usb-dispatch`; about
  1.8 TiB free of 3.6 TiB, GC 15:00). Only `iscsi-backup` is configured as a
  Proxmox storage on pve and pve-tiny.
- `usb-backup` is a **pull replica** of `iscsi-backup`: sync job daily 13:00,
  root namespace, `remove-vanished` **false**. Normal flow is backup to
  iscsi, then sync to usb.
- Prune: `iscsi-backup` keep-last 2 (every 2 h); `usb-backup` keep daily 8,
  weekly 4, monthly 2 (14:00). So iscsi holds only 2 restore points per
  guest; usb holds the history (pve-tiny namespace there: 7-10 snapshots per
  guest, last 2026-10-23; root namespace: pve's guests, last 2026-10-26).
- Method B (OpenSearch, possibly AI Services): write the fresh backup of the
  stopped pve CT **directly to `usb-backup` in a dedicated namespace**
  (`return-staging`), not iscsi, so the 115 GiB on iscsi is not at risk.
  The pull sync never writes to usb outside what it pulls, and
  `remove-vanished=false` means it will not delete the staging namespace.
  Needs a PBS storage entry for `usb-backup` on pve (to write) and on
  pve-tiny (to restore): two small reversible config changes, each approved
  separately. The staging copy is not replicated back to iscsi; delete it
  after the soak and let usb GC run.
- Open check: confirm the usb prune job's namespace scope will not touch
  `return-staging` (a fresh newest snapshot is retained by keep-daily 8
  regardless).

### R3 guest 1: Technitium 20017 (returned 2026-10-27)

Method A. `scripts/pve-tiny-return.sh 20017 <phase>` (generic per-guest script, one settings block per VMID): `check`, `copy`,
`create`, `restore`, `provision`, `verify`, `rollback`. State (archive,
checksums, baseline manifest) lives in `~/.local/state/pve-tiny-return/<vmid>/`;
each phase refuses to run until the previous one completed. 20017 is a
cluster **secondary**; the playbook does not join the cluster, so the 44 MB
`technitium-stack_technitium-config` volume is copied to preserve membership.
Fallback if the join breaks: rejoin as an operator step
(`docs/lan-dns-technitium/README.md`). Baseline 2026-10-27: `.15` and `.17`
both answer UDP and TCP; `technitium-tiny.cluster.lab...` resolves to `.17`.
Approval name: `pve-tiny-return-technitium`.

### Lesson from the first Technitium apply (2026-10-27): SDN null_resource replacement

Planning from the return worktree changes the paths held in the state's
`null_resource.configure_network_sdn_attachment` triggers, so Terraform wants
to **replace** it. Its destroy-time provisioner runs
`destroy-network-sdn-vnet.yml`, which would remove the VNet. The
`network_sdn_allow_destroy: false` guard aborted the apply before anything
changed (all four pve-tiny vnets verified intact, CT not created). The
earlier read-only plans listed this as one of the "destroys" and it was
wrongly described as harmless bookkeeping.

Fix, applied to every return: back up the worktree's state copy, then
`terragrunt state rm 'null_resource.configure_network_sdn_attachment[0]'`
before planning, so it plans as a create. Never set
`NETWORK_SDN_ALLOW_DESTROY_OVERRIDE`. The return scripts now do this and
refuse to apply if the plan replaces that resource or a container.

**Result 2026-10-27:** `copy` (40 MB archive, sha256 verified, baseline
manifest 240 lines), `create` (stale CT destroyed; apply after the SDN
`state rm` fix; 5 added), `restore`, `provision` (113 ok, 64 changed, **0
failed**; the Wazuh enrolment that failed during the evacuation succeeded)
and `verify` completed. CT 20017 runs on pve-tiny (`onboot=1`); pve copy is
stopped with `onboot=0` for the soak. Both resolvers answer UDP and TCP;
technitium logs show zone refresh from the primary `.15` and the cluster
config saved, so the restored volume kept cluster membership. Manifest diff
vs the pve source is additive: `wazuh-agent`, `unattended-upgrades`,
`cadvisor` and the apt timers, i.e. what the evacuation audit found missing.
One script bug found and fixed (checksum check ran from the wrong
directory; failed safe before any change). Still to do for this guest:
confirm the primary UI shows `.17` connected, take a backup on pve-tiny,
refresh `known_hosts`, then soak before destroying the pve copy under its
own approval.

### R3 guest 2: secpipe 50012 (returned 2026-10-27, Wazuh enrolment pending)

Method A, stateless: `scripts/pve-tiny-return.sh 50012 <phase>`. Verified
read-only: only the Portainer agent container, no data volumes; both timers'
scripts live in `/opt` (reproducible); the T-Pot ingest cursor lives in
OpenSearch (`tpot-events-sync-state`), not on the guest. No stale pve-tiny
config (phantom removed); plan is a clean create. The pve-tiny profile holds
`services/opensearch`, `tpot`, `llm-gpu` and `shared/external-apis`.

The known stale CVE credential is `/opt/cve-enrichment-sync/es-user.env`
(dated 2026-08-18; the rest are 2026-10-24), left by reusing a stale copy.
A fresh target plus the full provision rewrites it from OpenBao, so this
should resolve on its own. **Decision point:** with a working credential the
daily `cve-enrichment-sync` (about 21:00 NZDT) may send derived vulnerability
findings to an external LLM again, which the evacuation deliberately did not
trigger. That was its normal behaviour before the evacuation; confirm
whether to leave the timer enabled after the return or disable it until
reviewed.

**Result 2026-10-27:** operator ran `copy`, `create`, `restore`, `provision`.
CT 50012 runs on pve-tiny (`onboot=1`, `nvme-lvm`); pve copy stopped with
`onboot=0`. Core roles applied (CVE sync, T-Pot ingest, GVM scan account);
`es-user.env` and the T-Pot tunnel key were rewritten fresh on 15:37 (the
stale credential is gone). First T-Pot ingest on the new guest succeeded
(15:40). `provision` aborts at the Wazuh agent play, so the unattended-upgrades
play after it has not run; `verify` is not yet complete.

**Wazuh manager fault (not caused by the return):** the `wazuh-remoted`
daemon on CT 40015 is not running ("daemons not ready (wazuh-remoted->stopped)"),
so the manager API returns 500 on authentication and **every agent shows
Disconnected**. Agent last keepalive was 2026-10-26 03:44 UTC (about 23 h
before the return work started); the manager container itself has been up 11
days, 0 restarts, no OOM, and `ossec.log` shows no remoted error. Enrolment
(authd) still accepts requests. Fix remoted first (mind the known
restart-OOM hazard in `docs/wazuh-tuning/runbook.md`), then rerun
`scripts/pve-tiny-return.sh 50012 provision` and `verify`; the playbook is
idempotent.

**Open decision:** `cve-enrichment-sync.timer` is enabled on the new guest
and next fires 21:01 NZDT today; it may send derived findings to an external
LLM, as it did before the evacuation. Disable with
`pct exec 50012 -- systemctl disable --now cve-enrichment-sync.timer` on
pve-tiny if it should wait.

### R3 guest 3: ai-services 50013 (returned 2026-10-27, Wazuh enrolment pending)

Method A, about 2 GB of data. Carried (all verified present on the running pve
CT): `ai-services-openwebui-data` (948 MB: users, chats), `ai-services-deep-research-config`
(21 MB), `ai-services-searxng-data`, `eval-runner-hf` (958 MB, HF cache; saves a
re-download), and **`/srv/eval-runner`** (20 MB: all run results including the
restored `_historical/`; this is the path the evacuation missed). Not carried:
`ai-services-deep-research-data` (obsolete since 2026-09-22), images (about
15 GB, re-pulled from Harbor). The eval queue is in the cse-panel Redis (still
on pve until 20030 returns), not on this guest. Quiesce check: no running
`eval-*` container. Verify adds OpenWebUI `:8081`, SearXNG `:8082` and
`eval-run results` showing the historical section. The script now treats a
provision whose only failure is the Wazuh agent play as done-with-warning
(`provision.warn`), so Wazuh enrolments can be batched after the manager is
fixed.

**Findings while running 50013 (2026-10-27):**

- `copy`, `create`, `restore` completed (1.6 GB archive verified). The first
  `provision` failed in the compose play, **not** at Wazuh: a fresh build of
  `web-search-mcp` resolved unpinned `fastapi 0.162.0` / `starlette 1.10.0`
  / `uvicorn 0.54.0` / `pydantic 2.14.1` and `mcpo 0.0.20` crashed
  (`FastAPI.__init__() got an unexpected keyword argument 'ssl_certfile'`),
  so OpenWebUI (which waits on it) never started. The old pve image kept
  working because it predates the drift. Fix: pin the five packages to the
  last known-good set read from the old image's layers (fastapi 0.141.1,
  starlette 1.6.0, uvicorn 0.53.0, pydantic 2.13.5, sse-starlette 3.4.11),
  proved with a throwaway container. Committed on `work/pve-tiny-return`
  (`e291781d`); **it must also reach `stable`**, or any rebuild will break
  the same way.
- My Wazuh-tolerance logic wrongly marked that failed provision as done (it
  matched `roles/wazuh_agent/` anywhere in the log). Replaced by an explicit
  `WAZUH=skip` option (skips only the `wazuh_agent_rollout` play); nothing is
  inferred from a failure any more.
- **Play order matters:** in `deploy-ai-services-stack.yml` the Wazuh play
  (line 906) precedes the eval-runner install (line 948). While the Wazuh
  manager is down, a plain provision aborts before eval-runner is deployed,
  which is exactly how the evacuation lost it. Use `WAZUH=skip` for this
  guest until Wazuh is fixed; `verify` now fails loudly if
  `/usr/local/bin/eval-run` is missing.
- Same consequence for 50012: its provision stopped at the Wazuh play, so
  the unattended-upgrades play after it has not run; rerun with
  `WAZUH=skip` (and again later without it).
- Wazuh enrolment batch (do after the manager's `wazuh-remoted` is fixed):
  50012 secpipe, 50013 ai-services, plus any guest provisioned with
  `WAZUH=skip` (`provision.warn` marks them). 20017 enrolled successfully.

**Result 2026-10-27 (after the web-search-mcp pin and `WAZUH=skip`):** CT
50013 runs on pve-tiny (`onboot=1`); pve copy stopped with `onboot=0`.
`verify`: all containers healthy (openwebui, web-search-mcp, searxng,
deep-research, deep-research-files, portainer-agent); eval-runner workers
active and `ready` (Redis reached); OpenWebUI `:8081` and SearXNG `:8082`
return 200; the real ingress route `openwebui.lab...` returns 200 and
`deep-research.lab...` redirects to Authentik; `/srv/eval-runner/results` has
11 entries and `_historical` 29, matching the pve copy; `webui.db` on the new
guest has 1 user / 50 chats, identical to the pve source. Remaining manifest
diff vs the pve source is expected: `wazuh-agent` (pending), the obsolete
`deep-research-data` volume (deliberately not carried), an anonymous volume
id, `idna`/`normalizer` pip entry points, `systemd-pcrlock.socket` and a
`.dpkg-old` file. Still to do: backup, `known_hosts`, Wazuh enrolment batch,
soak before destroying the pve copy.

### R3 guest 4: pentest-runner 40072 (preflight written 2026-10-27, not yet run)

Method A with a selective copy (about 0.9 GB), because most of this guest's
state is not reproducible by `deploy-pentest-runner.yml`. Carried: `/root`
(80 `strix_runs`, 253 MB raw `model-traffic`, tool caches, launcher logs,
`framework_lock_client.py`) **excluding `/root/.ssh` and `/root/.ansible`**,
`/home/shannon` (fixture source, models.json), `/opt/BoxPwnr` (git clone) and
the `infra_temporal-data` volume. `/root/.ssh/authorized_keys` is **merged,
not copied**: it holds the operator key (`steve@garuda`, which Ansible
needs; the fresh guest already has it) and
`pentest-lab-worker@cse-controller` (how the controller reaches the runner);
missing lines are appended. No workload is running (only the viewer
supervisor); quiesce check refuses to stop if a `strix`/`boxpwnr` run is
active. `restore` also pings the VNet gateway from the new CT and stops if
VLAN 100 (`tvcse`) is not working on pve-tiny, before any provisioning. This
is the first guest on `cse_seg` and so the first real test of that VLAN path.
`verify` adds the viewer `/healthz`, run counts, key comments and DNS.
`WAZUH=skip` is not needed (this playbook has no Wazuh play). The 40070
controller's pentest worker is still absent on live pve; it returns with 40070.

### R2. Rehearsal (run and passed 2026-10-27)

Rehearses method B end to end on a small, harmless guest before OpenSearch.
Subject: pve CT 50012 secpipe (1.3 GiB used, running; stateless). Backup to
`pbs-usb-staging`, restore to unused VMID 950012 on pve-tiny `nvme-lvm`
with **no network** (net0 deleted before first start, so the 192.168.50.12
IP cannot collide), run the parity manifest on source and copy, diff them,
then destroy the test CT and forget the staging snapshot. Records backup
time/size and restore time/throughput for the sizing estimate.

Run it with one command from the workstation:
`scripts/pve-tiny-return-rehearsal.sh <vmid>` (`--dry-run` for read-only
checks, `--use-existing` if the backup was already taken by hand,
`--cleanup-only` to remove the test CT and staging snapshot). The script
finds the snapshot itself, so nothing is copied between sessions. Approval
names: `pve-tiny-return-r2-backup`, `-restore`, `-cleanup`. Must finish and clean
up before the pve-tiny backup job at 12:30 NZDT next day, or it would back up
the test CT.

**Result, 2026-10-27** (CT 50012, snapshot `ct/50012/2026-10-27T02:16:01Z`):

| Measure | Value |
|---|---|
| Backup (pve to `pbs-usb-staging`, snapshot mode, guest running) | 13 s (task log), 2.16 GiB logical |
| Restore on pve-tiny to `nvme-lvm` | 34 s total, 28.5 s data, 77.6 MiB/s average |
| Test CT | 950012, no network, `onboot=0`; started and ran |
| Parity manifest (enabled units, Docker volumes, `/opt` `/srv` `/usr/local/bin`, `/etc`) | 241 lines each, **PARITY-OK** |
| Cleanup | test CT purged, staging snapshot forgotten, both verified |

Sizing estimate for method B: roughly 13 s per GiB restored at this
throughput, so OpenSearch's 150 GiB data mount is about 35 minutes of
restore if it is fully used, plus the backup of the stopped CT. The backup
was fast partly because `usb-backup` already held most chunks (synced from
iscsi); expect a slower first backup for data not yet synced. Treat these as
estimates until OpenSearch's own preflight measures its size.

Method B (backup to `pbs-usb-staging`, restore on pve-tiny to `nvme-lvm`) is
confirmed working. `scripts/pve-tiny-return-rehearsal.sh` is reusable for
other guests.

Does **not** prove the full provision from `stable` or Terraform import on
pve-tiny; the first method-A guest (Technitium) proves provision, and the
first method-B guest needs an import step in its own preflight.

### R3. Per-guest return (one approval each, named `pve-tiny-return-<stack>`)

1. **Parity manifest** of the live pve guest before it is stopped (enabled
   units, `docker ps -a`, volumes, `/opt`, `/srv`, `/etc` top level, cron).
2. Drain writers, stop the pve guest, set `onboot=0`, then a fresh cold
   copy with `tar --numeric-owner --xattrs --acls`; verify checksum and
   counts.
3. Create the target fresh on pve-tiny via the reviewed Terraform plan;
   restore data; start only the target.
4. Run the **full** `scripts/provision.sh --stack <name>` from a branch cut
   from current `stable`.
5. Compare the target against the manifest; then run the consumer-path
   matrix.
6. Refresh `known_hosts`; take a fresh backup; fix the backup exclusions.
7. Keep the pve copy stopped through the soak, then destroy it under its
   own approval, not left as a stale duplicate.

Order, lowest risk first:

| Order | Guest | Note |
|---|---|---|
| 1 | 20017 Technitium | Restores node-level DNS redundancy first |
| 2 | 50012 secpipe | Stateless, re-provisioned; fixes its credential |
| 3 | 50013 ai-services | Verify OpenWebUI **and** eval-runner |
| 4 | 40072 pentest-runner | Full root and Docker copy |
| 5 | 100071, 40070, 20030 | CSE; drain queues first; panel last |
| 6 | 40014 opensearch | Largest, most consumers, so last |

### Consumer-path matrix (run after every guest)

| Flow | Check |
|---|---|
| Eval worker → Redis → panel | `GET /framework` has a fresh `checked` and a model |
| Controller → Redis, Harbor, Framework `:8080` | Authenticated request from inside the worker container |
| Controller pentest containers → pentest-runner | Bounded viewer/worker health check |
| node_exporter on each guest | Scrape `up` is 1 and the cert is valid |
| Secpipe → OpenSearch | One bounded index read |
| Clients → both resolvers | `.15` and `.17` answer |
| Every guest → PBS | New snapshot exists |

## Branch, Terraform state and scaffolding (added 2026-10-27)

Do the return from a **new** `work/pve-tiny-return` branch cut from
current `stable`, never from `work/pve-tiny-evacuation`.

Evacuation-only changes (not on `stable`; verified by grep 2026-10-27).
They stay on the evacuation branch and are **not** carried back, except
where noted:

| Item | Return handling |
|---|---|
| `network/pve.yaml` `cse_seg` attachment (`tvcse`) | Stays live on pve (decision above). Merge to `stable` only if the operator wants it tracked; otherwise the live SDN object is unmanaged by Terraform. Decide before R3. |
| `storage/pve.yaml` `platform-nvme` profile | Needed on pve **only until the pve copies are destroyed**. Not needed for the return. |
| `variables.tf` `stack_start`/`stack_onboot` | Same: pve copies only. |
| `environments/pve/{cse-*,pentest-runner,technitium-tiny-stack}` | Needed to plan/destroy the pve copies cleanly. Use the evacuation worktree for the retirement step (R3.7), then delete the entries. |
| `technitium-tiny-stack` `storage_profile: platform-monitoring-zfs` | **Do not carry back.** `stable` has `platform-default`; confirm what profile the pve-tiny stack should use against `storage/pve-tiny.yaml` before plan. |

State handling:

- Terragrunt state is **local and untracked** in each environment
  directory. pve-tiny state lives in the original checkout; pve state for
  the evacuated guests lives in the evacuation worktree. A branch cut from
  `stable` has neither.
- Before R1, copy both sets of state into the return worktree as ignored,
  access-restricted files and record checksums (same rule as the
  evacuation plan). Never plan from an empty state directory.
- After the NVMe is replaced, pve-tiny state for the nvme-lvm guests refers
  to volumes that no longer exist. Per guest: `terraform state rm` the
  stale resources only after the matching CT config is removed from
  pve-tiny, then let the reviewed plan **create** the target.
- 40072 `pentest-runner` has pve-tiny state that was historically empty and
  now has pve state. Its return target is created fresh by Terraform, with
  the root/Docker content restored over it; the plan must show a create,
  not a replace of anything live.
- Retiring a pve copy (R3.7): `terragrunt destroy` from the evacuation
  worktree environment, or `pct destroy` plus `terraform state rm`. Either
  way a reviewed plan/preflight first and its own approval.

## VMID and IP collisions on pve-tiny (added 2026-10-27)

Four guests (100071, 40070, 20030, 20017) have stopped sources on the boot
SSD that keep their VMIDs, and the stale CT configs point at old data.
For each, before creating the target:

1. Confirm the stopped source is `onboot=0` and still stopped.
2. Before the destroy: take a PBS backup of that stale source only if the
   operator wants it kept as evidence. It is stale by design, so the default
   is no.
3. Destroy the stale source CT under the guest's own approval.
4. Only then create the target with the same VMID and IP.

Never have the pve copy and the pve-tiny target running at once (same IP).
For the NVMe guests (40014, 50012, 50013, 40072) the stale CT configs on
pve-tiny reference lost volumes; remove them in R1.

## Edge, firewall, DNS and monitoring (added 2026-10-27)

These did not move with the guests, but depend on where they run.
Check each before R3 and again after each guest.

| Area | Check |
|---|---|
| MikroTik | Cross-zone rules for VLAN 100/`cse_seg` (see `mikrotik-firewall-cse-panel-cross-zone.yml`) are keyed on IPs, which do not change. Confirm they still permit the intended paths after the return and that the router rule reconciler passes. Do not edit router rules for the move itself. |
| VLAN 100 on pve-tiny | Confirm the `cse_seg` VNet and switch trunk are intact after the drive swap (R1) before any CSE guest. |
| Traefik/Authentik edge | `cse-panel-stack/edge.yaml` backends use IPs (`${LAB_IP_CSE_PANEL}`), so no edge change is expected; verify login and the four pentest-viewer routes through the real ingress. |
| Technitium | After restore of 20017, confirm cluster/zone sync with `.15`, UDP and TCP on `.17`, and that DHCP still hands out both resolvers. Do it before moving anything else (it is order 1). |
| Monitoring scrape | Confirm Prometheus/VictoriaMetrics targets for the eight guests resolve to the same IPs and go `up`. Recreated guests need fresh node_exporter certs (`/etc/node_exporter` on 40070 is a known gap). |
| Alerting | pve-tiny host alerts (`node_exporter_hw` for `pve-tiny`, file-handle alerts) will page while the node is down. Decide whether to silence them during the swap, and clear any silence afterwards. Alerting Phase 7 treats secpipe as pve-tiny: confirm the cadence fix still matches. |
| Wazuh / backups | Re-enrol agents on 50012 and 20017 and verify the pve-tiny PBS job covers all eight, with correct exclusions. |

## Sizing and windows (added 2026-10-27)

- The cold copy is the long step. Record, per guest, the used bytes before
  starting (`du`/`pct df`/`zfs list` on pve) and the measured throughput of
  a 1 GiB pve to pve-tiny test transfer; estimate the window from those.
- OpenSearch (150G data mount) is the dominant cost. Do it in a quiet
  period with the Secpipe timers and Grafana/Graylog consumers paused.
- Per guest, name the rollback trigger and time before starting. Rollback
  after the cutover means restarting the pve copy, so it must remain
  stopped, not destroyed, until the soak ends.
- Keep the pve guest `onboot=0` once stopped, so a pve reboot cannot start
  a duplicate IP.

## Gate checklist (all must be true before the first R3 approval)

- [ ] Open items 1-5 above closed or explicitly accepted as lost.
- [ ] Return branch cut from current `stable`; both state sets copied with checksums.
- [ ] New NVMe healthy, `nvme-lvm` recreated (R1), stale CT configs/state removed.
- [ ] pve-tiny profile loads; all `services/*` the eight stacks need exist.
- [ ] Inventory generated; `scripts/provision.sh --stack` works for all eight.
- [ ] Rehearsal (R2) restore and provision passed.
- [ ] Sizing estimates and windows recorded; alert silences decided.
- [ ] Ancillary faults (Step CA timeout, Wazuh enrolment, CVE credential) fixed or logged.

## What this plan does not yet fix

- **Per-guest literal commands.** The copy, restore and verify commands
  depend on pool IDs, mount layouts and sizes that are only known after R1.
  Write them as a `runbook` (one preflight per guest) once the new drive is
  in, following `docs/agent-design/step-packet-schema.md`, then ask for
  approval one task at a time.
- Whether the open items in the audit were closed. Verify with a read-only
  look at pve-tiny before the erase decision; do not assume.

## Completion

All eight run on pve-tiny with their intended IPs, pass the matrix, have
fresh backups, show no unreviewed Terraform drift, and the pve copies are
retired after soak. `tvcse` remains on pve.
