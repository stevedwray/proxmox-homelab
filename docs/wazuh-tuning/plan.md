# Wazuh tuning plan

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

## Phase 0 - baseline and tooling (read-only)

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

## Phase 1 - quick wins (each is its own supervised change)

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

## Phase 2 - FIM and rootcheck tuning

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

## Phase 3 - vulnerability detector triage

1. Understand the 3,957 findings: 148 per agent, mostly the same packages (vim family
   about 3,000, libxml2, urllib3, containerd, runc). Check whether Debian 13 patch levels
   make these false or accepted, and compare with Greenbone and Harbor findings for the
   same hosts to see where the three tools agree.
2. Decide a policy: fix by patching (apt-cacher/unattended upgrades), accept by an
   exceptions list, or both. Only the detector's own supported exclusion mechanism is
   used, no index hacking.
3. Record a "known-accepted" list in the repo so a later deploy keeps it.
   Gate: findings reduced by action (patched or explicitly accepted), never by hiding.

## Phase 4 - capacity and sizing

1. With noise gone, measure again for 7 days: indexer heap, RSS, shards, EPS, disk growth.
2. Right-size the LXC (RAM, heap `wazuh_indexer_heap_gb`, shard count, one monthly index
   instead of daily for low-volume indices). Use the Proxmox-change-then-set-in-config
   pattern so Terraform does not see drift (as done for greenbone-stack).
3. Decide with the numbers whether the stack is a pve-tiny candidate (separate plan).
   Gate: documented steady-state numbers and headroom of at least 30% on RAM and heap.

## Phase 5 - coverage and detection testing (optional, operator decides)

1. List unenrolled hosts (framework, pve-tiny, others) and enrol per the existing role.
2. Per-agent-type test matrix (LXC Docker stack, hypervisor, bare metal): FIM paths,
   Docker monitoring, SCA results, syscollector inventory present.
3. Agent upgrade procedure documented and tested on one host before the fleet.

## Phase 6 - steady state

1. Grafana: reuse the Greenbone pattern (textfile exporter + dashboard): alerts per day,
   top rules, agents not active, queue usage, indexer heap and disk, events dropped.
2. Alert rules for those (delivery via Discord stays a separate plan).
3. A weekly noise review task: `wazuh_tuning.py alerts` flags any rule over 10% of volume.
4. Final docs pass: docs/wazuh-stack/README.md brought up to date (28 agents, current
   design), this workspace closed out, memory updated.

## Order, risk and sessions

| Phase | Risk | Session notes |
|---|---|---|
| 0 | none (read-only) | start here; produces the baseline and the regression suite |
| 1a, 1c, 1d | low | each independently approvable; 1d gives the biggest win |
| 1b | highest | upgrade, own slot, backup checkpoint |
| 2 | low-medium | needs per-path review with the operator |
| 3 | low | mostly analysis |
| 4 | medium | resize needs a maintenance moment |
| 5, 6 | low | optional / last |

Suggested first slice for the next session: Phase 0 in full, then 1a and 1d, because
together they remove most of the noise and the unhealthy flag with little risk.

## Done when

All phases accepted or explicitly dropped by the operator; every change is in the repo
and reproduced by a clean deploy; README baseline table has "after" values; docs and
memory are current; the branch is merged to `stable`.
