# 03 — PBS retention + pve-tiny backups

**When:** today (PBS is close to full) · **Effort:** 1.5–2 h of hands-on
time, plus garbage-collection runtime (can be hours on ~1 TB)
**Value:** High · **Approval names:** `catchup-03a-pbs-retention`,
`catchup-03b-pve-tiny-backups`

## State on 2026-09-28 (read-only API)

- `pve` storage `pbs-iscsi`: type `pbs`, server `192.168.1.12` (the Proxmox
  Backup Server, CT 105 on `pve`), datastore `iscsi-backup`, user `root@pam`,
  fingerprint
  `2b:44:ab:df:d2:36:d5:be:6d:4d:e3:9b:4f:a8:cb:42:f8:2d:ab:48:61:a4:8e:a7:08:0d:d8:da:ba:54:00:fd`.
- Capacity: total 1,081 GB, used 989.5 GB, **available 36.5 GB (~97% used)**.
- `pve` backup job `backup-8b90fc3e-c3a5`: all guests except `105,910`,
  daily `11:00`, mode `snapshot`, storage `pbs-iscsi`,
  **`prune-backups: keep-all=1`** (nothing is ever pruned).
- `pve-tiny` has no backup job (`docs/ai-stacks-pve-tiny/README.md` Phase 0).
  Since 2026-09-27 it runs `mcp-utility-stack` 50011, `secpipe-stack` 50012,
  `ai-services-stack` 50013 and `opensearch-stack` 40014, plus the cse stacks.
- **VMID collision:** the four relocated CTs kept their VMIDs, and the old
  stopped copies on `pve` are still backed up daily under the same IDs. Two
  standalone nodes writing `ct/50011` etc. into the same PBS namespace would
  mix both nodes' snapshots in one backup group. That's why pve-tiny gets its
  own namespace.

Operator decisions: retention `keep-daily=7, keep-weekly=4, keep-monthly=6`;
pve-tiny backs up to this same PBS, namespace `pve-tiny`.

## Part A — retention on pve and reclaim space (approval `catchup-03a-pbs-retention`)

Preflight to report: target `pve` backup job and PBS datastore
`iscsi-backup`; mutating; changes job retention, deletes backup snapshots
beyond the policy, runs GC; out of scope: the job's schedule, guest list and
mode, and anything on pve-tiny.

### A1. Read-only baseline

```bash
ssh root@pve.gibbsgreatly.xyz 'pvesh get /cluster/backup/backup-8b90fc3e-c3a5 --output-format json-pretty; pvesm status --storage pbs-iscsi'
ssh root@pve.gibbsgreatly.xyz 'pct exec 105 -- proxmox-backup-manager datastore show iscsi-backup; pct exec 105 -- proxmox-backup-manager prune-job list; pct exec 105 -- proxmox-backup-manager garbage-collection status iscsi-backup'
```

Record in the hand-back: avail bytes, whether the datastore has a
`gc-schedule`, and any existing PBS-side prune jobs. **If a PBS prune job
already exists for `iscsi-backup`, stop.** Two retention policies would
conflict; decide which one owns retention before continuing.

### A2. Set retention on the pve job

```bash
ssh root@pve.gibbsgreatly.xyz "pvesh set /cluster/backup/backup-8b90fc3e-c3a5 --prune-backups 'keep-daily=7,keep-weekly=4,keep-monthly=6'"
ssh root@pve.gibbsgreatly.xyz 'pvesh get /cluster/backup/backup-8b90fc3e-c3a5 --output-format json' | python3 -c "import json,sys;print(json.load(sys.stdin)['prune-backups'])"
```

Expect `{'keep-daily': 7, 'keep-weekly': 4, 'keep-monthly': 6}` (no
`keep-all`). From now on each nightly run prunes after backing up.

### A3. Prune existing backups: dry run first

```bash
mkdir -p docs/catch-up/artifacts
ssh root@pve.gibbsgreatly.xyz 'pvesm prune-backups pbs-iscsi --dry-run 1 --keep-daily 7 --keep-weekly 4 --keep-monthly 6' | tee docs/catch-up/artifacts/03-prune-dry-run.txt
grep -c ' remove' docs/catch-up/artifacts/03-prune-dry-run.txt; grep -c ' keep' docs/catch-up/artifacts/03-prune-dry-run.txt
```

Sanity check before the real run: every VMID that still exists keeps at least
one snapshot (its newest). Any VMID that would go to zero is a bug. Stop.

```bash
awk '$NF=="keep"{print $2}' docs/catch-up/artifacts/03-prune-dry-run.txt | sort -u > docs/catch-up/artifacts/03-kept-vmids.txt
ssh root@pve.gibbsgreatly.xyz 'pct list | awk "NR>1{print \$1}"; qm list | awk "NR>1{print \$1}"' | sort -u | comm -23 - docs/catch-up/artifacts/03-kept-vmids.txt
```

That prints existing guests with no kept backup. It should print only
`105`/`910` (excluded from the job). Anything else: stop and look. (The
dry-run's column layout is assumed here; if `awk` finds nothing, read the file
by eye rather than trusting an empty result.)

### A4. Prune for real

```bash
TASK_APPROVAL=catchup-03a-pbs-retention ssh root@pve.gibbsgreatly.xyz 'pvesm prune-backups pbs-iscsi --keep-daily 7 --keep-weekly 4 --keep-monthly 6'
```

(`TASK_APPROVAL` documents the approval here; plain `ssh` isn't wrapped.)

### A5. Garbage-collect to actually free space, and schedule GC

Pruning removes snapshot indexes; chunks are only freed by GC.

```bash
ssh root@pve.gibbsgreatly.xyz 'pct exec 105 -- proxmox-backup-manager garbage-collection start iscsi-backup'
# poll until finished (can take hours):
ssh root@pve.gibbsgreatly.xyz 'pct exec 105 -- proxmox-backup-manager garbage-collection status iscsi-backup'
```

If A1 showed no `gc-schedule`, set one so this doesn't recur:

```bash
ssh root@pve.gibbsgreatly.xyz 'pct exec 105 -- proxmox-backup-manager datastore update iscsi-backup --gc-schedule daily'
```

### A6. Verify

```bash
ssh root@pve.gibbsgreatly.xyz 'pvesm status --storage pbs-iscsi'
```

**Gate before Part B:** available space ≥ 216 GB (20% of total). If it's
lower, don't add pve-tiny yet. List backup groups of guests that no longer
exist (old decommissioned VMIDs) and decide with the operator whether to
delete those groups in the PBS GUI (Datastore → Content → group → Remove).
That's a separate, explicit decision per group.

## Part B — pve-tiny backups (approval `catchup-03b-pve-tiny-backups`)

Preflight to report: target `pve-tiny` storage config and backup jobs, plus
one new PBS namespace; mutating (adds storage, adds job, runs one backup);
out of scope: the `pve` job, any restore.

### B1. Create the PBS namespace `pve-tiny`

PBS GUI (`https://192.168.1.12:8007`) → Datastore `iscsi-backup` → Content →
**Add Namespace** → name `pve-tiny`, parent root.

### B2. Add the PBS storage on pve-tiny

pve-tiny GUI → Datacenter → Storage → Add → **Proxmox Backup Server**:

| Field | Value |
|---|---|
| ID | `pbs-iscsi` |
| Server | `192.168.1.12` |
| Username | `root@pam` |
| Password | (PBS root password, typed in the GUI, never stored in git) |
| Datastore | `iscsi-backup` |
| Namespace | `pve-tiny` |
| Fingerprint | `2b:44:ab:df:d2:36:d5:be:6d:4d:e3:9b:4f:a8:cb:42:f8:2d:ab:48:61:a4:8e:a7:08:0d:d8:da:ba:54:00:fd` |
| Content | `backup` |

Verify:

```bash
ssh root@pve-tiny.gibbsgreatly.xyz 'pvesm status --storage pbs-iscsi && grep -A8 "^pbs: pbs-iscsi" /etc/pve/storage.cfg | grep -E "namespace|datastore|server"'
```

Expect `active 1`, `namespace pve-tiny`, `datastore iscsi-backup`, `server 192.168.1.12`.

### B3. Create the pve-tiny backup job

Scheduled at 12:30 so it never overlaps pve's 11:00 run:

```bash
ssh root@pve-tiny.gibbsgreatly.xyz "pvesh create /cluster/backup --schedule 12:30 --storage pbs-iscsi --all 1 --mode snapshot --prune-backups 'keep-daily=7,keep-weekly=4,keep-monthly=6' --notes-template '{{guestname}}' --notification-mode notification-system --enabled 1"
ssh root@pve-tiny.gibbsgreatly.xyz 'pvesh get /cluster/backup --output-format json-pretty'
```

### B4. Check mount points are included (read-only)

```bash
ssh root@pve-tiny.gibbsgreatly.xyz 'for id in 40014 50011 50012 50013; do echo "== $id"; pct config $id | grep -E "^(rootfs|mp[0-9]+):"; done'
```

Expect no line containing `backup=0`. If one does, stop: its data wouldn't be
in the backup (Phase 4 requirement 3 in `docs/ai-stacks-pve-tiny/plan.md`).

### B5. Take the first post-import backup now

```bash
ssh root@pve-tiny.gibbsgreatly.xyz "vzdump 40014 50011 50012 50013 --storage pbs-iscsi --mode snapshot --notes-template '{{guestname}}'"
```

If the storage doesn't support snapshots, vzdump falls back to suspend mode
and logs it. That's expected, and the CTs pause briefly.

### B6. Verify the evidence Phase 4 requires

```bash
ssh root@pve-tiny.gibbsgreatly.xyz 'pvesm list pbs-iscsi --content backup' | tee docs/catch-up/artifacts/03-pve-tiny-backups.txt
# for each of 40014 50011 50012 50013, take its newest volid from the list and:
ssh root@pve-tiny.gibbsgreatly.xyz 'pvesm extractconfig <volid>' | grep -E '^(hostname|rootfs|mp[0-9]+):'
```

Record per CT in the hand-back: the vzdump task status (`OK`), the volid, and
that the extracted config shows the expected hostname and mount points. These
are requirements 2 and 3 of the ai-stacks Phase 4 decommission gate, which
plan 05 relies on.

## Step (repo, after Parts A and B)

### catchup-03-record-backup-policy

```yaml
id: catchup-03-record-backup-policy
title: Record the backup policy and pve-tiny coverage in the ai-stacks workspace
depends_on: []

change: |
  In docs/ai-stacks-pve-tiny/README.md, directly after the line that begins
  "| Phase 4 decommission (after ≥7-day soak) |", insert this LITERAL row:

  | pve-tiny backup job + first post-import backup | done — see docs/catch-up/README.md hand-back for plan 03 (PBS `iscsi-backup`, namespace `pve-tiny`, daily 12:30, keep-daily=7/weekly=4/monthly=6) |

  Change nothing else.

scope:
  allowed_paths:
    - docs/ai-stacks-pve-tiny/README.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running any ssh, pvesh, pvesm or vzdump command"

gates:
  - id: row-present
    cmd: "grep -c 'pve-tiny backup job + first post-import backup' docs/ai-stacks-pve-tiny/README.md"
    expect: "prints 1"
    critical: true
```

Only run this step after the operator hand-back for B6 exists.

## Rollback

- A2: `pvesh set /cluster/backup/backup-8b90fc3e-c3a5 --prune-backups keep-all=1`
  (pruned snapshots can't be restored; that is what the A3 dry run is for).
- B2/B3: remove the job (`pvesh delete /cluster/backup/<id>`) and the storage
  (`pvesm remove pbs-iscsi`) on pve-tiny. Backups already taken stay on PBS.

## Done when

- `pve` job shows the new retention; PBS has ≥ 20% free; GC is scheduled.
- `pve-tiny` has `pbs-iscsi` (namespace `pve-tiny`) and a daily 12:30 job.
- One verified post-import backup exists for each of 40014/50011/50012/50013.
- `catchup-03-record-backup-policy` is done.
