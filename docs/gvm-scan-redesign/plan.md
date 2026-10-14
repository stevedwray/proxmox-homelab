# gvm-scan-redesign plan

Order matters: Phase 1 removes the duplicated work, Phase 2 decides the lean
config from data, Phase 3 turns the timings into a guaranteed night window.
Each phase is applied with targeted playbook tags (never a full greenbone-stack
redeploy while a scan runs) and deployed from a worktree of the branch.

## Phase 0 - baseline (done 2026-10-14)

Supervised run of `LAN scan: lan full-vuln` (never run before; started 2026-10-14
14:51 NZ). Result: stopped after about 2 h 04 min; 21 hosts with results, 19 with
non-Log findings, none High or Critical; peak 4.3 GB / Redis 673 MB / load 48; no
runaway web UI. Unmanaged devices with Medium findings: .128, .177, .251. The scan
stalled on 192.168.1.253, a device that went offline mid-scan, which is why Phase 3
needs the `DURATION` hard stop. Next: nothing, the lan task has been re-applied with
the narrow excludes.

## Phase 1 - one job per scan

1. `gvm_fleet_targets_generate.py`: add `--managed-hosts-out FILE`, a secret-free
   JSON `{zone: [ip, ...]}` of managed hosts. Unit test.
2. `deploy-greenbone-stack.yml`, scan-program block: generate that file on the
   controller, copy it to `/opt/greenbone-stack/managed-hosts.json` (0644), and
   mount it into the scan-program container. (Today the managed list is only
   generated later, in the credential-program block.)
3. `setup_scan_program.py`: full-vuln `exclude_hosts` = `FIXTURE_EXCLUDE[zone]`
   plus the zone's managed hosts. Remove the hand `tier_a_exclude` lists. Set the
   full-vuln task preference `max_hosts` to about 6 (Phase 0 decides). The target
   fingerprint already rebuilds a task whose excludes changed.
4. `setup_schedules.py`: add a weekly schedule for each zone's Discovery task,
   inside 22:00-07:00 and clear of the credentialed slots, from measured
   discovery durations (6-40 min on 2026-08-29).
5. Apply with `--tags scan-program,schedule-program`; verify the full-vuln targets
   no longer contain managed hosts and that 26+12 schedules are present.

Acceptance: no managed host appears in any full-vuln target; every zone has a
scheduled discovery; the gateway `.1` of each VLAN stays in the unmanaged scan.

Status 2026-10-14: steps 1-5 done (applied and verified, including the lan task after
the Phase 0 baseline). Steps 1-4 were written with unit tests (generator export,
exclusion logic, playbook tasks, discovery schedules: Thursday 22:00 NZ, 30 minutes
apart). Step 5 (apply) waits for Phase 0. Details settled while writing it:

- The workstation (192.168.1.104) is on the managed list but has no working
  credentialed scan (sshd off), so it is deliberately kept in the unmanaged scan
  (`STILL_UNCOVERED` in setup_scan_program.py) until that is fixed.
- MikroTik (192.168.1.1) is excluded via `CREDENTIALED_ELSEWHERE`: it has its own
  credentialed task but is not in the managed list.
- If the managed-hosts file is missing the script fails; it never falls back to
  scanning whole zones.
- Applying rebuilds the full-vuln targets whose excludes changed (history for
  those tasks is lost, which is acceptable: all but a few have run once).


## Phase 2 - lean config for managed hosts (experiment, then adopt)

Facts: "Full and fast" has 60 families, 186,363 tests, all growing. "Web
application abuses" is 9,594 of them; "Web Servers" 1,047; "Product detection"
3,058 (it also holds the SSH-login detections, so do not drop it whole).

1. Clone "Full and fast" to **"Full and fast (lean)"** and turn off the
   "Web application abuses" family.
2. Experiment on one heavy host, 192.168.20.10 (authentik), solo, two runs with
   the same credentialed target: baseline and lean. Compare duration, peak Redis,
   and the sets of (host, test) results.
3. Decision gate: adopt if time falls by about half or more and the only findings
   lost are web-app probes. Known trade-off: HTTP-based product detection for
   containerised apps (Grafana, Portainer, ...) is what vulnerability-checks apps
   that package checks cannot see; Harbor's image scanning covers the images.
   If the lean config is not enough, a second variant also drops the "(HTTP)"
   product detections at test level.
4. Adopt: `setup_credentials.py` passes the lean config id to `create_task` /
   `modify_task` for the zone tasks; unmanaged full-vuln keeps "Full and fast"
   (web probing is useful on unknown devices).

### Phase 2 result (2026-10-15): lean config NOT adopted

Config "Full and fast (lean)" (59 families, 176,778 tests, "Web application
abuses" off) was run against "Full and fast", one host at a time, same credentialed
target:

| Host | Baseline | Lean | Findings lost |
|---|---|---|---|
| 192.168.20.10 (authentik) | 99 min, 216 results | 43 min, 197 | none |
| 192.168.120.10 (apps_seg) | 34 min, 60 | 21 min, 57 | none |
| 192.168.60.20 (game_seg) | 30 min, 61 | 22 min, 57 | Medium: Missing 'HttpOnly' Cookie Attribute (HTTP) |

Redis stayed about 350-520MB in every run. Lean loses real web findings (the
fleet-wide web-abuse tally is cleartext HTTP on infra/media/mgmt, Express NODE_ENV
development on ai, HttpOnly on game) and saves little on hosts that serve web
content. Decision: keep "Full and fast" for credentialed tasks. The OOM risk is
already covered by the Redis cap, `max_hosts` and SPLIT_HOSTS. The config still
exists on the scanner; `gvm_tuning.py mklean` recreates it and `famhosts` lists
hosts by family.

## Phase 3 - guaranteed night window

1. After one full weekly cycle, record every task's duration.
2. Test a schedule `DURATION` on a small task (build_seg): confirm gvmd stops the
   task when it elapses. Only if that works, add a duration ending 06:45 NZ to
   every weekly schedule.
3. Recompute slots from the measured durations so everything ends by 06:45 and
   nothing exceeds the concurrency limit (`--max-scans 3`).

## Next actions (in order)

1. (done) Phase 0 baseline recorded; lan task re-applied.
2. `provision.sh --stack greenbone-stack` (findings-ingest) to ship the coverage fix,
   then the real `terragrunt plan` drift check from the main checkout.
3. (done, not adopted) Phase 2 lean config experiment.
4. After one full weekly cycle, Phase 3 (durations, `DURATION` test, slot recompute).

## Later (recorded, not scheduled)

- Consolidate the three setup scripts into one reconciler driven by a single
  declarative plan file.
- NetBox auto-push of discovered devices; Grafana metrics; Discord alerting.

## Rollback

Every phase is a commit on a branch plus a tag-scoped apply. Reverting the
commit and re-running the same tags restores the previous targets and
schedules. Credentialed task history is unaffected (their fingerprints do not
change in Phase 1).
