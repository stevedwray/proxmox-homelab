# gvm-coverage-cleanup

Fixes the GVM/Greenbone credentialed-scan program so it actually scans
with credentials, covers every host the operator wants covered, and fails
loudly when it stops working. Plan: [plan.md](plan.md).

## Status

**2026-10-12 14:25: Phase 2, VLAN-grouped credentials, is LIVE.** 12 VLAN tasks
cover all 39 hosts, plus MikroTik and OCI. R1–R4.1 are done; the live
edge_seg scan (R4.2) is in progress.

- **Phase 1 (per-host keys) is live and verified.** OP-1…OP-4 and OP-5.1 are
  done. OP-5.2 passed: `fleet/apt-cacher-stack` logged in
  (`SSH Login Successful`, no `SSH Login Failed`) and returned 8 package-level
  detections. That's the first credentialed scan in this setup that has
  ever authenticated.
- **Phase 2 (operator decision 2026-10-12): one shared `gvm-scan` key per
  VLAN/zone**, because 39 keys and 41 tasks had gotten out of hand. That
  makes 12 zones, so 12 credentials, 12 multi-host targets and 12 tasks (plus
  MikroTik and OCI), each weekly and capped at 4 concurrent hosts. Runbook:
  plan.md "Phase 2 runbook (VLAN-grouped credentials)". The plan's
  `gvmcov-01`…`16` step blocks describe Phase 1. Phase 2 was implemented
  directly by Claude in 1a5b263c, stub-tested from the live state; it isn't
  written as step blocks.

Status pointers to this workspace were added on 2026-10-11 to
docs/greenbone-stack/README.md, docs/greenbone-stack/network-scan-rollout-plan.md,
docs/lxc-scan-and-monitoring-rollout/README.md and plan.md,
docs/opensearch-stack/README.md, and greenbone-stack's STACK_CONTRACT.md.
Update them when the plan is executed (plan.md OP-5 step 5).

## What was found (2026-10-11, live evidence)

- **No scheduled fleet credentialed scan has ever authenticated.** All 21
  fleet hosts that GVM can reach, about 170 scheduled runs between
  2026-09-30 and 2026-10-10: every run reported
  `SSH Login Failed For Authenticated Checks`, with zero Local Security
  Check results and zero `SSH Login Successful`. Source: gvm-bridge
  `/findings/all` (25,669 results).
- **Root cause: GVM's "elevate privileges" is su-based, not sudo.** Wazuh's
  copy of the targets' sshd/PAM logs shows the `gvm-scan` key login
  *succeeding* every time, followed by
  `su: pam_unix(su-l:session): session opened for user gvm-scan by gvm-scan`.
  GVM ran `su -l <elevate-credential login>`, and that login was
  `gvm-scan` itself. Across 14 days there wasn't a single `sudo` call by
  `gvm-scan`. The 2026-09-29 rollout's "verified" note was wrong. A
  Greenbone forum thread also describes the elevate credential as su-based
  ([forum](https://forum.greenbone.net/t/does-community-edition-support-ssh-elevate-method/22083)).
- **4 fleet hosts were never reachable.** The MikroTik greenbone reach rules
  covered only build/mgmt/edge/infra/ai/game and the flat LAN, so
  media-stack-lab, torrent-stack-lab, newt-connector and nextcloud-stack
  (VLANs 80/110/120) have no GVM results at all.
- **The legacy root-key target was stale.** "managed Debian services" used
  pve-test-vm's "+100" IPs (`.20.110` etc., all dead) and the destroyed
  dns-stack. The pve/workstation/Pi/MikroTik targets were unscheduled.
- **Credentials and targets were create-only.** Rotating a key in OpenBao,
  or changing a host's IP, never reached GVM.
- **Uncredentialed program gaps:** no CIDR scans at all for
  pentest_seg/media_seg/cse_seg/connector_seg/apps_seg; the NAS and the
  retired pve-test-vm were in the lan full-vuln exclusions.

## Operator decisions (2026-10-11)

| Question | Decision |
| --- | --- |
| Privilege model | Unprivileged `gvm-scan`: SSH key only, no elevate credential, sudo grant removed |
| cse_seg hosts | Scan them (cse-controller, cse-code-eval: credentialed and CIDR) |
| pentest_seg fixtures | Excluded (harness-target-pve, pentagi-upstream-control, cse-kali) |
| Workstation + Raspberry Pis | Both move onto per-host `gvm-scan` with daily schedules |
| NAS (192.168.1.3, Asustor ADM) | Uncredentialed weekly full-vuln (removed from the lan exclusions) |
| Missing hosts (#5) | All get credentialed scans: pve, pve-tiny, framework, management-stack, media-stack, proxmox-backup-server, omada-controller, cse-panel-stack, technitium-tiny-stack |
| Alerting (#2) | Required: added a coverage check to the daily findings ingest (gvmcov-14) |
| Cadence (2026-10-12) | Credentialed scans weekly, not daily (the scanner couldn't finish the daily load). Phase 2: one weekly slot per VLAN, max 4 hosts scanned at once (`max_hosts`) |
| Grouping (2026-10-12) | **By VLAN: one shared `gvm-scan` key per zone** (12 zones, including a single `lan` key for pve, pve-tiny, framework, the workstation, the Pis and 4 LXCs). MikroTik keeps its own target. Replaces per-host keys |

## Follow-ups (out of scope for this plan; not started)

1. **gvm-bridge was unauthenticated and reachable from the LAN.** Fixed
   2026-10-12 by binding it to `127.0.0.1:8010` (deploy-greenbone-stack.yml).
   Its only client is the findings ingest on the same host.
2. **Push alerting (Discord) moves to its own plan and session** (operator
   2026-10-12). It should reuse catch-up plan 07's webhook
   (`services/grafana` → `DISCORD_ALERT_WEBHOOK_URL`). Until then,
   coverage failures show as the failed `gvm-findings-ingest` unit, the
   `es-findings-sync-state/greenbone-coverage` document, and `COVERAGE ...`
   journal lines.
3. **Scan cadence.** Moved to weekly (gvmcov-15). Revisit slot sizes once
   the coverage documents show real run durations; if lan/mgmt slots
   still don't finish, split them further or grow greenbone-stack.
4. **Stopped duplicate LXCs on pve.** VMIDs 40014/50011/50012/50013
   (opensearch, mcp-utility, secpipe, ai-services) are leftovers from the
   move to pve-tiny, where they now run.
5. **OpenBao `services/greenbone` still holds `GREENBONE_STEVE_SSH_PRIVATE_KEY`**
   (a copy of the operator's root key) and
   `GREENBONE_OPENVAS_WORKSTATION_SSH_PRIVATE_KEY`. Nothing reads them after
   gvmcov-05/09. Removing them is an operator OIDC write.
6. ~~Old per-host OpenBao entries / root-key copy~~: **done 2026-10-12**
   (operator). The 39 `scan-hosts/*` entries were deleted; `services/greenbone`
   is down to 4 fields, and version 1 (with the root key) is destroyed.
7. The old `openvas` account on the workstation (garuda) is unused after
   this plan.

## Hand-backs

(Executor: append one entry per completed step here.)

- **2026-10-12, gvmcov-01…14:** applied by Claude exactly as written in
  plan.md, in one commit (d5a0bfd3). All gates printed their expected
  values: inventory 39 hosts, manifest 39 entries / 0 sudo fields, 30
  playbooks syntax-check clean, zones 12, firewall destinations 11.
- **2026-10-12, gvmcov-15:** added after the operator chose weekly cadence;
  applied from plan.md (34bc19cb), byte-identical to the stub-tested copy.
  Both gates passed.
- **2026-10-12, OP-1:** 14 new OpenBao entries written (operator);
  inventory resolves 39/39.
- **2026-10-12, OP-3:** gvm-scan rolled out. All 35 root-SSH hosts
  `failed=0 unreachable=0`, including the 4 never-before-managed LXCs.
  Framework, the Pis and the workstation were run with `-K`.
  `mcp-utility-stack` reported `changed=0` (expected 2), to be checked.
- **2026-10-12 13:28, OP-4 attempt 1: FAILED partway.** Applied: main play
  (gvm-bridge rebuilt, `/tasks/credentialed` live), LAN scan program, the
  weekly CIDR schedules, and fleet key generation (39/39). The credential
  program then aborted with `400 Target is in use`: it had deleted the
  legacy `managed Debian services` task, but another task still referenced
  that target. Nothing after that point ran (no fleet rebuild, no weekly
  credentialed schedules, no findings-ingest update), so the live fleet is
  still the old daily setup. Fixed by gvmcov-16; re-run with the
  credential-program and findings-ingest tags.
- **2026-10-12 13:32, OP-4 attempt 2 (tags `credential-program`, then
  `findings-ingest`): OK**, both `failed=0`. Verified via gvm-bridge
  `/tasks/credentialed`: 41 credentialed tasks: 39 fleet hosts (rebuilt,
  status New), MikroTik, and OCI (unscheduled by design). The 40 scheduled
  tasks sit in 17 `Weekly credentialed scan:` slots, max 4 per slot,
  exactly as the stub test predicted. Legacy pve/workstation/Pi/"managed
  Debian" tasks are gone, and the credential program exited 0, so all legacy
  deletions succeeded. The findings-ingest role deployed the new
  gvm_findings_sync.py; the timer stays enabled.
- **2026-10-12, OP-5.1 idempotency: PASS.** Re-run of `scan-program` +
  `credential-program`: both GMP tasks reported `ok` (nothing created or
  deleted); the only changes were temp-file copies.
- **2026-10-12, OP-5.2 live credentialed scan: PASS.**
  `fleet/apt-cacher-stack` (scan start 2026-10-12T00:44:48Z): 53 results,
  `SSH Login Successful` present, `SSH Login Failed` absent, 8 LSC detections
  (`Determine OS and list of installed packages via SSH login`, dmidecode,
  sudo, bash, ...). Wazuh showed only `gvm-scan` publickey logins with no `su`.
  `last_report_scan_start` is filled in after a run, so the coverage check's
  field path is correct.
- **2026-10-12, Phase 2 code (1a5b263c): VLAN-grouped credentials.**
  Stub-tested starting from the live per-host state: run 1 converges (one
  running per-host task held back, rc 1), run 2 finishes cleanup (rc 0), and
  run 3 is a no-op. Result: 12 zone tasks (`max_hosts=4`), MikroTik, OCI, 13
  schedules, no tags. The per-host coverage check correctly separates ok,
  auth_failed, no_auth_evidence, no_results, never_run and stale. All 32
  affected playbooks syntax-check. Phase 2 runbook pending.
- **2026-10-12 14:25, Phase 2 runbook R1–R4.1: OK.** R1: 12 zone keys
  written. R2: every host switched to its zone key (operator reported clean).
  R3: full greenbone-stack play, `failed=0`; the credential program
  rebuilt everything. gvm-bridge shows 14 credentialed tasks: 12
  `Credentialed scan: <zone>` on `Weekly VLAN scan: <zone>` (lan 10, mgmt 9,
  infra 5, ai 3, cse/game/media/edge 2, apps/build/connector/pentest 1 =
  39 hosts), MikroTik on its own weekly slot, OCI unscheduled. R4.1
  idempotency: both GMP tasks `ok`. R4.2 edge_seg live scan started.
8. **mcp-utility-stack is running pre-Maigret OSINT code (found 2026-10-12).**
   At 07:15 NZDT something on the workstation (not a Claude session, not
   in shell history) redeployed it from the shared checkout while it was on
   this branch. That applied the new gvm-scan role early (hence OP-3's
   `changed=0`) and dropped `find_username_deep`, which lives only on
   `feat/osint-maigret-username-search`. Dated by Wazuh FIM
   (`/etc/sudoers.d/gvm-scan` deleted 18:20 UTC) and root SSH logins. The fix
   needs the OSINT branch rebased onto this one. The OSINT branch can't be
   deployed as-is: its role and secret paths predate this work.
