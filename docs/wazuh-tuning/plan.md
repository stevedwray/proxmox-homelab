# Wazuh tuning plan

**Status (2026-10-15): executed and merged to `stable` (PR #478); live on `pve`.** The phase text below is the
original plan (intent and gates). What actually happened, including every deviation, is in the table here and in the
per-phase records in [README.md](README.md#phase-records). Results against the targets: README "Results at a glance".

| Phase | Status | Where reality differed from the plan |
|---|---|---|
| 0 baseline, tooling, regression suites | **done** | Added a second tier (live actions on apt-cacher-stack) and a Docker tier (portainer-stack); counts cross-checked against the raw `alerts.json` (0.001% apart) |
| 1a dashboard healthcheck | **done** | Applied by editing the live compose and recreating only the dashboard (a playbook run would recreate all three containers) |
| 1b version skew | **done** | Upgraded to 4.14.8 (the fleet's version), not 4.14.9; backup was the nightly PBS snapshot (operator choice) instead of a manager-volume copy + indexer snapshot |
| 1c retention | **done** | 90 days (operator); plus pruning of the manager's raw logs, which Wazuh never rotates; the ISM plugin's system indices needed 0 replicas (cluster went yellow, fixed) |
| 1d rule 87907 | **done** | 40 exact, anchored level-0 rules generated from `docker_healthchecks.json`; `& < >` cannot be escaped in a pcre2 field, so they match as `.`; the 24 h gate is **pending** |
| 2a FIM ignore lists | **done** | Shared `agent.conf` per group, each block scoped to one agent by name; delivery needed stage-then-`mv` (a root-owned `docker cp` race made `remoted` skip the file) |
| 2b rootcheck 510 | **done** | 3,314 of 3,320 were LXC's own `/dev/.lxc*` files: one anchored level-0 rule; the 6 overlayfs events/day are left alone |
| 2c auth failures on graylog-stack | **done** | Not a graylog fault: MikroTik hAP log lines, 100% from the Greenbone scanner; lowered to L3 for that address and protocol only |
| 2d scanner sshd | **done** | Rules for 5710, 5712 (was L10) and 5760; 5740 has no source address, so it is not scoped |
| 3 vulnerability detector | **done, re-scoped** | Operator scoped the session to Wazuh and agents (no patching). Delivered `<nodiff>` for secrets, rootkit checks enabled fleet-wide, Debian profile, `vuln_triage.py`; syscollector and SCA reviewed and left alone |
| 4 capacity and sizing | **pending** | Needs ~7 days of post-tuning data; the Wazuh dashboard is the instrument |
| 5 coverage and detection testing | **pending, optional** | Known unenrolled: framework, pve-tiny, pentagi-stack |
| 6 steady state | **done, except** alert rules and a scheduled weekly review | Dashboard, exporter and scrape targets live; no provisioned Grafana alert mechanism exists in the repo; the noisiest-rule share is a dashboard stat instead of a scheduled task |

Method (carried over from the Greenbone work, where it found and fixed the scanner OOM
crashes and the 2x scan duplication):

1. **Baseline before touching anything.** The 2026-10-15 survey in README.md is the
   baseline; each phase re-runs the same queries afterwards.
2. **One change at a time, supervised, with a stop condition.** Never batch tuning
   changes: if a number moves we must know which change moved it.
3. **Numeric decision gates written down first** (adopt / do not adopt), like the lean
   config experiment. A change that fails its gate is reverted and recorded, not kept.
4. **Detection must not regress.** Every suppression is paired with a must-fire test
   (Phase 0) that proves the signal we care about still alerts. Tuning is allowed to make
   Wazuh quieter, never blinder.
5. **Config lives in the repo, not only on the host.** Live-only changes are used for
   experiments and are then moved into `deploy-wazuh-stack.yml` / role files before the
   phase closes. A later deploy must reproduce the tuned state.
6. **Read-only tooling first, mutation behind approval.** Survey modes never write. Any
   write goes through `./with-secrets-prod` with a named `TASK_APPROVAL` and a preflight
   summary, one task per approval.
7. **Resource guards.** Sampler running during every experiment; stop conditions below.
8. **Docs, memory and PRs kept current as each phase closes; everything merges to
   `stable` before the plan is called done.** No work left on branches.

Stop conditions for any supervised change: indexer heap above 85% for 5 minutes, free
RAM under 800MB, any `events_dropped` increase, any queue usage above 50%, a must-fire
test failing, an agent leaving `active`. Roll back first, investigate second.

## Phase 0 - baseline and tooling (read-only) - DONE

Goal: repeatable measurements and a regression suite, so every later phase has a
before/after.

1. Promote the three survey scripts (`terraform/lxc/ansible/files/wazuh-tuning/`) into a
   single helper `wazuh_tuning.py` with modes: `health` (containers, heap, disk, queues,
   agent versions), `alerts` (24 h by rule, agent, level, group), `noise <rule>` (breakdown
   of one rule), `agents`, `vulns`, `retention`, `fim <agent>`. Output also written as
   JSON so runs can be diffed.
2. A playbook `wazuh-tuning.yml` like `gvm-scan-tuning.yml`: copies the helper, runs a
   mode, supports the sampler (30 s: heap, RSS, free RAM, queue usage, events/s, disk).
3. Capture a **baseline report** (`docs/wazuh-tuning/artifacts/baseline-*.json`, ignored)
   and record the headline numbers in README.md.
4. Build the **must-fire suite** (small script run on the manager with `wazuh-logtest`
   plus a few live actions on one test agent): sshd failed and successful login, sudo
   to root, a new user, FIM change on a watched path (`/etc/passwd` on a test host), a
   container start and a non-health-check `docker exec`, a vulnerability-state change,
   an agent disconnect. Expected rule ids and levels are listed in the script. It runs
   before and after every change in later phases and must pass 100%.
5. Verify the survey counts against a second source (dashboard or `alerts.json`) once, so
   later numbers are trusted.

Gate: baseline recorded, must-fire suite green on current config.

## Phase 1 - quick wins (each is its own supervised change) - DONE

1a. **Dashboard healthcheck** - accept 401 as healthy (it proves the app answers) in
    `deploy-wazuh-stack.yml`; recreate only the dashboard container.
    Gate: container reports `healthy`; dashboard login still works.

1b. **Version skew** - decide per README decision 3. If upgrading: back up the manager
    volume and indexer snapshot first, upgrade manager, then indexer and dashboard to the
    same tag, verify all 28 agents `active`, pin the agent role to the same version.
    Gate: no agent disconnected, vulnerability detector and FIM still reporting, must-fire
    suite green. This is the highest-risk step of the plan, so it gets its own session
    slot and a stop-and-ask checkpoint after the backup.

1c. **Retention** - create an ISM policy (hot, then delete after N days; N from decision
    1) and attach it to `wazuh-alerts-4.x-*` plus an index template so new indices get it.
    Dry run first: list which existing indices the policy would delete and confirm with
    the operator. Gate: oldest index age equals N after one cycle; free disk non-decreasing.

1d. **Docker health-check noise (rule 87907)** - add a repo-managed `local_rules.xml`
    (delivered into the `wazuh_etc` volume by the playbook, with a validation step using
    `wazuh-analysisd -t` before reload) containing level-0 child rules of 87907 that match
    only health-check exec commands: `valkey-cli ... ping`, `healthcheck.sh`,
    `test -e $STATE_FILE`, and the other health commands found in the survey. Do not
    blanket-disable 87907. Experiment first on `logtest` with real sample events, then
    live, then compare 24 h later.
    Gate: alerts per day drop by at least 85%; the must-fire container tests pass;
    non-health-check `docker exec` still alerts.

## Phase 2 - FIM and rootcheck tuning - DONE

2a. **FIM ignore list**, repo-managed through agent groups' shared `agent.conf` (the
    mechanism already used for segments) rather than per-host ossec.conf edits:
    `/etc/pve/nodes/*/lrm_status` and other pmxcfs status files, our own sampler and
    runner logs under `/opt/greenbone-stack` and `/opt/actions-runner/_diag`, log files
    in general. Review the top 30 paths per agent first; ignore rules are per path,
    never per directory unless the directory is all logs.
    Gate: rule 550 volume down at least 80%; sensitive paths (`/etc`, `/usr/bin`,
    `/root/.ssh`, `/etc/sudoers.d`) still alert in the must-fire suite.
2b. **Rootcheck (rule 510)** - read the actual messages on three agents. Fix the cause
    where it is real (a genuine anomaly) and suppress only the specific known benign
    signature where it is not.
2c. **Auth failures on graylog-stack (rule 2501, 2,754/day)** - find the retrying
    client; this may be a real misconfiguration or an attack, so investigate before
    suppressing anything. Output: a note, a fix or a narrowly scoped rule.
2d. **Scanner-origin sshd events (192.168.70.11)** - narrow rules for 5710/5712/5740
    from the Greenbone scanner address only, level lowered not removed, so other sources
    still alert.
    Gate for phase: total alerts per day under 50k and no single rule above 10%.

## Phase 3 - vulnerability detector, SCA and inventory configuration (Wazuh side only) - DONE

Scope: Wazuh's own configuration and what the agents feed it. Applying host updates, removing packages and
changing pinned libraries are out of scope for this plan (operator, 2026-10-15).

1. Done: read-only analysis of the 3,957 findings against the Debian tracker (`vuln_triage.py`, README).
   Result: 97% are open/unassigned upstream, so the volume is a feed property, not a Wazuh fault.
2. Review the detector configuration on the manager (`<vulnerability-detection>`: enabled, index-status,
   feed update interval, offline vs online feed) and its cost on the indexer; tune only with evidence.
3. Review syscollector on the agents (package/OS inventory interval, hardware, ports, processes) for what the
   detector needs versus what is collected for nothing; check every agent reports a package inventory.
4. Review SCA (policies in use, run interval, result volume, failing checks that are LXC artefacts).
5. Decide how findings are surfaced (Phase 6 dashboard / weekly `vuln_triage.py` report), not hidden.
   Gate: documented settings with their reasons; any change has a before/after and keeps detection intact.

## Phase 4 - capacity and sizing - PENDING

1. With the noise gone, measure for ~7 days from the Wazuh dashboard (`/d/wazuh`; raw numbers via the helper's `health`
   and `retention` modes): indexer heap and RSS, shards, events per second, alert-index growth per day, disk used.
   Baseline for comparison: heap 69% of 4GB at 175 shards, ~0.4GB/day, ~1.3GB free RAM of 8GB.
2. Right-size the LXC (RAM, `wazuh_indexer_heap_gb`) and shard count: a one-shard-per-index template for new alert indices
   (a single node does not need 3-4 shards per index; 90-day retention would otherwise reach ~330 shards). Use the
   Proxmox-change-then-set-in-config pattern so Terraform sees no drift (as done for greenbone-stack).
3. Decide with the numbers whether the stack is a pve-tiny candidate (separate plan).
   Gate: documented steady-state numbers and headroom of at least 30% on RAM and heap.

## Phase 5 - coverage and detection testing (optional, operator decides) - PENDING

1. List unenrolled hosts (known: `framework`, `pve-tiny` hypervisor, `pentagi-stack`) and enrol per the existing role
   (`ansible/00-initial-setup/proxmox-wazuh-agent.yml` is the pattern for hypervisors and bare metal). Each enrolment
   needs the MikroTik rule for 1514/1515/55000 from its zone and a group in `agent_conf/`.
2. Per-agent-type test matrix (LXC Docker stack, hypervisor, bare metal): FIM paths, Docker monitoring, SCA results,
   syscollector inventory, rootkit checks. The live suite (`wazuh-mustfire-live.yml`) already takes `live_group`,
   `live_docker` and `live_rootcheck`, so a new host type is an inventory plus its case list.
3. Agent upgrade procedure documented and tested on one host before the fleet (the role now pins the version, so an
   upgrade is a deliberate change of `wazuh_agent_version` with the manager first).
4. Optional: a custom SCA policy that skips the CIS checks that cannot apply inside an LXC (baseline 43%, ~105 failing
   and 22 invalid checks per host).

### Phase 5a - `pve-test` (the laptop Proxmox node) - PLANNED, checks done 2026-10-16

Checked read-only, nothing changed. `pve-test` is a non-production Proxmox 9.2 node (Debian 13, kernel 7.0.14-17-pve,
4 CPU, 16GB RAM with ~11GB free) at `192.168.1.40`, on the default VLAN (`lan`, 192.168.1.0/24). It runs CT 910
(stopped template builder), CT 70010 `cse-kali` (running) and VM 70011 (stopped), no Docker, and has no Wazuh agent
(`/var/ossec` absent, no package).

| Check | Result |
|---|---|
| Manager reachable from `lan` | **yes**: 1514, 1515 and 55000 on 192.168.40.15 are open from both the workstation and `pve-test` itself, so **no MikroTik change is needed** (the same path serves `framework`, 192.168.1.18) |
| Existing pattern | `ansible/00-initial-setup/proxmox-wazuh-agent.yml` enrols the `pve` hypervisor with the `wazuh_agent` role (hosts: `pve.gibbsgreatly.xyz`); `pve-test.gibbsgreatly.xyz` is already in `ansible/inventory/production.yml` and `dev.yml` |
| Role fit | `wazuh_agent` is a plain apt install on Debian 13, so it fits as is (version pinned 4.14.8, `debian13` config profile, `/etc/pve/priv` already in `<nodiff>`) |
| Not production | not in `terraform/PRODUCTION_NODES`, so it does **not** go through `with-secrets-prod`; the secrets wrapper to use is still to be settled (see decision 1) |

Decisions needed from the operator before running anything:

1. **Secrets wrapper.** The role needs `WAZUH_AGENT_AUTHD_PASSWORD`, `WAZUH_API_PASSWORD` and `LAB_IP_WAZUH`, which come
   from the production OpenBao profile. Options: run through `./with-secrets-prod` with a named `TASK_APPROVAL` (the
   target host is still pve-test), or add a `pve-test` profile to the secrets manifest.
2. **Group.** Recommended: a new group `proxmox_host` (shared by `pve-test` and later `pve-tiny`) with its own
   `agent_conf/proxmox_host.xml`, kept out of the LXC zone groups so the hypervisor FIM does not skew the fleet
   numbers. The pattern in `pve`'s playbook currently sets no group (default).
3. **FIM scope.** `/etc/pve` is a FUSE cluster filesystem; realtime FIM on it can be noisy (VM config churn, `corosync`
   state) and `/etc/pve/priv` holds credentials. Start with the `pve` playbook's list (`/etc/pve`, `/etc/network`,
   `/etc/ssh/sshd_config`, `/root/.ssh`, `/etc/sudoers.d`) but measure FIM volume for an hour before accepting it.

Steps (each its own approval, in order):

1. Playbook: generalise `proxmox-wazuh-agent.yml` to take `hosts` and the group from vars (keep the `pve` default), or
   add `proxmox-wazuh-agent-pve-test.yml`; syntax-check it; add `agent_conf/proxmox_host.xml` and extend
   `test_agent_conf.py`. Commit on a `work/*` branch.
2. Enrol (mutating, one host): `export TASK_APPROVAL=wazuh-agent-pve-test`; run the playbook with `--limit
   pve-test.gibbsgreatly.xyz`. Out of scope: any change to the node's LXCs/VM, Proxmox config, MikroTik, or other hosts.
3. Verify: agent `active`, version 4.14.8, in the intended group, `agent.conf` merged (`verify-agent-conf`), syscollector
   and SCA (`cis_debian13`) results present, vulnerability detection populated.
4. Measure for one hour then 24 h with `wazuh_tuning.py agents/alerts/noise`: alerts per hour for this agent, top
   rules, FIM 550/554 share. Gates: agent stays active, no rule above 10% of fleet alerts, no `events_dropped`
   increase, manager free RAM stays above 800MB.
5. Add a live case (`live_group: proxmox_host`, `live_docker: false`) so the must-fire suite covers the new host type;
   record the result in README "Results at a glance" and the open-items list; update `docs/wazuh-stack/README.md`
   (enrolled count 27 -> 28).

Roll back: stop and disable `wazuh-agent`, `apt remove --purge wazuh-agent` on `pve-test`, and delete the agent on the
manager (`DELETE /agents`). `framework` follows the same shape after this proves out (Ubuntu, so the `debian13`
config profile and `cis_debian13` SCA policy need checking against its OS).

## Phase 6 - steady state - DONE (alert rules and weekly review aside)

1. Done: Grafana via the Greenbone pattern (role `wazuh_metrics`, textfile exporter, dashboard `wazuh.json`, scrape
   targets, cAdvisor on the host). The host also appears in Node Detail, Docker Containers and Lab Overview.
2. Open: alert rules. The repo has no provisioned Grafana alert mechanism (only a manual coredns example) and delivery
   (Discord) is a separate plan.
3. Weekly noise review: the "noisiest rule share" stat on the dashboard covers it; `wazuh_tuning.py alerts` is the
   detail view. Not scheduled as a task.
4. Done: docs pass (this workspace and `docs/wazuh-stack/README.md`) and memory.

## Order, risk and sessions

| Phase | Risk | Status | Notes |
|---|---|---|---|
| 0 | none (read-only) | done | produced the baseline and the regression suites |
| 1a, 1c, 1d | low | done | 1d gave the biggest win; each was its own approval |
| 1b | highest | done | own slot; PBS snapshot as the safety net |
| 2 | low-medium | done | per-path review with the operator; one delivery race found and fixed |
| 3 | low | done | re-scoped to Wazuh-side configuration |
| 4 | medium | pending | a resize needs a maintenance moment |
| 5 | low | pending, optional | |
| 6 | low | done | alert rules aside |

Every production change followed the same loop: preflight, operator "proceed", a named `TASK_APPROVAL`, the change, the
regression suites, the after-action summary. The manager was restarted about six times on 2026-10-15 for rule changes:
batch `local_rules.xml` changes in future.

## Next session

1. Take the 24 h measurements (runbook, "Re-measure the 24 h gates") and write the "after" values into the README.
2. Decide on Phase 4 once ~7 days of data exist; Phase 5 and the small follow-ups are listed in README "Open items".

## Done when

All phases accepted or explicitly dropped by the operator; every change is in the repo and reproduced by a clean
deploy; README has "after" values; docs and memory are current; everything merged to `stable`.

State: everything above is merged (#478) and reproduced by the repo, docs and memory are current. Remaining before the plan
can be closed: the 24 h "after" values, then Phase 4, and a decision on Phase 5.
