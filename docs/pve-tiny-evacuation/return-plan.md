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
