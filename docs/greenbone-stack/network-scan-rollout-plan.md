# GVM network-wide discovery & vulnerability scanning — rollout plan

Status: **Phases 1, 2, and 4 (weekly full-vuln scheduling) done and live in
production, confirmed by a successful unattended overnight run 2026-08-17.**
Phase 4's daily-discovery half, Phase 3 (deferred by decision), Phase 5, and
Phase 6 remain open — see each phase's own status line below. Decisions
below were made with the operator 2026-08-16; this file is the plan to
implement them. Read
[README.md](./README.md) and [pentagi-integration.md](./pentagi-integration.md)
first — this project extends the same `greenbone-stack`, but is a genuinely
different mission from both of those: this is *standing, scheduled,
network-wide* scanning, not a one-off authorized test scan or an
agent-triggered on-demand scan.

## Goal

Turn `greenbone-stack`'s GVM/OpenVAS instance from "a scanner that can hit
one authorized target when asked" into a routine discovery + vulnerability
scanning program covering the whole home network and lab: every Proxmox SDN
zone on `pve`, plus the flat `192.168.1.0/24` LAN.

## Why this isn't just "add a few more targets"

`greenbone-stack` sits in `pentest_seg` (VLAN 70), which is a **deny-by-default,
explicit-narrow-allow** zone — the same containment model `pentagi-stack`
relies on. Today `pentest_seg`'s only outbound reach is a short, specifically-
justified list (`terraform/lxc/network/pve.yaml` `policies:`): `infra_seg`
apt-cacher (3142), Harbor via `edge_seg` (80/443), `framework.gibbsgreatly.xyz`
(specific ports), `mgmt_seg`'s LDAP outpost (3389/6636, added for Greenbone's
own per-user login), the monitoring scrape rules, and two single-host
"authorized target" rules (`192.168.1.113` Metasploitable2, `192.168.1.55`
`harness-target`). Everything else is an explicit deny.

Scanning the whole LAN and every VLAN requires the **opposite shape**: broad
reach from one host to many destinations, not narrow reach to one destination.
That's a real, deliberate widening of what this zone can touch — not a
config tweak, and not something to fold into a routine PR without calling it
out. Treat Phase 1 below with the same seriousness CLAUDE.md gives production
credential mutations, even though `pve`'s own SDN/firewall changes aren't
gated by `TASK_APPROVAL` the way `pve`/`pve-framework` API mutations are.

## Decisions made 2026-08-16 (operator)

| Decision | Choice |
|---|---|
| Vantage point | **Reuse `greenbone-stack` in `pentest_seg`.** No new zone. New rules are scoped by *source = `greenbone-stack`'s own IP* (`${lab_ip_greenbone}`, canonical `192.168.70.11` on `pve`), not blanket `pentest_seg` — `pentagi-stack`'s own containment is unchanged. |
| Sensitive/production infra (Authentik, Harbor, Traefik, step-ca, the Proxmox hosts, NAS) | **Discovery/safe scan only at first.** Full vulnerability probes against these are deferred until the discovery tier has run cleanly for a while and is explicitly promoted per-host. |
| Flat-LAN scope | **Whole `192.168.1.0/24` range, including untracked devices** — not limited to what's already in `static_hosts`. |
| Cadence | **Daily discovery scan, weekly full vulnerability scan.** |
| Phase 3 (credentialed scanning) | **Keep deferring.** Not designed as part of this rollout; revisit once the unauthenticated program is running and trusted. |
| NAS IP | **`192.168.1.3`**, per prior documentation — treated as confirmed for this plan. |
| Tier A promotion | **Promote later, once proven stable.** Discovery-only runs first; individual Tier A hosts get promoted to the weekly full-vuln schedule one at a time, operator's call per host — not a blanket policy either way. |
| Newly-discovered LAN devices | **Auto-push to NetBox.** Every device the discovery scan finds gets written into NetBox automatically — no manual curation step. |
| Alert severity floor | **Medium-or-higher to start**, as originally proposed — tune once real scan volume/noise is observed. |

One consequence of the vantage-point choice worth being explicit about: this
makes `greenbone-stack`'s own blast radius, if it's ever compromised, equal
to "reaches everything on the network" — a materially bigger exposure than
today's narrow allowlist. That's the accepted tradeoff of not standing up a
second zone; it should be a conscious fact, not a side effect nobody named.

And on the "whole `192.168.1.0/24`, including untracked devices" choice: the
LAN includes at least two Raspberry Pis (`argon-01`/`192.168.1.22`,
`argon-02`/`192.168.1.23`, role `iot`) and a personal workstation
(`linux-desktop`/`192.168.1.104`) per `network/pve.yaml`'s `static_hosts`,
plus whatever else shows up in a discovery sweep (phones, guests, etc. are
plausible on a home LAN). Discovery scans are low-risk; some consumer/IoT
gear genuinely does misbehave under an active vulnerability scan config
(`Full and fast` is not gentle). Recommend the weekly full-vuln pass still
respects the Tier A/B split below for anything that isn't a known lab/infra
asset until it's been observed tolerating a scan cleanly at least once.

## Phase 1 — Firewall: broaden `greenbone-stack`'s reach

**Status: DONE, applied and independently confirmed live, 2026-08-16.**
Applied manually via the router's own Safe Mode console (operator-run, not
the Ansible playbook) after a live read-only inspection corrected an
assumption: the actual `pentest_seg` containment mechanism is
`in-interface=vlan70-pentest` on rule `*3B` (`pentest_seg default-deny to
LAN/other zones`), not a `src-address` match — none of the six destination
zones have their own inbound-side deny, so `*3B` was the only anchor that
mattered. All 7 rules were placed immediately before it via
`place-before=[find comment="pentest_seg default-deny to LAN/other zones"]`.

**Independently re-verified after the fact** (fresh `GET /rest/ip/firewall/filter`
from outside the console session, not an in-session check — see
[[reference_routeros_safe_mode]] on why that distinction matters): all 7
rules present at `*6D`–`*73`, `src-address=192.168.70.11` (confirmed this is
`pve` production's IP, not `pve-test-vm`'s `.111` — `with-secrets` defaults
`PVE_ENV=pve-test-vm`, checked `.env.pve` directly to be sure), correct
destination CIDR each, all sitting directly before `*3B` at its new
position. Total rule count went 90 → 97 (exactly +7), disabled-rule count
unchanged at 6 — nothing else in the table was disturbed.

`terraform/lxc/network/pve.yaml`'s `policies:` block documents this as
live (see below the table). The Ansible playbook
(`mikrotik-firewall-greenbone-lan-scan-reach.yml`) was written first but
wasn't the tool actually used to apply this — its anchor-selection logic
has been corrected to match the real mechanism discovered live (see the
file itself) so it stays a valid idempotent path for any future
re-application, rather than describing a different, looser assumption
than what's actually live.

**Superseded**: this section originally flagged an outstanding reachability
spot-check (`nc -zv`/`ping`) as not yet done. That's since been proven far
more thoroughly than a spot-check ever would — see the manual scan
validation and the first scheduled overnight run further down, both of
which are real scan traffic reaching every zone repeatedly.

Add new MikroTik rules, all **scoped by source IP = `greenbone-stack`'s own
address only**, one rule per destination zone (mirrors the existing
Metasploitable2/`harness-target` precedent of scoping by IP rather than by
port list, since open-ended discovery/vuln scanning is inherently
"enumerate whatever's there," not a fixed port set):

| From | To | Protocol | Notes |
|---|---|---|---|
| `greenbone-stack` IP | `build_seg` (`192.168.10.0/24`) | all | |
| `greenbone-stack` IP | `mgmt_seg` (`192.168.20.0/24`) | all | Supersedes/extends the existing narrow `pentest_seg → mgmt_seg:3389,6636` LDAP-only rule — that rule can stay (it's `pentagi-stack`+`greenbone-stack` both using it for LDAP), this is additive. |
| `greenbone-stack` IP | `edge_seg` (`192.168.30.0/24`) | all | |
| `greenbone-stack` IP | `infra_seg` (`192.168.40.0/24`) | all | |
| `greenbone-stack` IP | `ai_seg` (`192.168.50.0/24`) | all | |
| `greenbone-stack` IP | `game_seg` (`192.168.60.0/24`) | all | |
| `greenbone-stack` IP | `192.168.1.0/24` (flat LAN) | all | |

No new inbound rules needed — MikroTik's stateful firewall handles
established/related return traffic, same as every existing outbound-only
rule in this file.

**Two real gotchas from prior work, both apply here:**
- **Rule ordering.** `harness-target.md` documents a live incident where a
  new `pentest_seg`-sourced rule was appended *after* `pentest_seg`'s own
  catch-all deny and was silently dead despite being correctly written.
  Every new rule here needs the same check — confirm placement *before* any
  applicable catch-all, in every zone that has one, not just `pentest_seg`'s.
- **`terragrunt plan` sanity check**, per CLAUDE.md's execution guardrails —
  confirm the target node before applying, and confirm the plan shows only
  additive rule creation, not modification/deletion of any existing rule.

**Validation tier (per CLAUDE.md's table):** this reads as "Terraform/
network/SDN/firewall — additive only" (new narrowly-scoped cross-zone rules,
zero changes/deletions to existing resources) *if* `terragrunt plan` bears
that out — apply, then `scripts/provision.sh --stack <name>` against 1–2
existing stacks in adjacent zones to confirm no regression. Full teardown is
owed before promoting past `stable` per the table, but is **not** the default
per-iteration validation — do not schedule one without an explicit operator
ask, per CLAUDE.md and [[feedback_avoid_full_teardown_scale]].

## Phase 2 — Target inventory & scan-config tiers

**Status: DONE, validated live on `pve-test-vm`, 2026-08-16.**
`terraform/lxc/ansible/files/greenbone-scan-setup/setup_scan_program.py`
creates all 14 Targets/Tasks (one Discovery + one Full-and-fast pair per
zone/LAN) idempotently via python-gvm, mirroring `gvm-bridge/app.py`'s
already-live-proven call shapes. Wired into `deploy-greenbone-stack.yml`
as new tasks at the end of the existing play (copies the script in, runs
it once via the same throwaway `gvm-tools` container pattern already used
for `modify_auth.xml`). **Simplification found**: GVM ships a built-in
`Discovery` scan config — used that directly rather than authoring a new
custom config from scratch.

**Validated by running the script directly against the running `gvmd`**
on `pve-test-vm` (not via a full `provision.sh` re-deploy — that re-pulls
every image and touches unrelated config; only the one new script needed
exercising). All 14 Targets + 14 Tasks confirmed created, then a second
clean run confirmed full idempotency (all 28 objects "already exists,
skipping", zero duplicates).

**Three real bugs found and fixed getting there, none guessable from
`gvm-bridge`'s precedent alone**:
1. `alive_test`'s draft string ("ICMP, TCP-ACK Service Ping, ARP Ping")
   doesn't match any `AliveTest` enum value — python-gvm raises
   `InvalidArgument`. The real combined-default string, confirmed by
   enumerating the live enum, is `"ICMP, TCP-ACK Service & ARP Ping"`
   (comma + ampersand, "Service" not "Service Ping" mid-clause).
2. `create_target` has **no implicit port default** — omitting both
   `port_list_id` and `port_range` fails with `GvmResponseError 400: One
   of PORT_LIST and PORT_RANGE are required`. Fixed by resolving GVM's
   built-in `"All TCP and Nmap top 100 UDP"` port list by name (the same
   one `Full and fast` pairs with by default) and passing its ID to every
   Target.
3. `exclude_hosts` wants a `list[str]`, not a pre-joined comma string —
   passing a joined string produced `GvmResponseError 400: Error in host
   specification`. Matches the same shape as `hosts=[cidr]`, just missed
   on the first pass.

**Real infra incident hit during validation, unrelated to any of the
above, worth its own note**: manually running `docker compose run` for
one service against this stack while an earlier, interrupted
`provision.sh` invocation's `docker compose up --pull always` was *still
running in the background on the remote host* caused a genuine
container-recreate race (`gvmd`/`ospd-openvas` got stuck in `Created`,
one container hit a hash-prefixed rename conflict). Recovered cleanly by
killing both stale processes and running one clean `docker compose up
-d` to settle the stack — no data loss, but a real lesson: **always
check `ps aux | grep docker.compose` on the target host for a still-running
process before starting another one**, especially after a locally
interrupted/cancelled command — the remote side doesn't necessarily stop
just because the local tool call was cancelled.

- **Two GVM Scan Configs**, not one:
  - `Discovery` — GVM's own built-in config; host-alive + port sweep, no
    vulnerability NVTs. Safe against fragile/production hosts.
  - `Full and fast` — the existing config already used for the authorized
    Phase 4 test scan and the `gvm-bridge` integration. Real vulnerability
    probes; not guaranteed non-disruptive.
- **Tier A (discovery-only until explicitly promoted per-host):** the
  Proxmox hosts themselves (`pve`, `pve-test-vm`), the MikroTik router,
  the NAS (`192.168.1.3`), Authentik, Harbor, Traefik, step-ca. These are
  the assets where an intrusive probe causing a hiccup has platform-wide
  consequences. **Promotion policy (decided 2026-08-16): promote later, not
  never.** Once the discovery-only tier has run cleanly for a while,
  individual Tier A hosts get promoted to the weekly full-vuln schedule one
  at a time — operator's call per host, no blanket "all of Tier A moves
  together" step.
- **Tier B (full vulnerability scan from the start):** everything else —
  the rest of the LXC fleet, `build_seg`/`ai_seg`/`game_seg` app containers,
  the Raspberry Pis, the workstation, and LAN unknowns turned up by
  discovery (subject to the "observed tolerating a scan once" note above).
- **Exclude `192.168.1.113` (Metasploitable2) and `192.168.1.55`
  (`harness-target`) from the routine/scheduled population.** Both are
  deliberately, permanently vulnerable red-team targets whose findings are
  known and meaningless as "new vulnerability" signal — they'd just be
  scheduled noise. They stay reachable for the existing on-demand
  PentAGI/`gvm-bridge` path, which is a separate mission from this one.
- **`alive_tests`**: do not blanket-copy `gvm-bridge`'s hardcoded
  `Consider Alive` — that was justified specifically because the lab targets
  are deliberately ICMP-firewalled. Most LAN/VLAN hosts do respond to ICMP
  normally; verify per zone rather than assuming.
- **Targets**: implemented as *two* GVM Targets per zone (by CIDR), not
  one — a zone can contain a mix of Tier A and Tier B hosts (e.g.
  `mgmt_seg` has Authentik/step-ca alongside Portainer/monitoring/DNS), so
  the Discovery Target covers the whole zone CIDR while the Full-and-fast
  Target for that same zone uses GMP's `exclude_hosts` to carve out its
  Tier A members. Revisit target grain if a zone's scan time or noise
  level argues for splitting further.
- **Capacity question, partially answered 2026-08-16**: operator manually
  triggered `lan discovery` alone, then all 6 zone discovery scans
  concurrently, on production `pve`, to observe real behavior (not yet
  the daily-schedule automation, Phase 4 — a manual one-off exercise of
  the same Tasks). Findings:
  - **CPU is the real constraint, not memory.** With all 6 zone scans
    running concurrently, host CPU stayed pinned at 95-100% for the
    entire run (`ospd-openvas` alone measured up to 187% via `docker
    stats` — already over the 2-core ceiling on its own). Memory never
    exceeded ~56% (2.3GB/4GB) and dropped to ~27% by the end — comfortable
    throughout. **2 cores is the binding limit for this stack, not the
    4096MB memory allocation** — revisit *cores* first if scan duration
    becomes a problem, not memory.
  - **Long flat-progress plateaus are normal, not a hang.** Both the
    single `lan discovery` run and the 6 concurrent zone runs each showed
    multi-minute (up to ~9 min) periods where the GMP `progress` field
    didn't move at all. Confirmed via `docker stats` during one such
    plateau: `ospd-openvas` was at ~187% CPU, genuinely still computing
    (`gvmd`/`ospd-openvas` container logs are near-silent during this
    phase, which looks alarming but isn't). Don't treat a stalled
    percentage alone as a failure signal when scheduling/alerting logic
    is built in Phase 4/5 — check actual host resource usage or wait
    longer before concluding a scan is stuck.
  - **All 7 discovery scans (6 zones + `lan`) completed and produced real,
    distinct, non-empty results** — nothing came back silently empty (the
    exact failure mode the `alive_tests` gotcha exists to prevent).
    Result/host counts: `lan` 511 results/23 hosts, `mgmt_seg` 478/14,
    `infra_seg` 176/7, `edge_seg` 109/3, `ai_seg` 63/4, `build_seg` 41/3,
    `game_seg` 39/2.
  - **Still open**: this was one manual concurrent batch, not the actual
    daily-schedule automation (Phase 4) or a full-vuln run (heavier
    per-host than discovery). Whether the current 2-core sizing holds up
    under the real Phase 4 cadence (daily discovery + weekly full-vuln,
    potentially overlapping) is still unconfirmed — revisit if scheduled
    scans are still running when the next one is due to start.

## Phase 3 — Credentialed scanning (first pass: ready to apply, 2026-08-19)

The first pass deliberately reuses SSH access that already exists; it does
**not** provision users, keys, sudo policy, or SSH configuration on scan
targets. It is intentionally a home-lab trade-off, recorded here rather than
silently treating Greenbone as a holder of a new least-privilege identity.

- `GREENBONE_STEVE_SSH_PRIVATE_KEY` (SOPS) authenticates as `root` to the
  managed Debian services and `pve`, and as `ansible` to `argon-01` and
  `argon-02` (which already have passwordless sudo).
- `GREENBONE_OPENVAS_WORKSTATION_SSH_PRIVATE_KEY` (SOPS) authenticates as the
  existing `openvas` user on the workstation. Its GUI-login visibility and
  any sudo password are independent of SSH key authentication.
- `setup_credentials.py`, invoked only with
  `ANSIBLE_TAGS=credential-program`, creates named GVM SSH credentials plus
  explicit, initially unscheduled `Full and fast` Targets/Tasks. Existing
  CIDR Targets remain anonymous: a root credential must never be attached to
  an entire subnet or to discovered unknown hosts.
- The Asustor NAS is deliberately excluded until its ADM-managed SSH-key
  credential has been separately imported into SOPS.

`pve-test-vm` is powered down and out of scope, so this pass cannot use the
normal test-hypervisor validation path. Do not apply it to `pve` without the
standard production-mutation preflight and explicit operator approval. First
run each credentialed Task manually; attach a schedule only after confirming
that it authenticates and has acceptable impact.

## Phase 4 — Scheduling

**Weekly full-vuln scheduling: DONE, LIVE on both `pve-test-vm` (validated,
then detached) and production `pve` as of 2026-08-16.** Daily discovery
scheduling is NOT done — separate, not yet requested.

GMP's native `Schedule` objects (icalendar-based), attached directly to
Tasks via `modify_task(schedule_id=...)` — **not routed through
`gvm-bridge` or PentAGI**; that integration exists for agent-triggered
on-demand scans and is a different mission from standing recurring scans.
Created via a real python-gvm script
(`terraform/lxc/ansible/files/greenbone-scan-setup/setup_schedules.py`),
tagged `schedule-program` in `deploy-greenbone-stack.yml` (separate tag
from Phase 2's `scan-program`), same idempotent create-by-name pattern.

**What's live**: the 7 `full-vuln` Tasks (one per zone + LAN) each got
their own weekly Schedule, operator-specified 2026-08-16 — staggered an
hour apart, LAN deliberately last, first run 2026-08-16 22:00
Pacific/Auckland, recurring weekly indefinitely:

| Time (Pacific/Auckland) | Zone |
|---|---|
| 22:00 | build_seg |
| 23:00 | mgmt_seg |
| 00:00 (+1d) | edge_seg |
| 01:00 | infra_seg |
| 02:00 | ai_seg |
| 03:00 | game_seg |
| 04:00 | lan |

**Design decisions made building this**:
- `DURATION` deliberately omitted from every VEVENT. gvmd defaults it to
  `PT0S` when absent (confirmed live) and, per its own scheduler source
  (`scheduled_task_handle_start_success` in `gvmd`'s `src/manage.c`), only
  treats a 0-duration schedule as "once-off, auto-detach" when
  `task_schedule_next_time` is *also* 0 — an ongoing `RRULE:FREQ=WEEKLY`
  keeps `next_time` non-zero, so this path never trips. No risk of gvmd
  aborting an in-progress scan just because it runs past the 1-hour
  stagger interval (full-vuln scans routinely do).
- `schedule_periods` left at its default (0) — confirmed via the same
  gvmd source to mean unlimited scheduled runs, not zero runs.
- DTSTART is a naive local time; the separate `timezone="Pacific/Auckland"`
  argument to `create_schedule` is what gvmd applies to it. gvmd
  auto-generates a full DST-aware `VTIMEZONE` block for Pacific/Auckland
  on creation (confirmed live) — the 22:00 local-time trigger stays
  correct across DST transitions without any manual adjustment.
- Schedules **actually trigger runs**, unlike Phase 2's inert
  Targets/Tasks — so after validating on `pve-test-vm`
  (`ANSIBLE_TAGS=schedule-program`), the test-env schedules were detached
  (`modify_task(schedule_id="0")`) and deleted
  (`delete_schedule(ultimate=True)`) before applying to production, to
  avoid a second host duplicating tonight's scan load against the same
  live network. The validated script itself stays tracked; only the live
  attachment was removed from the test env.

Still to do for Phase 4 in full: **Daily** `Discovery Only` scheduling,
all zones + LAN — not requested yet, no schedule exists for the Discovery
tasks. Also still applies: respect Greenbone's own documented warning
that feed sync is slow and asynchronous — a scheduled scan against a
mid-sync feed gives "incomplete and erroneous results" per their own
docs, already noted in README.md.

## Phase 5 — Results pipeline (the GSA reports page is broken — plan around it, don't rediscover it)

`gvmd`'s `get_reports` GMP call crashes the daemon (known upstream bug,
`greenbone/gvmd` #2273 — see README.md). A standing scan program needs a way
to actually read results without that call. Plan:

- A small periodic job (host cron on `greenbone-stack`, independent of
  `gvm-bridge`) using `get_results` — same call `gvm-bridge` already uses
  correctly (task-scoped via `filter_string`, `rows=-1` to avoid pagination
  truncation, per the three bugs already found and fixed there) — against
  completed scheduled Tasks.
- **Ship findings to Graylog**, not a new sink — Graylog already ingests
  syslog from the Proxmox host, MikroTik, and the NAS
  (`docs/design/architecture.md`), so this is a natural extension rather
  than a new piece of infrastructure.
- **Severity floor before alerting (decided 2026-08-16): Medium-or-higher
  to start.** A daily whole-network discovery sweep plus weekly full-vuln
  scans will surface a lot of low-severity chatter — Medium-or-higher pages/
  alerts, the full result set still lands in Graylog for manual review
  regardless of the floor. Explicitly a starting point, not a final
  tuning — revisit once real scan volume/noise has actually been observed;
  it couldn't be tuned properly before that data exists.
- **"New since last scan" diffing** is valuable (the actual point of
  *regular* scanning is catching change) but non-trivial — treat as a
  stretch goal once the basic pipeline is running, not a Phase 5 blocker.
- **NetBox auto-population (decided 2026-08-16): on.** Every device the
  discovery scan finds — including previously-untracked LAN devices — gets
  written into NetBox automatically, no manual curation step. This is a new
  write path into NetBox (today's `populate.py` discovery is read-only
  against Docker socket proxies/Portainer, not a general network-scan
  ingester) — implementation needs to either extend `populate.py` or add a
  small adjacent script that consumes the discovery scan's own results and
  upserts into NetBox's device/IP models. Decide the exact mechanism during
  implementation, not in this scoping pass.

## Phase 6 — Validation & promotion

Two CLAUDE.md validation tiers both apply and need to both pass before
promoting past `stable`:
- The Phase 1 firewall change — additive-only network tier (see Phase 1).
- Any playbook/role changes to `greenbone-stack` itself (new scan configs,
  schedules, the results-pipeline cron job) — Ansible task/role tier:
  `scripts/provision.sh --stack greenbone-stack` on `pve-test-vm`.

Validate on `pve-test-vm` first, exactly as the original deployment did.
This project does not need, and should not default to, a full teardown
cycle — per CLAUDE.md and [[feedback_avoid_full_teardown_scale]], that's
reserved for an explicit operator ask by name.

## Open questions carried forward, not yet decided

All five decision points originally listed here were resolved with the
operator 2026-08-16 (folded into the "Decisions made" table and the
relevant phase sections above). What remains genuinely open, not a
decision so much as something that can't be known until the program is
actually running:

1. The exact NetBox write mechanism for Phase 5's auto-population (extend
   `populate.py` vs. a new adjacent script) — an implementation detail to
   settle during Phase 5, not a scoping-level decision.
2. Whether `greenbone-stack`'s current sizing (2 cores / 4096 MB) holds up
   under the new daily/weekly load — Phase 2's capacity note; only
   answerable by watching real scan durations after rollout.
3. Where the Medium-or-higher alert floor actually needs to move once real
   noise volume is observed (Phase 5) — deliberately left for after
   real data exists, not decided now.

## What's next (2026-08-16 checkpoint)

`task/gvm-lan-scan-rollout` has **Phase 1 and Phase 2 done and live on
both `pve-test-vm` and production `pve`** as of 2026-08-16.

Phase 2 was applied to production via the tracked IaC path — same
tag-scoped `provision.sh` invocation validated on `pve-test-vm`, run
against `pve` under `TASK_APPROVAL`:
```
ANSIBLE_TAGS=scan-program TASK_APPROVAL=<name> ./with-secrets-prod scripts/provision.sh --stack greenbone-stack
```
First run: `ok=3, changed=2` (genuinely new — production had none of
these objects yet, unlike `pve-test-vm`). Immediate second run:
`ok=3, changed=0`, confirming idempotency holds on production the same
as it did on test. All 14 Targets + 14 Tasks are now live on production
`greenbone-stack`.

**Manual reachability validation done, same day**: operator triggered
`lan discovery` and then all 6 zone discovery scans concurrently on
production `pve` (via GSA, not Phase 4 automation), confirming real
traffic end-to-end — see the capacity findings above for the full
results/performance data. This also stands in for the "optional
reachability spot-check" item that was on this list — real production
scan traffic into every zone, not just a `ping`, is stronger evidence
than the originally-planned narrower check.

Remaining:

1. Start Phase 3 (deferred by decision) / Phase 4 (scheduling) / Phase 5
   (results pipeline) — none started yet.
2. Decide whether the current 2-core sizing needs revisiting before
   Phase 4 turns this into a recurring daily/weekly load — see the
   capacity findings above.

## Related documentation

- [README.md](./README.md) — the live `greenbone-stack` deployment record,
  known limitations (`get_reports` crash, host-alive gotcha), and network
  facts this plan builds on.
- [pentagi-integration.md](./pentagi-integration.md) — the sibling,
  already-implemented on-demand/agent-triggered scanning path via
  `gvm-bridge`. Different mission from this one; both share the same GVM
  instance and the same two GVM gotchas, but this plan's scans are
  scheduled and network-wide rather than agent-triggered and single-target.
- `terraform/lxc/network/pve.yaml` — current zone layout, `static_hosts`
  inventory, and the existing `policies:` block Phase 1 extends.
- `ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml`
  — Phase 1's actual playbook, written and syntax-checked, not yet run.
- `docs/design/architecture.md` — confirms Graylog already ingests syslog
  from the Proxmox host, MikroTik, and NAS (Phase 5's sink choice).
- `docs/pentagi-stack/harness-target.md` — source of the MikroTik
  rule-ordering gotcha Phase 1 must re-check.
- `CLAUDE.md` — validation tiers (Phase 1/6) and the standing rule against
  defaulting to full-teardown-scale validation.
