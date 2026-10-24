# Return to pve-tiny after the NVMe replacement

Status: **plan only; nothing executed.** Written 2026-10-24 from the
evacuation plan/runbook, the issues met during it, and a parity audit of
the stopped pve-tiny sources against the live pve targets.

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

### R2. Rehearsal

Test restore of one PBS snapshot to an unused VMID on isolated
networking, then run the full provision path against it.

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

## Completion

All eight run on pve-tiny with their intended IPs, pass the matrix, have
fresh backups, show no unreviewed Terraform drift, and the pve copies are
retired after soak. `tvcse` remains on pve.
