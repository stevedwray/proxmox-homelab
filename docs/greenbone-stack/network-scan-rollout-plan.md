# GVM network-wide discovery & vulnerability scanning — rollout plan

Status: **scoped, not started.** Decisions below were made with the operator
2026-08-16; this file is the plan to implement them. Read
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

**Not yet done**: an actual reachability spot-check (`nc -zv`/`ping`) from
inside `greenbone-stack` into 2–3 destination zones. The firewall rule
being present and correctly placed is strong evidence but not the same as
observed traffic — this needs either the operator running a couple of
commands directly on `greenbone-stack`, or an SSH session against
production `pve` on my end, which needs the standard `TASK_APPROVAL` flow
per CLAUDE.md before I'd run it myself.

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

- **Two GVM Scan Configs**, not one:
  - `Discovery Only` — host-alive + port sweep, no vulnerability NVTs. Safe
    against fragile/production hosts.
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
- **Targets**: one GVM Target per zone (by CIDR) is the likely right grain
  to keep task count manageable, rather than one per host — revisit if a
  zone's scan time or noise level argues for splitting it up.
- **Real open capacity question, not yet answered**: `greenbone-stack` is
  sized at Greenbone's stated *minimum* (2 cores / 4096 MB), justified
  originally for one-off authorized-target scans. Daily discovery sweeps
  across 8 network segments plus a weekly full-vuln pass is a materially
  different, heavier standing load. Watch scan duration and container
  resource usage after the first week; revisit sizing if scans are still
  running when the next one is due to start.

## Phase 3 — Credentialed scanning (decided 2026-08-16: deferred)

**Explicitly deferred, not just "not decided yet."** This rollout ships
unauthenticated (network-visible findings only). Credentialed scanning
(SSH creds for Linux/LXC hosts, a scoped read-only account — not root, not
an existing admin credential) is a real follow-on phase, but only once the
unauthenticated program is running cleanly and trusted — no target date.
When it's picked up, it needs its own credential-provisioning design (new
SOPS keys, per-asset-type credential scope) as its own pass, not an
add-on to this plan.

## Phase 4 — Scheduling

GMP's native `Schedule` objects (icalendar-based), attached directly to
Tasks — **not routed through `gvm-bridge` or PentAGI**; that integration
exists for agent-triggered on-demand scans and is a different mission from
standing recurring scans. Create via the same `gvm-cli` file-bind-mount
pattern the deploy playbook already uses for GMP calls (see README.md's
"LDAP login" section, gotcha #1) or directly in GSA once, then confirm it
persists.

- **Daily**: `Discovery Only` config, all in-scope zones + LAN.
- **Weekly**: `Full and fast` config, Tier B hosts immediately, Tier A hosts
  once individually promoted.
- Respect Greenbone's own documented warning that feed sync is slow and
  asynchronous — a scheduled scan against a mid-sync feed gives "incomplete
  and erroneous results" per their own docs, already noted in README.md.

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

`task/gvm-lan-scan-rollout` has Phase 1 **done and live** — see above.
Remaining before Phase 1 is fully closed out, then moving on:

1. Optional but recommended: an actual reachability spot-check
   (`nc -zv`/`ping`) from inside `greenbone-stack` into 2–3 destination
   zones, to confirm real traffic, not just rule presence. Not done yet.
2. Start Phase 2 — scan configs (`Discovery Only` vs `Full and fast`),
   Tier A/B target classification, per-zone GVM Targets. Not started.
   Everything in Phase 2 onward is local to `greenbone-stack` itself (GMP
   calls against its own GVM instance), not a shared-infrastructure change
   like Phase 1 was — lower-stakes to iterate on.

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
