# 05 — Decommission the old AI-stack CTs on pve

**When:** not before **2026-10-04** (7-day soak after the 2026-09-27
cutovers) · **Effort:** 45 min · **Value:** Medium (reclaims pve disk; stops
backing up four dead copies every night)
**Depends on:** plan 03 Part B done, with a verified post-import backup per CT
**Approval names:** `ai-stacks-pve-tiny-decommission-<stack>` (one per stack,
the names `docs/ai-stacks-pve-tiny/plan.md` already defines)

This carries out Phase 4 of `docs/ai-stacks-pve-tiny/plan.md`. That plan is
the authority. This page puts its gate in order with exact commands and
stack names.

| Stack | VMID | Old copy on `pve` (state 2026-09-28) | New home |
|---|---|---|---|
| `mcp-utility-stack` | 50011 | stopped | `pve-tiny`, `192.168.50.10` |
| `secpipe-stack` | 50012 | stopped | `pve-tiny`, `192.168.50.12` |
| `ai-services-stack` | 50013 | stopped | `pve-tiny`, `192.168.50.11` |
| `opensearch-stack` | 40014 | stopped | `pve-tiny`, `192.168.40.14` |

## Gate, per stack: all four must hold, or skip that stack

1. **Soak:** today is 2026-10-04 or later.
2. **Backup exists and is post-import:** plan 03's B6 hand-back lists a
   volid for this VMID on `pbs-iscsi` namespace `pve-tiny`, task status `OK`.
3. **Backup is usable:** the B6 `pvesm extractconfig` output for that volid
   shows the right hostname and every `mp*` line, none with `backup=0`.
4. **App checks pass right now:** re-run the stack's checks from
   `docs/ai-stacks-pve-tiny/plan.md` Phase 3 immediately before destroying:
   - mcp-utility-stack → "### mcp-utility-stack checks"
   - secpipe-stack → "### secpipe-stack checks"
   - opensearch-stack → "### opensearch-stack: fingerprint, export, import, checks"
     (checks part only)
   - ai-services-stack → "### ai-services-stack: fingerprint, export, import, checks"
     (checks part only)

Quick liveness check before those (read-only):

```bash
for hp in 192.168.50.10:8000 192.168.50.10:8001 192.168.50.11:8090; do curl -s -m5 -o /dev/null -w "$hp %{http_code}\n" http://$hp/; done
curl -s -m8 -o /dev/null -w "deep-research %{http_code}\n" https://deep-research.lab.gibbsgreatly.xyz/
```

(`404`/`200`/`302` = answering. `000` = stop.)

## Operator: destroy (production, one approval per stack)

Preflight per stack: target `pve`, mutating, destroys exactly VMID `<ID>`
(stopped) and its volumes; out of scope: the pve-tiny copy, the `tvai` zone,
PBS backups of the old copy.

```bash
S=mcp-utility-stack; ID=50011   # then secpipe-stack/50012, ai-services-stack/50013, opensearch-stack/40014
ssh root@pve.gibbsgreatly.xyz "pct config $ID | grep -E '^hostname:'; pct status $ID"
# expect the matching hostname and "status: stopped" — anything else: stop
TASK_APPROVAL=ai-stacks-pve-tiny-decommission-$S ssh root@pve.gibbsgreatly.xyz "pct status $ID | grep -q stopped && pct destroy $ID --purge"
rm -rf terraform/lxc/environments/pve/$S   # untracked local state only; its terragrunt.hcl was git-rm'd in ai-tiny-05
```

Keep `pve`'s `tvai` zone. Removing an existing zone is a full-teardown-tier
change and isn't needed.

Verify after each:

```bash
ssh root@pve.gibbsgreatly.xyz "pct status $ID" 2>&1 | grep -q 'does not exist' && echo "$ID gone"
ssh root@pve-tiny.gibbsgreatly.xyz "pct status $ID"   # expect status: running
```

## What stays behind, deliberately

- The old copies' PBS backup groups (root namespace, `ct/50011` etc.). The
  pve job no longer backs these VMIDs up, so its retention never prunes these
  groups again. They stay as an archive until the operator removes them in
  the PBS GUI.
- The workstation archive and `.sha256` from the migration. Per the
  ai-stacks plan, retire them only after a restore rehearsal (to a
  non-conflicting VMID, never started on the production IP) or after a
  second verified pve-tiny backup generation exists. The second generation
  exists automatically after plan 03's job has run twice.

## Step (repo)

### catchup-05-record-decommission

```yaml
id: catchup-05-record-decommission
title: Record the Phase 4 decommission as done in the ai-stacks workspace
depends_on: [catchup-03-record-backup-policy]

change: |
  In docs/ai-stacks-pve-tiny/README.md, replace the table row
  "| Phase 4 decommission (after ≥7-day soak) | not started |"
  with this LITERAL row:

  | Phase 4 decommission (after ≥7-day soak) | done — old pve CTs 50011/50012/50013/40014 destroyed after gate; see docs/catch-up/README.md hand-back for plan 05 |

  Change nothing else.

scope:
  allowed_paths:
    - docs/ai-stacks-pve-tiny/README.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any ssh, pct or rm command"

gates:
  - id: row-updated
    cmd: "grep -c 'Phase 4 decommission (after ≥7-day soak) | done' docs/ai-stacks-pve-tiny/README.md"
    expect: "prints 1"
    critical: true
```

Run only after all four stacks are destroyed. If some were skipped at the
gate, the operator writes the row by hand, naming which ones remain.

## Done when

- The four VMIDs don't exist on `pve` and are running on `pve-tiny`.
- `terraform/lxc/environments/pve/{mcp-utility-stack,secpipe-stack,ai-services-stack,opensearch-stack}`
  are gone locally.
- `catchup-05-record-decommission` is done.
