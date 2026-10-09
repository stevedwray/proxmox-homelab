## Status

**All three phases (GVM, Wazuh, Graylog) fully deployed to production and
verified live as of 2026-09-30.** Written 2026-09-29 following
`docs/agent-design/README.md`'s process, then executed directly in the
same session (operator judged it too complex for `/implement-step`
local-model dispatch) rather than handed off step by step. See `README.md`
for the current, day-to-day status; this section is the phase-by-phase
build history.

- **Phase 1 (GVM)**: `gvm-01` through `gvm-07` all written, deployed, and
  verified live. `gvm-03` (secrets/manifest.json, 25 entries) was done by
  the operator directly (this session's permissions denied all access to
  `secrets/`); `gvm-04`'s bootstrap ran and all 25 stacks' credentials
  confirmed live in OpenBao; all 25 stacks redeployed with
  `gvm_scan_account`, verified via a real credentialed probe (SSH login +
  sudo elevation both confirmed working, not just assumed); `greenbone-
  stack` redeployed, `gvm-07` registered all 25 hosts' credentials/
  Targets/Tasks in GVM, verified via an idempotent re-run. **`gvm-08`**
  (added after initial Track A deploy, per the operator's "divide scans up
  by VLAN" request) organizes the 25 per-host Tasks by network zone via a
  per-zone GVM Schedule + Tag -- a shared multi-host Target per zone isn't
  possible (confirmed against upstream python-gvm: one `ssh_credential_id`
  per Target, no per-host override, in any shipped GMP version), so this
  keeps the 25 individual credentialed Targets and groups scheduling/
  visibility around them instead. Deployed and verified live (all 10
  schedules + tags confirmed correct via raw GMP XML and `gvmd`'s own
  event log). Real bugs found and fixed along the way: `openbao_write.py`'s
  one-line-per-field stdin protocol would have silently truncated
  multi-line SSH keys (fixed via base64); the original ~36-stack scope
  estimate (from `terraform/lxc/environments/pve/`) turned out unreliable
  and missed 6 real running stacks, found via a live Proxmox API call and
  added; `delegate_to: localhost` OpenBao-read tasks inheriting play-level
  `become: true` stripped `LAB_IP_OPENBAO` via `sudo` (fixed with
  `become: false`); python-gvm has no elevate-credential parameter on
  `create_target`/`modify_target` in any version (worked around by
  hand-building the GMP XML element); an unrelated pre-existing regex bug
  in `gaming-stack-lab`'s Wings DNS-fix task blocked its redeploy (fixed).
- **Phase 2 (Wazuh)**: `waz-01` (agent_groups) and `waz-02` (fleet rollout)
  both written, deployed, and verified live 2026-09-30. All 25 in-scope
  stacks now have a real, active Wazuh agent, individually-verified
  `wazuh_agent_fim_paths` (not a copied default), and the correct
  `wazuh_agent_group` matching each stack's actual `stack.yaml` zone --
  confirmed via `GET /agents?select=name,group,status`, every agent
  `status=active` with the right group. Root cause of the original
  `ai-services-stack` timeout: not zone-specific at all -- every
  already-registered agent (the entire original 8-stack pilot) was still
  in the `default` group, because none of them had ever actually executed
  the group-assignment API call added to the role after their original
  enrollment. Two real, independent bugs found and fixed (see
  `fix/wazuh-mikrotik-fleet-api-access`): (1) MikroTik had never opened
  port 55000 (the manager API) from any zone -- fixed with 14 new
  narrowly-scoped rules, one set per zone; (2) `agent-auth`'s `-G` flag
  only applies group membership at first enrollment, so an
  already-connected agent's redeploy silently never applies a group
  change -- fixed with an explicit `PUT /agents/{id}/group/{id}` call
  after enrollment either way.
- **Phase 3 (Graylog log forwarding)**: `log-01` (docker_base daemon.json
  ownership) and `log-02` (migrating the two actually-in-scope non-compliant
  stacks, `ai-services-stack` and `mcp-utility-stack`) both written and
  already live -- confirmed 2026-09-30 (`ai-services-stack`'s
  `/etc/docker/daemon.json` shows the correct `syslog` driver, RFC5424,
  `tcp://127.0.0.1:10514`). This took effect during Track A's own
  redeploys of those two stacks, since `docker_base_manage_daemon_json`
  isn't gated by the Wazuh skip-tag -- an earlier revision of this doc
  said Phase 3 was undeployed, which was stale by the time Track A's
  redeploys actually ran; corrected here.

**Not yet done:** `log-03` (a verification-only pass across the other
~23 already-`syslog` stacks, no code change); confirming last night's
first unattended per-zone GVM scan run actually completed cleanly for
all 10 zones (see `gvm-08`'s own status above).

## Problem statement

Two related gaps, found while triaging UVM stack-risk data:

1. **GVM/Greenbone's credentialed (LSC) scanning is not "properly" done.**
   `terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py`
   reuses the operator's own **root** admin SSH key (`usk` credential type)
   against a hand-picked list of 12 Debian hosts + `pve` — there is no
   dedicated scan account, no privilege-escalation credential, and no
   Ansible-managed distribution mechanism. Its own module docstring
   (lines 1-11) calls this "a pragmatic first pass." Credentialed scanning
   has never been extended past that 12-host list to the rest of the fleet.
2. **Wazuh agent + Graylog log forwarding are not on every LXC.** Wazuh's
   agent role/enrollment mechanism is fleet-ready as written, but only 8 of
   ~36 real production stacks on `pve` currently include it. Host-level
   syslog forwarding (`rsyslog_forward` via `lxc_base`) is already
   universal, but Docker *container* log forwarding to Graylog is
   inconsistent per-stack — a full, already-reviewed migration plan for
   this exists (`docs/logging/docker-log-driver-audit.md`) but was never
   applied.

## Design decisions (operator-confirmed 2026-09-29)

- **Scope**: the ~36 real production stacks currently deployed on `pve`
  (per `terraform/lxc/environments/pve/`). Explicitly **excluded**: the 9
  `net-*` disposable network-test fixtures, `harness-target`/
  `harness-target-pve` (deliberately vulnerable red-team targets — a
  root-capable scan account and a monitored agent would both change their
  intended threat model), and the `cse-*` CyberSecEval harness stacks (a
  distinct eval harness, not a normal workload). Test-* generic fixtures
  (`test-docker`, `test-lxc`, `test-storage*`, `dhcp-test-client-01`,
  `docker-socket-proxy-test`) are likewise out of scope — not real,
  standing production services.
- **GVM scan identity: unique SSH keypair + unique sudo password per LXC**,
  not one shared identity. Real blast-radius containment: a leaked
  credential only ever grants root on the one host it belongs to. Accepted
  cost: ~36 separate OpenBao entries to generate and manage, and a new
  per-stack (not per-profile) OpenBao read path (Design decision below;
  every other secret in this repo is read via one flat per-*profile*
  env-var export, which doesn't fit "36 different values under one
  profile").
- **Sudo scope: full sudo, password-gated** (not a restricted command
  allowlist). Matches Greenbone's own documented guidance for Local
  Security Checks — the NVT catalog needs broad system-wide read access,
  and a fixed allowlist would need constant maintenance as the feed
  evolves, silently breaking scan coverage instead of failing loudly.
- **Wazuh `agent_groups`: yes, introduce now**, grouped by each stack's
  existing `zone:` field in `stack.yaml` (e.g. `infra_seg`, `ai_seg`,
  `mgmt_seg`) — a real field that already exists on every stack, so no new
  per-stack data entry is needed.
- **Docker container log forwarding: adopt `docker-log-driver-audit.md`'s
  existing, already-reviewed design wholesale** (`docker_base` becomes the
  owner of `/etc/docker/daemon.json`, opt-in flag, syslog default) rather
  than inventing a second mechanism. It was designed, not applied — this
  plan is what applies it, scoped to the fleet defined above.

## A gap I could not close myself

`secrets/manifest.json` needs new entries for the per-stack GVM scan
credentials (Phase 1, step `gsa-03` below). **This session's own permission
settings deny me any access — Read or Bash — to anything under `secrets/`**,
even though the file holds only field *names*, never values. I could not
inspect its current exact syntax or edit it. `gsa-03` is written as prose,
not a step block, for a session/operator with that access; every other step
that depends on it names the manifest keys it needs verbatim.

## Phase 1 — GVM credentialed scanning redesign

### Mechanism

Per-stack secrets don't fit this repo's existing OpenBao read pattern
(`./with-secrets*` exports one flat env-var set per *environment profile*
— `pve`, `pve-tiny`, etc. — not per individual host within a profile).
Rather than restructure that shared, widely-used loader, this phase adds a
**small, separate, single-purpose script** that does its own OpenBao read
for one named stack, reusing `scripts/secrets_env.py`'s already-proven
`OpenBaoClient`/`login()` code (same AppRole/env-var conventions, same
read-only `deploy-<node>` role) rather than duplicating it. Blast radius of
the new tooling is isolated to this one script; nothing about the existing
`with-secrets` mechanism changes.

Credential generation is a **separate, one-time, operator-run bootstrap**
(`gsa-02`) — OpenBao writes require a human OIDC login
(`docs/reference/secrets-management.md`), so the loop over ~36 hosts runs
inside the operator's own authenticated shell session, once.

### gvm-01-scan-account-role

```yaml
id: gvm-01-scan-account-role
title: Create the gvm_scan_account Ansible role (dedicated user + sudo + authorized_keys)
depends_on: []

change: >
  Create a new role at terraform/lxc/ansible/roles/gvm_scan_account/ with
  tasks/main.yml and defaults/main.yml. tasks/main.yml must: (1) create a
  system user named "gvm-scan" (ansible.builtin.user, shell /bin/bash,
  create_home: false); (2) write its public key to
  ~gvm-scan/.ssh/authorized_keys (ansible.posix.authorized_key, exclusive:
  true) from a variable gvm_scan_account_public_key (no default -- must be
  supplied by the caller, fails closed if empty via an
  ansible.builtin.assert task before the user-creation task); (3) set the
  account's password from a variable gvm_scan_account_sudo_password_hash
  (ansible.builtin.user's password: parameter, expects a pre-hashed value)
  so `sudo` prompts for and accepts that password; (4) write
  /etc/sudoers.d/gvm-scan with content "gvm-scan ALL=(ALL) ALL" via
  ansible.builtin.copy (mode 0440, validate: "visudo -cf %s"). defaults/main.yml
  sets gvm_scan_account_public_key: "" and
  gvm_scan_account_sudo_password_hash: "" with a comment explaining both
  are intentionally supplied by the including playbook (from
  gvm_scan_host_secret.py's output, see gvm-02), never given a real default,
  matching known_production_images.json's "never guessed" philosophy for
  security-relevant values.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/gvm_scan_account/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Including this role from any playbook -- that's gvm-05"

gates:
  - id: syntax-check
    cmd: "printf '%s\n' '- hosts: all' '  gather_facts: false' '  roles: [gvm_scan_account]' > /tmp/syntax-check-gvm-scan-account.yml && ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check /tmp/syntax-check-gvm-scan-account.yml"
    expect: "exit 0 -- CORRECTED 2026-09-29: a bare tasks/main.yml is NOT a valid standalone play list (ansible-playbook --syntax-check errors 'ansible.builtin.assert is not a valid attribute for a Play' when pointed at it directly) -- verified live, must wrap the role in a throwaway play like this instead"
    critical: true
  - id: sudoers-content-exact
    cmd: "grep -q 'gvm-scan ALL=(ALL) ALL' terraform/lxc/ansible/roles/gvm_scan_account/tasks/main.yml"
    expect: "exit 0"
    critical: true
```

### gvm-02-host-secret-reader

```yaml
id: gvm-02-host-secret-reader
title: Add scripts/gvm_scan_host_secret.py to read one stack's GVM scan credentials from OpenBao
depends_on: []

change: >
  Create scripts/gvm_scan_host_secret.py. It imports OpenBaoClient,
  SecretsError, login, load_manifest, DEFAULT_MANIFEST, DEFAULT_CACERT from
  scripts/secrets_env.py (same directory, sys.path insert of this file's
  own parent). Argparse takes --stack (required) and --profile (default
  from env PVE_ENV, fallback "pve"). It builds the OpenBao address from
  env OPENBAO_ADDR or https://$LAB_IP_OPENBAO:8200, cacert from env
  OPENBAO_CACERT or DEFAULT_CACERT, cred_dir from env OPENBAO_CRED_DIR or
  ~/.config/openbao. It logs in via the named profile's AppRole (reusing
  login()), reads KV entry "services/greenbone/scan-hosts/<stack>", prints
  the resulting dict as one line of JSON to stdout, calls
  client.revoke_self() in a finally block, and returns 0. On any
  SecretsError it prints "ERROR: <message>" to stderr and returns 1
  without printing anything to stdout (so a caller can safely assume any
  stdout output is valid JSON). Add a module docstring naming the exact
  entry path and the three expected fields: GVM_SCAN_SSH_PRIVATE_KEY,
  GVM_SCAN_SSH_PUBLIC_KEY, GVM_SCAN_SUDO_PASSWORD.

scope:
  allowed_paths:
    - scripts/gvm_scan_host_secret.py
  forbidden_actions:
    - "Any change to scripts/secrets_env.py itself"
    - "Any network call -- this step only writes the file"

gates:
  - id: syntax-check
    cmd: "python3 -m py_compile scripts/gvm_scan_host_secret.py"
    expect: "exit 0"
    critical: true
  - id: no-secrets-env-modified
    cmd: "git diff --name-only | grep -qx 'scripts/secrets_env.py' && echo BAD || echo OK"
    expect: "OK"
    critical: true
```

### gvm-03-manifest-entries (prose — needs `secrets/` access this session doesn't have)

Add one manifest entry per in-scope stack under path
`services/greenbone/scan-hosts/<stack-name>`, each listing fields
`GVM_SCAN_SSH_PRIVATE_KEY`, `GVM_SCAN_SSH_PUBLIC_KEY`,
`GVM_SCAN_SUDO_PASSWORD`. These entries are deliberately **not** added to
any environment `profile`'s entry list — `gvm_scan_host_secret.py` reads
them directly by name via `--stack`, bypassing the profile/env-var export
path entirely, so they should never appear in a flat `with-secrets` env
dump. Whoever applies this: confirm `secrets/manifest.json`'s exact current
schema first (this plan was written without being able to read it) and
match its real field-declaration shape, not the shape assumed here.

### gvm-04-credential-bootstrap-script

```yaml
id: gvm-04-credential-bootstrap-script
title: Add scripts/gvm_scan_credentials_bootstrap.py (operator-run, one-time generation)
depends_on: [gvm-02-host-secret-reader]

change: >
  Create scripts/gvm_scan_credentials_bootstrap.py. It takes one or more
  stack names as positional argv (or --all-pve-stacks to glob
  terraform/lxc/environments/pve/*/ directory names, excluding the
  exclusions named in this plan's Design decisions section -- hardcode
  that exact exclusion list: net-app-01, net-artifacts-01, net-build-01,
  net-client-01, net-client-02, net-isolated-01, net-service-01,
  net-service-02, net-svc-01, harness-target, harness-target-pve, cse-kali,
  cse-code-eval, cse-controller, cse-panel-stack, test-docker, test-lxc,
  test-storage, test-storage-extra, dhcp-test-client-01,
  docker-socket-proxy-test). For each stack: generate an ed25519 keypair
  via `ssh-keygen -t ed25519 -N "" -C "gvm-scan@<stack>" -f <mkstemp path>`
  (subprocess, then read both halves, then delete the temp files); generate
  a 32-char urlsafe sudo password via secrets.token_urlsafe(24); hash the
  password with `crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))`
  for the value that will become gvm_scan_account_sudo_password_hash later
  (gvm-05); then invoke `scripts/openbao_write.py
  services/greenbone/scan-hosts/<stack> GVM_SCAN_SSH_PRIVATE_KEY
  GVM_SCAN_SSH_PUBLIC_KEY GVM_SCAN_SUDO_PASSWORD` as a subprocess, piping
  the three raw values (private key, public key, plaintext password -- not
  the hash; gvm_scan_host_secret.py's caller hashes it at apply time so
  GVM's own GMP credential, which needs the plaintext for its "up"
  privilege-escalation credential, still has it) one per line to its
  stdin, inheriting BAO_TOKEN/LAB_IP_OPENBAO from the environment (never
  reads or stores them itself). Print a per-stack progress line and a
  final summary (N succeeded, N failed). Module docstring states plainly:
  requires BAO_TOKEN already exported from a completed `bao login
  -method=oidc -no-store` (this script never logs in itself), and is
  meant to be run once per stack, not on every provisioning pass --
  running it twice for the same stack rotates that stack's credentials
  (openbao_write.py always writes a fresh KV version), so callers should
  only pass stacks that don't already have an entry yet.

scope:
  allowed_paths:
    - scripts/gvm_scan_credentials_bootstrap.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Actually running this script -- BAO_TOKEN/OIDC login is operator-only, out of scope for this step"

gates:
  - id: syntax-check
    cmd: "python3 -m py_compile scripts/gvm_scan_credentials_bootstrap.py"
    expect: "exit 0"
    critical: true
  - id: exclusion-list-present
    cmd: "grep -c 'harness-target' scripts/gvm_scan_credentials_bootstrap.py"
    expect: "at least 1"
    critical: true
```

**Then, prose (operator-only, needs `bao login -method=oidc -no-store` +
`export BAO_TOKEN=...`):** run
`scripts/gvm_scan_credentials_bootstrap.py --all-pve-stacks` once. This
populates all ~36 OpenBao entries in one authenticated session.

### gvm-05-include-role-and-generate-hash

```yaml
id: gvm-05-include-role-and-generate-hash
title: Wire gvm_scan_account into one exemplar playbook (harbor-stack) as the pattern for the fleet rollout
depends_on: [gvm-01-scan-account-role, gvm-02-host-secret-reader]

change: >
  In terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml, add a new
  play (same shape as the existing "Enroll this host as a Wazuh agent"
  play at the file's end): hosts: all, become: true, gather_facts: false,
  with a pre_tasks block that runs
  "python3 {{ playbook_dir }}/../../../../scripts/gvm_scan_host_secret.py
  --stack harbor-stack" via ansible.builtin.command, delegate_to:
  localhost, register: gvm_scan_secret_raw, then
  set_fact: gvm_scan_secret: "{{ gvm_scan_secret_raw.stdout | from_json }}",
  then a vars block setting
  gvm_scan_account_public_key: "{{ gvm_scan_secret.GVM_SCAN_SSH_PUBLIC_KEY }}"
  and
  gvm_scan_account_sudo_password_hash: "{{ gvm_scan_secret.GVM_SCAN_SUDO_PASSWORD | password_hash('sha512') }}",
  then roles: [gvm_scan_account]. Use the correct relative path from this
  specific playbook's location to scripts/ (verify at execution time --
  do not guess the ../ count without checking).

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
  forbidden_actions:
    - "Any change to any other playbook -- that's gvm-06"
    - "Running this playbook against production -- validation (syntax-check) only in this step"

gates:
  - id: syntax-check
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml"
    expect: "exit 0"
    critical: true
```

### gvm-06-fleet-rollout (bounded, not per-stack step blocks)

Apply the exact same play block from `gvm-05` (with the stack name
substituted in both the `--stack` argument and the `-C` comment it reads
from) to every other in-scope stack's `deploy-*.yml` playbook. Derive the
current list at execution time, don't trust this plan's own count:

```bash
comm -23 \
  <(ls terraform/lxc/environments/pve/ | sort) \
  <(grep -l gvm_scan_account terraform/lxc/ansible/playbooks/deploy-*.yml | \
    sed -E 's#.*/deploy-(.*)\.yml#\1#' | sort)
```

(minus this plan's own exclusion list). Each stack gets its own commit or
all land in one commit — operator's call, matches this repo's normal
Ansible-role-change validation tier either way (`scripts/provision.sh
--stack <name>` per stack, under the production approval flow).

### gvm-07-setup-credentials-privilege-escalation

```yaml
id: gvm-07-setup-credentials-privilege-escalation
title: Extend setup_credentials.py to also create a "sudo" elevate-privileges credential per target
depends_on: []

change: >
  In terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py,
  extend ensure_credential() (or add a second function
  ensure_privilege_escalation_credential(gmp, name, sudo_password)) to
  also call gmp.create_credential with credential_type="up" (username +
  password), login="gvm-scan", password=sudo_password, for each of the
  ~36 fleet targets. Extend the TARGETS list/dict structure (currently
  lines 62-101) so each new fleet entry carries both its usk login
  credential (login="gvm-scan", private_key from the per-stack OpenBao
  read) and its up elevate-privileges credential (same login, sudo
  password from the same read). When creating or updating the GMP Target
  object for each host, set its ssh_elevate_credential_id to the "up"
  credential's id (gmp.modify_target or the equivalent create_target
  kwarg -- check python-gvm's current Target API for the exact
  parameter name before writing this, it varies by python-gvm version).
  Read each stack's two secrets via a subprocess call to
  scripts/gvm_scan_host_secret.py --stack <name> (same mechanism gvm-05's
  Ansible tasks use), not a new OpenBao client.

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py
  forbidden_actions:
    - "Any change to the existing 12-host manual-admin-key TARGETS entries (lab-root, workstation-openvas, raspberry-pi-ansible, mikrotik-gvm-scan) -- those stay as they are, this only adds the new fleet entries alongside them"
    - "Running this program against the live GVM instance -- that's a separate, explicitly-approved production step, not part of writing the code"

gates:
  - id: syntax-check
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py"
    expect: "exit 0"
    critical: true
```

### gvm-08-vlan-scheduling (deployed 2026-09-29, prose — implemented after gvm-07, not part of the original operator answers)

Operator asked, after Track A's initial deploy, for the fleet scans to be
"divided up by vlan". Checked against upstream python-gvm source directly
before writing anything: `create_target`/`modify_target` accept exactly
one `ssh_credential_id` for every host in a Target, in every shipped GMP
version (v224 through v227/next) — there is no per-host credential within
a multi-host Target. That's incompatible with the per-host-unique-
credential design this whole plan is built around, so a literal
one-shared-Target-per-zone isn't achievable without abandoning blast-radius
containment. Confirmed this reading with the operator via AskUserQuestion
before implementing.

Implemented as: the 25 existing per-host Targets/Tasks are unchanged, each
keeps its own credential. Added one GVM **Schedule** per network zone
(`ZONE_SCHEDULE_TIMES` in `setup_credentials.py` — daily, staggered ~45min
apart starting 01:00 UTC across the 10 in-scope zones, operator-confirmed
cadence and window) and one **Tag** per zone (`zone:<name>`) attached to
every task in that zone. `gvm_fleet_targets_generate.py` now also resolves
each stack's `zone:` from its `stack.yaml` (handles both the plain and
nested `network: { zone: }` forms) and includes it in `targets.json`.
`ensure_task()` passes `schedule_id` into `create_task`/`modify_task`
(a real, directly-supported parameter in this GMP version — unlike the
elevate-credential case above, no hand-built XML was needed). Schedule
iCalendar text is hand-built (`BEGIN:VCALENDAR`/`VEVENT` with
`DTSTART`+`RRULE:FREQ=DAILY`) rather than depending on the `icalendar`
PyPI package, which isn't a guaranteed dependency of the upstream
`gvm-tools` image this runs inside.

Deployed and verified live: all 10 schedules created at the right times,
all 25 tasks confirmed wired to their zone's schedule (`modify_task` on
each pre-existing task), all 10 tags created with the correct per-zone host
counts, and `gvmd`'s own event log shows real `Schedule ... has been
created by admin` entries for all 10 — not silently rejected.

**Correction, 2026-09-30 (`fix/gvm-schedule-nzt-timezone`):** the initial
version used `SCHEDULE_TIMEZONE="UTC"`, which put these "overnight" times
at 14:00–20:45 in the operator's actual timezone (NZT) — their afternoon/
evening, not overnight. Only one host (`nextcloud-stack`/`apps_seg`) had
actually fired by the next day, purely by coincidence of its zone's
time-of-day landing after the original deploy time on the same calendar
day — it succeeded (1000 results, real credentialed LSC checks, 0
high-severity findings), but the other 24 hosts hadn't run at all, which
is what surfaced the timezone bug on inspection. Fixed by switching
`SCHEDULE_TIMEZONE` to the real IANA zone name `Pacific/Auckland` instead
of a fixed offset, so it resolves NZ's DST transitions correctly forever
rather than drifting wrong twice a year. `ensure_schedule()` now calls
`gmp.modify_schedule()` to re-apply the `icalendar`/`timezone` even when a
schedule of that name already exists, not just on first creation — needed
so the fix actually corrected the 10 already-created UTC schedules in
place, not only future ones. Verified live: `gvmd` expands the corrected
schedule into a full DST-aware `VTIMEZONE` block with real NZDT/NZST
transition rules (raw GMP XML), and all 25 tasks/10 tags re-confirmed
wired. First real overnight run under the corrected schedule: `mgmt_seg`
at 01:00 NZT.

## Phase 2 — Wazuh agent fleet rollout + groups

### waz-01-agent-groups-support

```yaml
id: waz-01-agent-groups-support
title: Add agent_groups support to the wazuh_agent role
depends_on: []

change: >
  In terraform/lxc/ansible/roles/wazuh_agent/defaults/main.yml, replace
  the existing comment block at lines 11-17 (the one explaining why
  agent_groups isn't supported yet) with a new default
  wazuh_agent_group: "" (singular -- one zone group per host, not a list;
  comment: derive this from the including playbook's own stack.yaml zone
  field, e.g. wazuh_agent_group: "{{ lookup('file',
  playbook_dir+'/../stacks/'+stack_name+'/stack.yaml') | ... }}" is NOT
  required here -- the including playbook just passes its own zone value
  literally, same as it already passes wazuh_agent_fim_paths). In
  tasks/main.yml, before the existing "Enroll this agent" task (currently
  starting at line 230), add a new task "Ensure this host's Wazuh agent
  group exists on the manager" using ansible.builtin.uri against the
  Wazuh API (https://{{ wazuh_agent_manager_ip }}:55000/groups, GET to
  check, PUT /groups/{{ wazuh_agent_group }} to create if absent, 401
  handled by first POSTing /security/user/authenticate for a token) --
  skip this whole task with `when: wazuh_agent_group | length > 0`. Then
  extend the existing "Enroll this agent with the manager via
  wazuh-authd" command's argv list to append ["-G", "{{
  wazuh_agent_group }}"] only when wazuh_agent_group is non-empty (use a
  Jinja conditional list-concatenation, not a second near-duplicate task).
  Check the actual Wazuh API auth flow (JWT token via
  /security/user/authenticate, Bearer header on subsequent calls) against
  the Wazuh version this manager runs before writing the exact request
  shape -- do not assume a specific version's API without checking
  wazuh-stack's own docs/wazuh-stack/ for the pinned version.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/wazuh_agent/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Including wazuh_agent from any new playbook -- that's waz-03"

gates:
  - id: syntax-check
    cmd: "printf '%s\n' '- hosts: all' '  gather_facts: false' '  roles: [wazuh_agent]' > /tmp/syntax-check-wazuh-agent.yml && ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check /tmp/syntax-check-wazuh-agent.yml"
    expect: "exit 0 -- a bare tasks/main.yml is not a valid standalone play list, must wrap the role (see gvm-01's corrected gate for why)"
    critical: true
  - id: conditional-flag-present
    cmd: "grep -c '\\-G' terraform/lxc/ansible/roles/wazuh_agent/tasks/main.yml"
    expect: "at least 1"
    critical: true
```

### waz-02-fleet-rollout (bounded, not per-stack step blocks)

For every in-scope stack whose `deploy-*.yml` does **not** already include
`wazuh_agent` (confirm the current gap list at execution time, don't trust
this plan's count — the 2026-09-29 research pass found 8 done:
authentik-stack, nextcloud-stack, harbor-stack, technitium-tiny-stack,
newt-connector, proxy-stack, apt-cacher-stack, technitium-stack; re-check
live with
`comm -23 <(ls terraform/lxc/environments/pve/|sort) <(grep -l wazuh_agent terraform/lxc/ansible/playbooks/deploy-*.yml | sed -E 's#.*/deploy-(.*)\.yml#\1#' | sort)`,
minus this plan's exclusion list), add the same play block already used by
the 8 done stacks (`hosts: all, become: true, gather_facts: false, vars:
{wazuh_agent_fim_paths: [...stack-appropriate paths...], wazuh_agent_group:
"<that stack's zone from stack.yaml>"}, roles: [wazuh_agent]`), reading
each stack's own `wazuh_agent_fim_paths` value from what its Compose
file/app config actually needs watching (do not copy another stack's paths
verbatim — this varies per stack, same judgment the 8 existing inclusions
already made per-stack).

## Phase 3 — Docker container log forwarding to Graylog

### log-01-apply-daemon-json-ownership

```yaml
id: log-01-apply-daemon-json-ownership
title: Apply docker-log-driver-audit.md's proposed docker_base defaults diff verbatim
depends_on: []

change: >
  Apply the exact diff already written in
  docs/logging/docker-log-driver-audit.md's "Proposed diff:
  roles/docker_base/defaults/main.yml (NOT APPLIED)" section to
  terraform/lxc/ansible/roles/docker_base/defaults/main.yml, then also
  implement the corresponding tasks/main.yml changes that diff implies
  (a templated /etc/docker/daemon.json write, gated on
  docker_base_manage_daemon_json, merging docker_base_daemon_extra via
  combine, registering docker_base_daemon_json for restart-handler use) --
  the audit doc's §4 write-up describes this task shape in prose even
  though it only shows the defaults/ diff verbatim; follow that
  description exactly, do not invent a different task structure. Update
  docs/logging/docker-log-driver-audit.md's own header to note this design
  is now applied, with today's date and a pointer to this plan.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/docker_base/
    - docs/logging/docker-log-driver-audit.md
  forbidden_actions:
    - "Setting docker_base_manage_daemon_json: true on any actual stack -- that's log-02, done one stack at a time"
    - "Deleting any stack's own hand-written daemon.json task -- that's log-02, must happen in the SAME commit as that stack's flag flip per the audit's own §2 warning about flapping"

gates:
  - id: syntax-check
    cmd: "printf '%s\n' '- hosts: all' '  gather_facts: false' '  roles: [docker_base]' > /tmp/syntax-check-docker-base.yml && ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check /tmp/syntax-check-docker-base.yml"
    expect: "exit 0 -- a bare tasks/main.yml is not a valid standalone play list, must wrap the role (see gvm-01's corrected gate for why)"
    critical: true
  - id: default-still-off
    cmd: "grep -q 'docker_base_manage_daemon_json: false' terraform/lxc/ansible/roles/docker_base/defaults/main.yml"
    expect: "exit 0 (merging this must be a no-op fleet-wide until stacks opt in)"
    critical: true
```

### log-02-migrate-noncompliant-stacks (bounded, follows the audit's own list + order)

For each stack `docker-log-driver-audit.md` §2b/2c names as non-compliant
(json-file-not-reaching-Graylog: `ai-services-stack`, `mcp-utility-stack`,
`pentagi-stack`\*, `pentagi-upstream-control`\*,
`pentagi-upstream-vanilla-companion`\*; no-daemon.json-at-all:
`cse-kali`\*, `docker-socket-proxy-test`\*, `harness-target`\*,
`harness-target-pve`\*) — **cross-reference against this plan's own scope
exclusion list first**: everything marked \* above is already out of
scope per this plan's Design decisions (pentagi is deprecated/being
decommissioned per memory, cse-\*/harness-target/docker-socket-proxy-test
are explicitly excluded). That leaves only `ai-services-stack` and
`mcp-utility-stack` as real, in-scope migrations for this plan. For each:
set `docker_base_manage_daemon_json: true`, move that stack's existing
non-logging daemon.json keys (if any) into `docker_base_daemon_extra`,
delete its own hand-written daemon.json task in the same commit (per the
audit's own flap-prevention warning), and confirm via the audit's §5
verification approach (re-check with a live `docker inspect` on one
container post-redeploy that the log driver actually changed).

### log-03-fleet-verification (bounded)

For every other in-scope stack (already on `syslog` per the audit's own
count of 23 compliant playbooks — re-verify the current list at execution
time rather than trusting a stale count), no code change is needed; this
step is a verification pass only: confirm each stack's `daemon.json` (or
its `docker_base_manage_daemon_json` state, once `log-01`/`log-02` land)
still routes to `127.0.0.1:10514`, and record any stack found to have
silently drifted since the audit was written 2026-09-27.

## Validation

Every Ansible role/task change in this plan (`gvm-01`, `waz-01`, `log-01`)
is an "Ansible task or role change" per this repo's Validation Tiers table
— `scripts/provision.sh --stack <affected-stack>` directly on `pve`, under
the production approval flow, no `pve-test-vm` detour needed. The fleet
rollout steps (`gvm-06`, `waz-02`, `log-02`) are the same tier repeated per
stack; batch related ones per the repo's own "batch related changes, run
the appropriate tier once" guidance rather than one approval per host.

`gvm-04`'s bootstrap script run and `gvm-03`'s manifest edit are the only
genuinely operator-only actions in this plan (OIDC login; `secrets/`
access this session lacks) — everything else is ordinary local-model-executable
step-packet work.

## Open items / not decided yet

- ~~The exact Wazuh API version/auth shape for `waz-01`'s group-creation
  task~~ — superseded: `waz-01`'s group-creation call has not actually
  been exercised live yet (Track B redeploy deferred), so this remains
  genuinely unverified, but the more concrete open item now is below.
- ~~`gvm-07`'s exact python-gvm API call for setting a Target's elevate
  ssh credential~~ — RESOLVED 2026-09-29: confirmed live, no version of
  python-gvm supports it at all; fixed via a hand-built GMP XML element.
  See `gvm-07`'s step section above.
- ~~Whether GVM's own credentialed-scan schedule/task objects need
  updating to actually *use* the new fleet-wide Target list~~ — RESOLVED
  2026-09-29 as `gvm-08` (see above): per-zone Schedule + Tag, deployed
  and verified live.
- **New, real, not yet understood**: `ai-services-stack`'s Wazuh
  enrollment hit an API timeout connecting to the Wazuh manager (port
  55000, `ai_seg` → `infra_seg` zone crossing) during the Track A fleet
  rollout. Not diagnosed — Track B redeploy was deferred entirely rather
  than debugged inline, per the operator's explicit scope call at the
  time. Needs investigation before Track B's redeploy: firewall rule gap
  between those two zones on that port, a manager-side issue, or
  something else. Whoever picks up Track B should start here, not assume
  it's the same "unverified against a live manager" risk this plan
  originally flagged for `waz-01`'s group-creation logic (that code never
  actually ran far enough to hit that risk — it failed earlier, at the
  initial authentication call).
