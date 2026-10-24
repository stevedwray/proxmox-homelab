# alerting plan

Workspace README (decisions, design rules, hand-backs): [README.md](README.md).
Replaces `docs/catch-up/07-baseline-alerting.md`, whose OpenBao-health and
alert-rule steps are reused below by id.

## Status (2026-10-24)

**Phases 1, 1c and both prerequisites are deployed and proven** (drills and a real page: README, *Proven live*).
The work was merged to `stable` from `work/graylog-sender-ip-pentest-stream`. Phase 0 enrolment, Phase 2, 5 and 6
are still to do. Phases 3, 4 and 4b are future state.

| Phase | What | State |
|---|---|---|
| 0.1, 0.3 | Graylog stamps the real sender IP; `pentest_seg` has its own stream; two MikroTik rules narrowed | **Live** |
| 0.4, 0.5 | Workstation and argon-01/02 into Graylog | **Done and proven 2026-10-24** (`graylog-workstation-syslog-ng.yml`, `graylog-pi-syslog.yml`) |
| 0.6, 0.8 | MikroTik metrics (mktxp), NAS | Outline / waiting on the operator (Asustor log settings and SNMP) |
| 1 | Discord channels, 9 baseline + 18 hardware rules, routing | **Live and proven** |
| 1c | Telegram paging via Grafana, honeypot tripwire, 10-minute T-Pot sync, short plain-text messages | **Live and proven** |
| prereq | OpenBao seal-status metric | **Live** (`openbao_sealed` = 0) |
| prereq | node_exporter fleet repair | **Done** 2026-10-24 |
| 2 | Graylog log alerts | **Applied and drilled** (`scripts/graylog_alerts.py`) |
| 3, 4, 4b | OCI relay with buttons, dead man's switch, blackbox checks | **Future state.** The relay is built and tested but parked, not deployed |
| 5 | New critical vulnerabilities (Harbor, Greenbone) | **Built, not yet deployed** (`homelab-vulnerabilities.yml`) |
| 6 | Digest, fire drill, native integrations | Outline |

**Order from here:** the Phase 0 enrolment steps, then Phase 2 (Graylog log alerts, so the pve-tiny drive failure
would have paged from logs alone), then 5 and 6. Phases 3, 4 and 4b wait for a decision. Operator housekeeping
(NVMe silence, Discord token reset) is in the README's open items. **Parallel work:** the pve-tiny evacuation
(`work/pve-tiny-evacuation`) moves stacks off that host; re-check the `stack=pve-tiny` alerts, the NVMe silence and
the secpipe/honeypot sync host as each stack moves.

## How to read this

- Steps are fenced YAML blocks under their own heading, per
  `docs/agent-design/step-packet-schema.md`. A step is local-model work: edit
  files, run its gates, stop. **No step deploys anything.** Steps `03` to `06` were executed
  directly by the planner (their literal content is kept as the record; where a step and the
  repo disagree, **the repo is right**, and Phase 1c says what superseded what).
- Anything that touches a running system is plain prose under an "Operator"
  heading. The operator runs it; production runs go through
  `./with-secrets-prod*` with a named `TASK_APPROVAL`.
- Outlines are on purpose: each depends on facts that only exist after the phase before it
  lands, and its first task is to find them. Do not run an outline.
- **Two traps found for real, both worth a gate:** a literal block shown in a step is 2 spaces
  deeper than it belongs in the file (the `change: |` block adds them), and `syntax-check`
  cannot see inside a `content: |` string. `scripts/check_grafana_provisioning.py` renders and
  parses the inline Grafana files for that reason.
- Branch: `work/graylog-sender-ip-pentest-stream` carried all of this and is merged to `stable`.

## Phase 0: log and metrics coverage

A rule can't fire on logs that never arrive. Phase 0 closes the gaps found by
the 2026-10-24 sweep.

| Item | State |
|---|---|
| 0.1 Relay stamps the real sender IP (`relay_src_ip`) | **Done**, live |
| 0.3 `pentest_seg` in its own stream; MikroTik 514/443 rules narrowed | **Done**, live |
| 0.2 T-Pot relabel | **Dropped**: its source is already the generic `raspberrypi` and its own logs never say "tpot" |
| 0.4 Workstation `garuda` into Graylog, warning and above | **Done and proven 2026-10-24**: `ansible/00-initial-setup/graylog-workstation-syslog-ng.yml` (syslog-ng from the official repo; rsyslog was the operator's first choice but chaotic-aur's build crashes on glibc 2.44). Steps 00 and 01 below are **superseded** |
| 0.5 argon-01 / argon-02 into Graylog | **Done and proven 2026-10-24**: `ansible/00-initial-setup/graylog-pi-syslog.yml` (step 02's content, as committed) |
| 0.6 MikroTik hardware and firmware metrics (mktxp) | Outline, Phase 0b below |
| 0.7 Omada metrics missing from VictoriaMetrics | Closed by the monitoring-stack deploy (Phase 1c checklist) |
| 0.8 NAS (Asustor Drivestor) | Operator, below |
| 0.9 Ignore the expected `GazaarBackup` failure | Phase 2 (Graylog event definitions) |

### alerting-00-journal-forwarder

> **SUPERSEDED 2026-10-24.** The operator wanted a standard daemon for the workstation, not a script, so this script and `alerting-01`
> were never written. rsyslog was tried first and cannot run on this Arch install (chaotic-aur's libfastjson crashes against glibc 2.44),
> so the workstation uses syslog-ng from the official repo: see `graylog-workstation-syslog-ng.yml`.

```yaml
id: alerting-00-journal-forwarder
title: Add the journald-to-Graylog forwarder script and its unit test
depends_on: []

change: |
  Create two files with exactly this LITERAL content.

  File 1: ansible/00-initial-setup/files/journal_to_graylog.py

  #!/usr/bin/env python3
  """Forward warning-and-above journald entries to Graylog as RFC 5424 over TCP.

  Runs as a systemd service on the operator workstation (Arch/Garuda has no
  rsyslog in its main repos). It follows `journalctl -o json`, keeps its place
  in a cursor file so a restart or a Graylog outage loses nothing, and sends to
  the graylog-stack relay (tcp/514), which stamps the real sender IP.

  Environment:
    GRAYLOG_HOST       relay address (required)
    GRAYLOG_PORT       default 514
    MAX_PRIORITY       highest syslog severity number to forward, default 4
                       (0 emerg ... 4 warning, 7 debug)
    CURSOR_FILE        default /var/lib/graylog-journal-forward/cursor
  """
  from __future__ import annotations

  import datetime
  import json
  import os
  import socket
  import subprocess
  import sys
  import time

  HOSTNAME = socket.gethostname()


  def _text(value) -> str:
      """journald JSON gives binary fields as a list of byte values."""
      if isinstance(value, list):
          return bytes(value).decode("utf-8", "replace")
      return "" if value is None else str(value)


  def format_entry(entry: dict, hostname: str = HOSTNAME) -> str:
      """Return one RFC 5424 line (no trailing newline) for a journald entry."""
      priority = int(entry.get("PRIORITY", 6))
      facility = int(entry.get("SYSLOG_FACILITY", 1))
      micros = int(entry["__REALTIME_TIMESTAMP"])
      stamp = datetime.datetime.fromtimestamp(micros / 1_000_000, datetime.timezone.utc)
      app = _text(entry.get("SYSLOG_IDENTIFIER") or entry.get("_COMM") or "-")
      app = "".join(c if 33 <= ord(c) <= 126 else "_" for c in app)[:48] or "-"
      procid = _text(entry.get("_PID") or "-")
      message = " ".join(_text(entry.get("MESSAGE")).split())
      return (
          f"<{facility * 8 + priority}>1 "
          f"{stamp.strftime('%Y-%m-%dT%H:%M:%S.%f')}Z {hostname} {app} {procid} - - {message}"
      )


  def _connect(host: str, port: int) -> socket.socket:
      delay = 2
      while True:
          try:
              return socket.create_connection((host, port), timeout=15)
          except OSError as exc:
              print(f"graylog connect failed: {exc}; retrying in {delay}s", file=sys.stderr, flush=True)
              time.sleep(delay)
              delay = min(delay * 2, 60)


  def _save_cursor(path: str, cursor: str) -> None:
      tmp = f"{path}.tmp"
      with open(tmp, "w", encoding="utf-8") as fh:
          fh.write(cursor)
      os.replace(tmp, path)


  def main() -> int:
      host = os.environ["GRAYLOG_HOST"]
      port = int(os.environ.get("GRAYLOG_PORT", "514"))
      max_priority = int(os.environ.get("MAX_PRIORITY", "4"))
      cursor_file = os.environ.get("CURSOR_FILE", "/var/lib/graylog-journal-forward/cursor")
      os.makedirs(os.path.dirname(cursor_file), exist_ok=True)

      cmd = ["journalctl", "--follow", "--output=json", f"--priority={max_priority}"]
      try:
          with open(cursor_file, encoding="utf-8") as fh:
              cmd += [f"--after-cursor={fh.read().strip()}", "--lines=all"]
      except FileNotFoundError:
          cmd += ["--lines=0"]

      sock = _connect(host, port)
      with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, bufsize=1) as proc:
          for raw in proc.stdout:
              entry = json.loads(raw)
              line = (format_entry(entry) + "\n").encode("utf-8", "replace")
              while True:
                  try:
                      sock.sendall(line)
                      break
                  except OSError:
                      sock.close()
                      sock = _connect(host, port)
              _save_cursor(cursor_file, entry["__CURSOR"])
      return proc.returncode or 1


  if __name__ == "__main__":
      raise SystemExit(main())

  File 2: ansible/00-initial-setup/files/test_journal_to_graylog.py

  import unittest

  import journal_to_graylog as j


  class FormatEntryTest(unittest.TestCase):
      def test_kernel_error(self):
          entry = {
              "PRIORITY": "3", "SYSLOG_FACILITY": "0", "SYSLOG_IDENTIFIER": "kernel",
              "_PID": "0", "__REALTIME_TIMESTAMP": "1792800000123456",
              "MESSAGE": "nvme0n1: I/O Error\non two lines",
          }
          self.assertEqual(
              j.format_entry(entry, "garuda"),
              "<3>1 2026-10-24T00:00:00.123456Z garuda kernel 0 - - nvme0n1: I/O Error on two lines",
          )

      def test_defaults_and_binary_message(self):
          entry = {
              "__REALTIME_TIMESTAMP": "1792800000000000", "_COMM": "my app",
              "MESSAGE": [104, 105, 255],
          }
          out = j.format_entry(entry, "garuda")
          self.assertTrue(out.startswith("<14>1 2026-10-24T00:00:00.000000Z garuda my_app - - - hi"))

      def test_app_name_truncated(self):
          entry = {"__REALTIME_TIMESTAMP": "1792800000000000", "SYSLOG_IDENTIFIER": "x" * 80, "MESSAGE": "m"}
          self.assertEqual(j.format_entry(entry, "h").split(" ")[3], "x" * 48)


  if __name__ == "__main__":
      unittest.main()

scope:
  allowed_paths:
    - ansible/00-initial-setup/files/journal_to_graylog.py
    - ansible/00-initial-setup/files/test_journal_to_graylog.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the script (it opens a network connection and follows the journal)"

gates:
  - id: unit-tests
    cmd: "cd ansible/00-initial-setup/files && python3 -m unittest test_journal_to_graylog 2>&1 | tail -3"
    expect: "output contains 'Ran 3 tests' and ends with 'OK'"
    critical: true
  - id: compiles
    cmd: "python3 -m py_compile ansible/00-initial-setup/files/journal_to_graylog.py && echo ok"
    expect: "prints ok"
    critical: true
  - id: ruff
    cmd: "ruff check ansible/00-initial-setup/files/"
    expect: "exit 0"
    critical: true
```

### alerting-01-workstation-playbook

> **SUPERSEDED 2026-10-24** by `ansible/00-initial-setup/graylog-workstation-syslog-ng.yml` (see alerting-00).

```yaml
id: alerting-01-workstation-playbook
title: Add the playbook that installs the forwarder as a systemd service on the workstation
depends_on: [alerting-00-journal-forwarder]

change: |
  Create ansible/00-initial-setup/graylog-workstation-forwarder.yml with
  exactly this LITERAL content.

  ---
  # Forward the operator workstation's warning-and-above journald entries to
  # Graylog (docs/alerting/plan.md, Phase 0). Garuda/Arch has no rsyslog in its
  # main repos, so a small systemd service (files/journal_to_graylog.py) follows
  # the journal instead. The graylog-stack relay stamps the real sender IP.
  #
  # The workstation is the machine running this (inventory group `workstation`,
  # connection local). It is a LAN host, so MikroTik's shared Graylog rule
  # already admits it. Run (sudo asks for your password):
  #   ./with-secrets ansible-playbook -i ansible/inventory/inventory.yml \
  #     ansible/00-initial-setup/graylog-workstation-forwarder.yml \
  #     --limit garuda --ask-become-pass
  #
  # Verify: logger -p user.warning 'WORKSTATION_FWD_PROOF' ; then in Graylog
  #   relay_src_ip:192.168.1.104 AND message:WORKSTATION_FWD_PROOF
  # Rollback: systemctl disable --now graylog-journal-forward

  - name: Forward workstation journald warnings to Graylog
    hosts: workstation
    become: true
    gather_facts: false

    vars:
      gwf_graylog_host: "{{ lookup('env', 'LAB_IP_GRAYLOG') | mandatory('LAB_IP_GRAYLOG env var is required') }}"
      # Highest syslog severity number forwarded: 4 = warning and above.
      gwf_max_priority: "4"

    tasks:
      - name: Install the journald forwarder
        ansible.builtin.copy:
          src: "{{ playbook_dir }}/files/journal_to_graylog.py"
          dest: /usr/local/sbin/journal_to_graylog.py
          owner: root
          group: root
          mode: "0755"
        notify: Restart graylog-journal-forward

      - name: Write the forwarder settings (no secrets)
        ansible.builtin.copy:
          dest: /etc/graylog-journal-forward.env
          owner: root
          group: root
          mode: "0644"  # nosonar: ansible:S2612 -- holds only the relay address and a severity number
          content: |
            GRAYLOG_HOST={{ gwf_graylog_host }}
            GRAYLOG_PORT=514
            MAX_PRIORITY={{ gwf_max_priority }}
        notify: Restart graylog-journal-forward

      - name: Write the forwarder service
        ansible.builtin.copy:
          dest: /etc/systemd/system/graylog-journal-forward.service
          owner: root
          group: root
          mode: "0644"  # nosonar: ansible:S2612 -- systemd unit files must be world-readable
          content: |
            [Unit]
            Description=Forward journald warnings to Graylog
            After=network-online.target
            Wants=network-online.target

            [Service]
            EnvironmentFile=/etc/graylog-journal-forward.env
            ExecStart=/usr/bin/python3 /usr/local/sbin/journal_to_graylog.py
            Restart=always
            RestartSec=10
            DynamicUser=yes
            SupplementaryGroups=systemd-journal
            StateDirectory=graylog-journal-forward
            ProtectSystem=strict
            ProtectHome=yes
            PrivateTmp=yes
            NoNewPrivileges=yes

            [Install]
            WantedBy=multi-user.target
        notify: Restart graylog-journal-forward

      - name: Enable and start the forwarder
        ansible.builtin.systemd:
          name: graylog-journal-forward
          daemon_reload: true
          enabled: true
          state: started

    handlers:
      - name: Restart graylog-journal-forward
        ansible.builtin.systemd:
          name: graylog-journal-forward
          daemon_reload: true
          state: restarted

scope:
  allowed_paths:
    - ansible/00-initial-setup/graylog-workstation-forwarder.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/graylog-workstation-forwarder.yml"
    expect: "exit 0"
    critical: true
  - id: lint
    cmd: "ansible-lint --nocolor ansible/00-initial-setup/graylog-workstation-forwarder.yml 2>&1 | tail -2"
    expect: "contains '0 failure(s)'"
    critical: true
```

### alerting-02-pi-playbook

> **Written as `ansible/00-initial-setup/graylog-pi-syslog.yml`** (this step's content, dedented), not yet run.

```yaml
id: alerting-02-pi-playbook
title: Add the playbook that enrols argon-01 and argon-02 in Graylog log shipping
depends_on: []

change: |
  Create ansible/00-initial-setup/graylog-pi-syslog.yml with exactly this
  LITERAL content.

  ---
  # Enrol the argon-01/argon-02 Raspberry Pi 4 hosts (Debian 13) in Graylog log
  # shipping (docs/alerting/plan.md, Phase 0). Same rsyslog_forward role as
  # tpot-monitoring.yml; real hardware keeps imklog so kernel and disk errors
  # are forwarded. They sit on the LAN, which MikroTik's shared Graylog rule
  # already admits. Run one host at a time:
  #   ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ./with-secrets ansible-playbook \
  #     -i ansible/inventory/inventory.yml ansible/00-initial-setup/graylog-pi-syslog.yml \
  #     --limit argon-01
  #
  # Verify: logger 'PI_FWD_PROOF' on the Pi, then in Graylog
  #   relay_src_ip:192.168.1.22 AND message:PI_FWD_PROOF
  # Rollback: rm /etc/rsyslog.d/90-log-forwarding.conf && systemctl restart rsyslog

  - name: Enrol Raspberry Pi hosts in Graylog log shipping
    hosts: hw_hosts
    become: true
    gather_facts: false

    pre_tasks:
      # hw_hosts also holds pve, pve-tiny, pve-test and the workstation; they
      # have their own log shipping and a second forward file would duplicate
      # every message.
      - name: Refuse to run on anything but the Raspberry Pi hosts
        ansible.builtin.assert:
          that: inventory_hostname in ['argon-01', 'argon-02']
          fail_msg: "graylog-pi-syslog.yml is only for argon-01/argon-02; use --limit."

    tasks:
      - name: Install rsyslog_forward for Graylog log shipping
        ansible.builtin.include_role:
          name: rsyslog_forward
        vars:
          rsyslog_forward_disable_imklog: false

scope:
  allowed_paths:
    - ansible/00-initial-setup/graylog-pi-syslog.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"
    - "Editing the rsyslog_forward role"

gates:
  - id: syntax-check
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/graylog-pi-syslog.yml"
    expect: "exit 0"
    critical: true
  - id: lint
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-lint --nocolor ansible/00-initial-setup/graylog-pi-syslog.yml 2>&1 | tail -2"
    expect: "contains '0 failure(s)' (warnings about the role's existing variable names are expected and are not new)"
    critical: true
```

### Operator: enrol the workstation and the Pis

Use **`./with-secrets-prod`** (as `tpot-monitoring.yml` does), not plain `./with-secrets`: the dev wrapper loads the retired `pve-test-vm` profile, whose `LAB_IP_GRAYLOG` is `192.168.20.114`, a dead address. Each playbook now refuses to continue unless Graylog answers. Found on the first workstation run, 2026-10-24.

Preflight: targets are the workstation (this machine, `192.168.1.104`) and
`argon-01` / `argon-02` (`192.168.1.22` / `.23`); mutating (a script, a
systemd unit, a package install on the Pis, one service restart each); out of
scope: everything else on those hosts.

```bash
TASK_APPROVAL=enrol-workstation-graylog ./with-secrets-prod ansible-playbook -i ansible/inventory/inventory.yml \
  ansible/00-initial-setup/graylog-workstation-syslog-ng.yml --limit garuda --ask-become-pass

ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles TASK_APPROVAL=enrol-pis-graylog ./with-secrets-prod ansible-playbook \
  -i ansible/inventory/inventory.yml ansible/00-initial-setup/graylog-pi-syslog.yml --limit argon-01
```

Repeat the Pi command with `--limit argon-02`. Prove each one:

```bash
logger -p user.warning 'WORKSTATION_FWD_PROOF'          # on the workstation
ssh ansible@192.168.1.22 logger 'PI_FWD_PROOF'          # then argon-02 (.23)
```

In Graylog search `relay_src_ip:192.168.1.104 AND message:WORKSTATION_FWD_PROOF`
and `relay_src_ip:192.168.1.22 AND message:PI_FWD_PROOF`. A kernel warning
from each host (for example a USB or thermal message) should also appear
within a day; if a Pi shows nothing from `application_name:kernel`, imklog is
not reading `/proc/kmsg` and that needs a look.

### Operator: NAS (Asustor Drivestor)

No step can be written until two facts are known. In ADM check:

1. Which log categories and severity the syslog sender includes (System,
   Connection, File access, and anything covering disk, SMART, fan and
   temperature events).
2. Whether SNMP can be enabled. SNMP would give disk health and temperature as
   metrics, which logs alone won't.

Record both in the README hand-back log. The NAS step packets (enable the
categories, add an SNMP scrape if available) are written from the answer.

### Phase 0b (outline): MikroTik hardware and firmware metrics

Findings: the hAP ax3 has one health sensor (`cpu-temperature`, 64 C), plus
CPU load, memory and flash. RouterOS 7.24.2 is installed with 7.24.5
available; the RouterBOARD firmware (7.19.6) is behind RouterOS and 7.24.2 is
pending. A read-only account already exists (`MIKROTIK_READONLY_USER` /
`_PASSWORD` in `services/mikrotik`).

Decided: run **mktxp** as a sidecar in monitoring-stack, using the read-only
account, scraped by VictoriaMetrics.

To find before the steps are written: the monitoring-stack compose layout and
how a sidecar is added there; mktxp's config format and its update-check
option; whether RouterOS REST/API access from monitoring-stack
(`192.168.20.12`) to the router is allowed by the firewall.

## Phase 1: Discord baseline and hardware rules

**State: built and committed, not deployed.** Result once deployed: a Discord alert for the
failure classes found on 2026-10-24. Critical alerts go to `#alerts-critical`, warnings to
`#alerts-warning`, security items to `#security`. The Telegram paging layered on top is Phase 1c,
and **both are deployed together** with the checklist in Phase 1c.

What is in the repo (`terraform/lxc/stacks/monitoring-stack/alerting/`): `homelab-baseline.yml`
(9 rules), `homelab-hardware.yml` (17 rules: NVMe and SATA faults, temperatures, SMART going
blind) and `homelab-honeypot.yml` (1 rule, Phase 1c); wired into
`deploy-monitoring-stack.yml`, which also adds the `vm-alerting` datasource.

### Prerequisites

| | State |
|---|---|
| **A.** node_exporter fleet repair (seven stacks have had no host metrics since 2026-10-21) | **Pending**, operator. Commands: Phase 1c checklist, item 1a |
| **B.** OpenBao seal-status metric | **Built, pending deploy**, operator. Commands: item 1b |
| **C.** Discord channels, webhooks, OpenBao fields, manifest | **Done 2026-10-24.** `scripts/discord_bootstrap.py` created `homelab-alerts` with four channels and webhooks; four URLs are in OpenBao `services/grafana` (v2) and declared in the manifest; read back through the wrapper; test messages arrived. One thing left: reset the bot token in the Developer Portal |

### alerting-03-manifest-fields

```yaml
id: alerting-03-manifest-fields
title: Add the four Discord webhook fields to the services/grafana manifest entry
depends_on: []

change: |
  In secrets/manifest.json, in the "services/grafana" entry's "fields" list,
  append these four strings, in this order, after "GRAFANA_OAUTH_CLIENT_SECRET":
  "DISCORD_WEBHOOK_CRITICAL", "DISCORD_WEBHOOK_WARNING",
  "DISCORD_WEBHOOK_SECURITY", "DISCORD_WEBHOOK_EVENTS". Keep the file's
  existing formatting. Change nothing else.

scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Adding any secret value anywhere"

gates:
  - id: fields-present
    cmd: >-
      python3 -c "import json;f=json.load(open('secrets/manifest.json'))['entries']['services/grafana']['fields'];assert f[-4:]==['DISCORD_WEBHOOK_CRITICAL','DISCORD_WEBHOOK_WARNING','DISCORD_WEBHOOK_SECURITY','DISCORD_WEBHOOK_EVENTS'] and len(f)==8 and len(set(f))==8;print('ok')"
    expect: "prints ok"
    critical: true
  - id: diff-size
    cmd: "git diff --numstat -- secrets/manifest.json"
    expect: "one changed line only"
    critical: true
```

### Baseline rules (reused from plan 07)

Run `catchup-07-alert-rules-file` from `docs/catch-up/07-baseline-alerting.md`
exactly as written. It creates the seven baseline rules (target down, disk
85%, NAS 90%, OpenBao sealed, snapshot stale, snapshot failed, manifest
drift). Then the next step.

### alerting-04-baseline-exclusions

```yaml
id: alerting-04-baseline-exclusions
title: Exclude the intentionally-off machines from the target-down rule
depends_on: [catchup-07-alert-rules-file]

change: |
  In terraform/lxc/stacks/monitoring-stack/alerting/homelab-baseline.yml,
  in the rule with uid homelab-target-down, replace this exact line:

    expr: 'up{job!~"minecraft-status|minecraft-jvm",instance!="192.168.60.10:8080"}'

  with this exact line (same indentation):

    expr: 'up{job!~"minecraft-status|minecraft-jvm",instance!~"192.168.60.10:8080|pve-test.gibbsgreatly.xyz:9100|garuda.gibbsgreatly.xyz:9100"}'

  pve-test (laptop) and garuda (workstation) are switched off on purpose.
  Change nothing else.

scope:
  allowed_paths:
    - terraform/lxc/stacks/monitoring-stack/alerting/homelab-baseline.yml
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: replaced
    cmd: >-
      python3 -c "import yaml;d=yaml.safe_load(open('terraform/lxc/stacks/monitoring-stack/alerting/homelab-baseline.yml'));r=[x for x in d['groups'][0]['rules'] if x['uid']=='homelab-target-down'][0];e=r['data'][0]['model']['expr'];assert 'pve-test.gibbsgreatly.xyz:9100' in e and 'garuda.gibbsgreatly.xyz:9100' in e and 'instance!~' in e;print('ok')"
    expect: "prints ok"
    critical: true
  - id: query-valid
    cmd: >-
      python3 -c "import urllib.request,urllib.parse,json;q='up{job!~\"minecraft-status|minecraft-jvm\",instance!~\"192.168.60.10:8080|pve-test.gibbsgreatly.xyz:9100|garuda.gibbsgreatly.xyz:9100\"}';print(json.load(urllib.request.urlopen('http://192.168.20.12:8428/api/v1/query?'+urllib.parse.urlencode({'query':q}),timeout=10))['status'])"
    expect: "prints success (read-only query)"
    critical: true
```

### alerting-05-hardware-rules-file

```yaml
id: alerting-05-hardware-rules-file
title: Add the Grafana hardware alert-rule provisioning file
depends_on: []

change: |
  Create terraform/lxc/stacks/monitoring-stack/alerting/homelab-hardware.yml
  with exactly this LITERAL content (copied verbatim to Grafana; the
  {{ $labels.* }} parts are Grafana templates, not Jinja):

  # Grafana file-provisioned hardware alert rules (docs/alerting/plan.md, Phase 1).
  # Copied as-is by deploy-monitoring-stack.yml; never templated by Ansible, so the
  # {{ $labels.* }} parts are Grafana templates. Every expression selects
  # job="node_exporter_hw": LXC node_exporters repeat the host NVMe sensors.
  apiVersion: 1
  groups:
    - orgId: 1
      name: homelab-hardware
      folder: Homelab alerts
      interval: 1m
      rules:
        - uid: hw-nvme-media-errors
          title: NVMe media errors increasing
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'increase(nvme_media_errors_total{job="node_exporter_hw"}[1h])'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [0]}
          for: 5m
          noDataState: OK
          execErrState: Error
          labels: {severity: critical, category: hardware, page: "true"}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.device }}: {{ humanize $values.A.Value }} new NVMe media errors in the last hour (drive is failing even if SMART says healthy)'

        - uid: hw-nvme-critical-warning
          title: NVMe critical warning flag set
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'nvme_critical_warning{job="node_exporter_hw"}'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [0]}
          for: 2m
          noDataState: OK
          execErrState: Error
          labels: {severity: critical, category: hardware, page: "true"}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.device }}: NVMe controller reports a critical warning'

        - uid: hw-nvme-spare-low
          title: NVMe spare capacity near threshold
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: '(nvme_available_spare_threshold_ratio{job="node_exporter_hw"} + 0.05) - nvme_available_spare_ratio{job="node_exporter_hw"}'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [0]}
          for: 10m
          noDataState: OK
          execErrState: Error
          labels: {severity: critical, category: hardware, page: "true"}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.device }}: available spare is within 5% of the failure threshold of the drive'

        - uid: hw-smart-unhealthy
          title: SMART overall health failed
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'smartmon_device_smart_healthy{job="node_exporter_hw"}'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: lt, params: [1]}
          for: 5m
          noDataState: OK
          execErrState: Error
          labels: {severity: critical, category: hardware, page: "true"}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.disk }}: SMART overall health assessment failed'

        - uid: hw-nvme-wear
          title: NVMe wear above 90%
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'nvme_percentage_used_ratio{job="node_exporter_hw"}'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [0.9]}
          for: 1h
          noDataState: OK
          execErrState: Error
          labels: {severity: warning, category: hardware}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.device }}: {{ humanize $values.A.Value }} of rated endurance used'

        - uid: hw-nvme-temp-warning
          title: NVMe composite temperature above 70 C
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack,chip)(node_hwmon_temp_celsius{job="node_exporter_hw",chip=~"nvme_nvme.*",sensor="temp1"})'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [70]}
          for: 15m
          noDataState: OK
          execErrState: Error
          labels: {severity: warning, category: hardware}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.chip }}: {{ humanize $values.A.Value }} C'

        - uid: hw-nvme-temp-critical
          title: NVMe composite temperature above 80 C
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack,chip)(node_hwmon_temp_celsius{job="node_exporter_hw",chip=~"nvme_nvme.*",sensor="temp1"})'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [80]}
          for: 5m
          noDataState: OK
          execErrState: Error
          labels: {severity: critical, category: hardware, page: "true"}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.chip }}: {{ humanize $values.A.Value }} C'

        - uid: hw-cpu-temp-warning
          title: CPU temperature above 85 C
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack)(node_hwmon_temp_celsius{job="node_exporter_hw",chip=~".*18_3",sensor="temp1"})'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [85]}
          for: 10m
          noDataState: OK
          execErrState: Error
          labels: {severity: warning, category: hardware}
          annotations:
            summary: '{{ $labels.stack }}: CPU Tctl {{ humanize $values.A.Value }} C'

        - uid: hw-cpu-temp-critical
          title: CPU temperature above 95 C
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack)(node_hwmon_temp_celsius{job="node_exporter_hw",chip=~".*18_3",sensor="temp1"})'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [95]}
          for: 5m
          noDataState: OK
          execErrState: Error
          labels: {severity: critical, category: hardware, page: "true"}
          annotations:
            summary: '{{ $labels.stack }}: CPU Tctl {{ humanize $values.A.Value }} C'

        - uid: hw-sata-bad-sectors
          title: SATA disk has pending or uncorrectable sectors
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack,disk)({__name__=~"smartmon_(current_pending_sector|offline_uncorrectable)_raw_value",job="node_exporter_hw"})'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [0]}
          for: 5m
          noDataState: OK
          execErrState: Error
          labels: {severity: critical, category: hardware, page: "true"}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.disk }}: {{ humanize $values.A.Value }} sectors are pending reallocation or uncorrectable (data at risk)'

        - uid: hw-sata-counters-rising
          title: SATA disk error counters rising
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack,disk)(increase({__name__=~"smartmon_(reallocated_sector_ct|reported_uncorrect|runtime_bad_block|end_to_end_error|program_fail_cnt_total|erase_fail_count_total)_raw_value",job="node_exporter_hw"}[24h]))'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [0]}
          for: 5m
          noDataState: OK
          execErrState: Error
          labels: {severity: warning, category: hardware}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.disk }}: SMART error counters rose by {{ humanize $values.A.Value }} in 24h (reallocated, uncorrectable or bad blocks)'

        - uid: hw-sata-crc-errors
          title: SATA link CRC errors rising
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack,disk)(increase(smartmon_udma_crc_error_count_raw_value{job="node_exporter_hw"}[24h]))'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [0]}
          for: 5m
          noDataState: OK
          execErrState: Error
          labels: {severity: warning, category: hardware}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.disk }}: {{ humanize $values.A.Value }} new CRC errors in 24h (suspect the SATA cable or backplane)'

        - uid: hw-sata-temp-warning
          title: SATA disk temperature above 55 C
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack,disk)((smartmon_temperature_celsius_raw_value{job="node_exporter_hw"} < 120) or (smartmon_airflow_temperature_cel_raw_value{job="node_exporter_hw"} < 120))'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [55]}
          for: 15m
          noDataState: OK
          execErrState: Error
          labels: {severity: warning, category: hardware}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.disk }}: {{ humanize $values.A.Value }} C'

        - uid: hw-sata-temp-critical
          title: SATA disk temperature above 65 C
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack,disk)((smartmon_temperature_celsius_raw_value{job="node_exporter_hw"} < 120) or (smartmon_airflow_temperature_cel_raw_value{job="node_exporter_hw"} < 120))'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [65]}
          for: 5m
          noDataState: OK
          execErrState: Error
          labels: {severity: critical, category: hardware, page: "true"}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.disk }}: {{ humanize $values.A.Value }} C'

        - uid: hw-sata-wear
          title: SATA SSD wear leveling below 20%
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'smartmon_wear_leveling_count_value{job="node_exporter_hw"}'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: lt, params: [20]}
          for: 1h
          noDataState: OK
          execErrState: Error
          labels: {severity: warning, category: hardware}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.disk }}: {{ humanize $values.A.Value }}% of rated life remains'

        - uid: hw-smart-unreadable
          title: SMART became unreadable on a disk
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: '(smartmon_device_smart_available{job="node_exporter_hw"} offset 1d) - smartmon_device_smart_available{job="node_exporter_hw"}'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [0]}
          for: 30m
          noDataState: OK
          execErrState: Error
          labels: {severity: warning, category: hardware}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.disk }}: SMART was readable yesterday and is not now, so its health flag can no longer be trusted'

        - uid: hw-smart-stale
          title: SMART metrics stopped updating
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max by (stack)(time() - node_textfile_mtime_seconds{job="node_exporter_hw",file=~".*/(smartmon|nvme).prom"})'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [7200]}
          for: 10m
          noDataState: OK
          execErrState: Error
          labels: {severity: warning, category: hardware}
          annotations:
            summary: '{{ $labels.stack }}: the SMART/NVMe collector has not written metrics for {{ humanizeDuration $values.A.Value }}, so every disk rule is blind'

scope:
  allowed_paths:
    - terraform/lxc/stacks/monitoring-stack/alerting/homelab-hardware.yml
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: parses
    cmd: >-
      python3 -c "import yaml;d=yaml.safe_load(open('terraform/lxc/stacks/monitoring-stack/alerting/homelab-hardware.yml'));r=d['groups'][0]['rules'];assert len(r)==17 and all(x['data'][0]['datasourceUid']=='vm-alerting' and 'node_exporter_hw' in x['data'][0]['model']['expr'] for x in r);print('ok')"
    expect: "prints ok"
    critical: true
  - id: queries-valid
    cmd: >-
      python3 -c "import yaml,json,urllib.request,urllib.parse;d=yaml.safe_load(open('terraform/lxc/stacks/monitoring-stack/alerting/homelab-hardware.yml'));[print(x['uid'],json.load(urllib.request.urlopen('http://192.168.20.12:8428/api/v1/query?'+urllib.parse.urlencode({'query':x['data'][0]['model']['expr']}),timeout=10))['status']) for x in d['groups'][0]['rules']]"
    expect: "17 lines, each ending in 'success' (read-only query against VictoriaMetrics)"
    critical: true
```

### alerting-06-monitoring-playbook

```yaml
id: alerting-06-monitoring-playbook
title: Wire the four Discord contact points, routing, alerting datasource and both rule files into deploy-monitoring-stack.yml
depends_on: [alerting-03-manifest-fields, alerting-04-baseline-exclusions, alerting-05-hardware-rules-file]

change: |
  Edit terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml. Make
  exactly these five edits.

  1. Directly after the vars line that begins
     "    grafana_oauth_client_secret: " insert these three LITERAL lines
     (4-space indentation, like their neighbours):
      grafana_discord_critical_url: "{{ lookup('env', 'DISCORD_WEBHOOK_CRITICAL') | mandatory('DISCORD_WEBHOOK_CRITICAL env var is not set') }}"
      grafana_discord_warning_url: "{{ lookup('env', 'DISCORD_WEBHOOK_WARNING') | mandatory('DISCORD_WEBHOOK_WARNING env var is not set') }}"
      grafana_discord_security_url: "{{ lookup('env', 'DISCORD_WEBHOOK_SECURITY') | mandatory('DISCORD_WEBHOOK_SECURITY env var is not set') }}"

  2. In the directory-creation loop, directly after the item
     "        - { path: \"{{ monitoring_compose_dir }}/grafana/provisioning/dashboards\", mode: \"0750\" }"
     insert the LITERAL item:
          - { path: "{{ monitoring_compose_dir }}/grafana/provisioning/alerting", mode: "0750" }

  3. In the task "    - name: Write Grafana datasource provisioning", add
     "      register: grafana_datasources_provisioning" as the last key of the
     task (same indentation as "ansible.builtin.copy:"), and inside its
     content, directly after the first line "              editable: true"
     (the one ending the VictoriaMetrics entry), insert this LITERAL block
     (12 spaces before "- name", 14 before the other keys):
              - name: VictoriaMetrics (alerting)
                uid: vm-alerting
                type: prometheus
                access: proxy
                url: http://victoriametrics:8428  # nosonar: ansible:S5332 — Docker-internal hostname, never reaches SDN
                isDefault: false
                editable: false

  4. Directly before the task "    - name: Write Grafana dashboard provider config",
     insert this LITERAL block (4-space task indentation, blank line after):
      - name: Copy Grafana alert rules (static files; Grafana templates, never Jinja)
        ansible.builtin.copy:
          src: "{{ playbook_dir }}/../../stacks/monitoring-stack/alerting/{{ item }}"
          dest: "{{ monitoring_compose_dir }}/grafana/provisioning/alerting/{{ item }}"
          mode: "0640"
        loop:
          - homelab-baseline.yml
          - homelab-hardware.yml
        register: grafana_alert_rules_provisioning

      - name: Write Grafana Discord contact points and notification policy
        ansible.builtin.copy:
          dest: "{{ monitoring_compose_dir }}/grafana/provisioning/alerting/contact-points.yml"
          mode: "0640"
          content: |
            apiVersion: 1
            contactPoints:
              - orgId: 1
                name: homelab-discord-critical
                receivers:
                  - uid: homelab-discord-critical
                    type: discord
                    settings:
                      url: "{{ grafana_discord_critical_url }}"
                      use_discord_username: false
                    disableResolveMessage: false
              - orgId: 1
                name: homelab-discord-warning
                receivers:
                  - uid: homelab-discord-warning
                    type: discord
                    settings:
                      url: "{{ grafana_discord_warning_url }}"
                      use_discord_username: false
                    disableResolveMessage: false
              - orgId: 1
                name: homelab-discord-security
                receivers:
                  - uid: homelab-discord-security
                    type: discord
                    settings:
                      url: "{{ grafana_discord_security_url }}"
                      use_discord_username: false
                    disableResolveMessage: false
            policies:
              - orgId: 1
                receiver: homelab-discord-warning
                group_by: ['grafana_folder', 'alertname']
                group_wait: 30s
                group_interval: 5m
                repeat_interval: 4h
                routes:
                  - receiver: homelab-discord-security
                    object_matchers:
                      - ['category', '=', 'security']
                    continue: true
                  - receiver: homelab-discord-critical
                    object_matchers:
                      - ['severity', '=', 'critical']
                    repeat_interval: 30m
        register: grafana_contact_points_provisioning
        no_log: true

  5. Directly before the task "    - name: Wait for Grafana health endpoint",
     insert this LITERAL task (blank line after):
      - name: Restart Grafana after alerting or datasource provisioning changed
        ansible.builtin.command:
          cmd: docker compose -f "{{ monitoring_compose_dir }}/docker-compose.yml" restart grafana
        when:
          - not ansible_check_mode
          - grafana_alert_rules_provisioning.changed or grafana_contact_points_provisioning.changed or grafana_datasources_provisioning.changed
        changed_when: true

  Change nothing else. (The coredns scrape job that plan 07 removed is
  already gone.)

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Removing any scrape job or target"
    - "Running the playbook or provision.sh"

gates:
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-monitoring-stack.yml"
    expect: "exit 0"
    critical: true
  - id: wiring
    cmd: >-
      bash -c 'f=terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml; for p in "grafana_discord_critical_url:" "grafana_discord_warning_url:" "grafana_discord_security_url:" "provisioning/alerting\", mode" "uid: vm-alerting" "register: grafana_alert_rules_provisioning" "register: grafana_contact_points_provisioning" "register: grafana_datasources_provisioning" "Restart Grafana after alerting" "homelab-hardware.yml"; do grep -qF "$p" $f || { echo "missing: $p"; exit 1; }; done; echo ok'
    expect: "prints ok"
    critical: true
  - id: provisioning-render
    cmd: "python3 scripts/check_grafana_provisioning.py"
    expect: "prints ok (renders the inline datasources.yml and contact-points.yml, parses them, checks vm-alerting and that every policy receiver exists)"
    critical: true
  - id: lint
    cmd: "cd terraform/lxc/ansible && ansible-lint playbooks/deploy-monitoring-stack.yml"
    expect: "no new failures compared with the same command on the pre-edit file (the file already has 1 failure and 27 warnings)"
    critical: true
```

Indentation trap, found for real when this step was first applied: the literal
blocks above are shown 2 spaces deeper than they belong in the file, because
the `change: |` block adds 2. Copy the indentation of the neighbouring lines
in the playbook, not of this document. Neither `syntax-check` nor `grep`
can see this mistake (the text is inside a `content: |` string); only
`provisioning-render` can.

### Operator: deploy and prove Phase 1

Superseded by the single checklist under **Phase 1c**, because the Discord and Telegram routing
ship in one Grafana provisioning change and one monitoring-stack deploy. The Phase 1 proof
steps are folded into it (rule and contact-point counts, the real fire test with `docker stop
cadvisor`, the Omada check, the NVMe replay).

## Phase 1c: Telegram paging and the honeypot tripwire

Built by the planner directly (not as local-model steps), with every query and the
tripwire rule itself evaluated against live data before it was written down. Nothing here
is deployed yet. This **replaces the contact points and policy** that step
`alerting-06-monitoring-playbook` wrote (that step's literal block is out of date); the
files in the repo are the source of truth.

**Who gets paged.** A rule pages Telegram when it carries the label `page: "true"` (or
`tripwire: honeypot`). Nothing else does.

| Goes to | Alerts |
|---|---|
| Telegram **and** Discord `#alerts-critical` | the 8 critical hardware rules; OpenBao sealed, snapshot stale, snapshot failed; production node unreachable; local disk above 95% |
| Telegram **and** Discord `#security` | the honeypot tripwire |
| Discord `#alerts-critical` only | other critical alerts (any scrape target down) |
| Discord `#alerts-warning` | warnings (disk 85%, NAS 90%, counters rising, wear, SMART unreadable or stale, temperatures) |
| plus Discord `#security` | anything labelled `category: security` |

Repeats: pages every 30 minutes until resolved or silenced; the tripwire once per 12 hours.

**The tripwire** (`alerting/homelab-honeypot.yml`): Grafana queries the `T-Pot Events`
OpenSearch datasource for Suricata flows into the Pi (`192.168.1.28`) on a service port from an
ephemeral source port, excluding the Pi's management ports and the allowlist (the same
`expected sources` list as the dashboard, which includes Greenbone `192.168.70.11`). One alert
instance per source address, looking back 2 hours so a probe stays visible while the hourly
(now 10-minute) sync catches up. Evaluated through Grafana's own engine against live data:
silent for the last 2 hours, and firing for `192.168.1.114` (81 flows) over 30 days.

**Checks** (`scripts/check_grafana_provisioning.py`, a gate for this phase): the inline
Grafana files parse; every rule's datasource exists; every rule marked `page` reaches a Telegram
receiver and nothing unmarked does; every critical hardware rule pages; the tripwire routes only
to its own contact point. Each of those was proven by breaking it on a copy.

### Operator: Phase 1c

**Done 2026-10-24**, in this order, all drills passed (README, *Proven live*). Kept as the runbook for a rebuild. Corrections found while running it: a manual `ansible-playbook` needs `ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg` and `ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles`; `--check` reports `Enable timers` as failed (the timer file is not written in a dry run); the honeypot drill must come from a host that is not on the allowlist (`argon-01`, `ssh ansible@192.168.1.22`, `bash -c 'echo > /dev/tcp/192.168.1.28/445'`); pentagi no longer exists, so ignore it in any `up==0` list.

Order matters.

1. **Two prerequisites** (both are things the new alerts depend on):

   **a. Repair the node_exporter fleet.** Without it the target-down rule would fire for seven
   stacks the moment alerting is on. Dry run first:

   ```bash
   git merge-base --is-ancestor 56c611bb HEAD && echo has-fix
   export TASK_APPROVAL=node-exporter-renew-fix
   ./with-secrets-prod       scripts/node-exporter-renew-fix.sh --check
   ./with-secrets-prod       scripts/node-exporter-renew-fix.sh
   ./with-secrets-prod-tiny  scripts/node-exporter-renew-fix.sh
   ./with-secrets-prod       scripts/node-exporter-renew-fix.sh --hw-hosts
   ```

   Verify with `curl -s --data-urlencode 'query=up==0' http://192.168.20.12:8428/api/v1/query`.
   It should list only `pve-test` (the laptop, off on
   purpose) and possibly `llamacpp` on framework (README open item 1). Anything else is a real
   target that is down.

   **b. Deploy the OpenBao seal-status metric.** Built and tested 2026-10-24
   (`files/openbao/openbao_health.py`, 5 tests, plus a timer in `deploy-openbao.yml`). **Without
   it `openbao_sealed` has no data, that rule treats "no data" as firing, and it would page
   Telegram the moment this is deployed.** Read the dry run first: only the new health tasks and
   "Enable timers" should change; anything else, stop and look.

   ```bash
   ./with-secrets-prod ansible-playbook -i terraform/lxc/stacks/openbao-stack/inventory.yml -u root \
     terraform/lxc/ansible/playbooks/deploy-openbao.yml --check --diff
   TASK_APPROVAL=catchup-07b-openbao-health ./with-secrets-prod ansible-playbook \
     -i terraform/lxc/stacks/openbao-stack/inventory.yml -u root terraform/lxc/ansible/playbooks/deploy-openbao.yml
   sleep 90; curl -s --data-urlencode 'query=openbao_sealed' http://192.168.20.12:8428/api/v1/query
   ```

   Expect one series with value `0`. Read-only checks on 2026-10-24 found OpenBao unsealed and
   its nightly snapshot succeeding every night at 03:30 (both `nightly` and `postwrite` series are
   in VictoriaMetrics), so the other OpenBao rules have good data.
2. **Telegram credentials into OpenBao.** They are already in `~/git/oci/.env`; this copies
   them without showing them. Do it **before** I add the manifest fields, or every production
   wrapper fails closed.

   ```bash
   cd ~/git/proxmox-homelab
   export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
   export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"   # opens a browser
   { grep '^TELEGRAM_BOT_TOKEN=' ~/git/oci/.env | cut -d= -f2-; grep '^TELEGRAM_CHAT_ID=' ~/git/oci/.env | cut -d= -f2-; } \
     | LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py services/grafana TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
   unset BAO_TOKEN
   ```

   Tell me when it succeeds and I will add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to the
   `services/grafana` manifest entry and read them back.
3. **Deploy monitoring-stack** (approval `alerting-monitoring`):
   `./with-secrets-prod scripts/provision.sh --stack monitoring-stack`. This adds the
   alerting provisioning and also restores the missing Omada scrape jobs.
4. **Make the honeypot sync faster** (approval `tpot-sync-10min`; `secpipe-stack` now lives on
   `pve-tiny`): `./with-secrets-prod-tiny scripts/provision.sh --stack secpipe-stack`. Only the
   timer changes. Check with `systemctl list-timers tpot-findings-ingest.timer` on the host.
5. **Prove it** (each line is a thing that can be seen; do them in this order):
   1. Grafana, Alerting, Alert rules: folder `Homelab alerts`, **31 rules** (9 baseline, 18 hardware,
      2 honeypot, 2 vulnerability), none in Error. Contact points: five (`homelab-discord-warning`, `-security`,
      `-critical`, `homelab-page`, `homelab-tripwire`).
   2. **Test** `homelab-page` and `homelab-tripwire` from Grafana. Each must deliver **both** a
      Telegram message and a Discord message. This is the check on the Telegram field names.
   3. **A Discord-only fire**: `ssh root@192.168.20.12 'docker stop cadvisor'`. Within about 7 minutes
      "Scrape target down" reaches Discord `#alerts-critical` and **not** Telegram (it is critical
      but not a page), and repeats every 30 minutes. `docker start cadvisor` sends the resolved
      message.
   4. **The honeypot drill**, from the Kali VM (`192.168.1.114`): `nc -vz 192.168.1.28 445` and
      `nc -vz 192.168.1.28 23`. Within about 12 minutes a Telegram message and a `#security`
      message should name `192.168.1.114`. Your own browsing of the T-Pot web UI, the router and
      Greenbone must **not** alert. If the source shows blank, the label name `src_ip.keyword` did not
      survive Grafana's notification stage; tell me and I will switch the rule to a plain count.
   5. `curl -s --data-urlencode 'query=count({__name__=~"omada_.*"})' http://192.168.20.12:8428/api/v1/query`
      returns a non-zero count (closes Phase 0.7).
   6. Hardware replay: `increase(nvme_media_errors_total{job="node_exporter_hw"}[24h])` for pve-tiny
      shows the real failure the rule exists for; see the silence note below.
6. **Afterwards:** reset the Discord bot token in the Developer Portal (Bot, Reset Token; do not copy
   the new one); then PR the branch to `stable`.

**Rollback.** The alerting is file-provisioned, so removing the three rule files and
`contact-points.yml` from the monitoring host's `grafana/provisioning/alerting/` and restarting
Grafana removes everything; reverting the commits and redeploying does the same properly. The
OpenBao metric is one timer to disable (`systemctl disable --now openbao-health.timer`). The
T-Pot timer is `tpot_findings_ingest_on_calendar` in the role defaults.

**Silencing the NVMe alert while the pve-tiny drive is awaiting RMA.** `NVMe media errors
increasing` will page whenever the failing drive logs a burst. In Grafana, Alerting, Silences,
add one for `alertname = NVMe media errors increasing` and `stack = pve-tiny`, set to end when
the replacement is in. Unsilenced, it would be doing its job.

**Not verified until the deploy:** Grafana 13's exact provisioning field names for Telegram
(`bottoken`, `chatid`, `parse_mode`) were not in the docs I could reach and come from the source
as I know it; the contact-point **Test** button is the check.

## Phase 2: Graylog log alerts

**Status 2026-10-24: applied to live Graylog 7.1.9 and drilled.** The synthetic line `critical medium error, dev nvme9n9` logged from the workstation reached Discord `#alerts-critical` as "Storage fault in a kernel log" (grouped as `garuda`, backlog attached, template fields rendered) about four minutes later. Goal: the pve-tiny drive failure
would have paged from the logs alone. It would have: `pve-tiny` logged storage errors **every day from 2026-10-16**
(8 to 11 a day, 55 on the 23rd), eight days before anyone noticed.

**What exists:** `terraform/lxc/stacks/graylog-stack/alerting/log-alerts.yml` (the rules, as data) and
`scripts/graylog_alerts.py` (12 tests). The script matches by title and updates in place, so re-running is safe. It lists
by default, `--validate` asks Graylog to check each definition (saves nothing), `--apply` creates or updates, `--test`
sends Graylog's own test message to each Discord channel.

| Rule | Pattern (exact text, never level) | 30-day hits | Goes to |
|---|---|---|---|
| Storage fault in a kernel log | `critical medium error`, `I/O error, dev`, `Buffer I/O error`, `NVMe error count increased`, `EXT4-fs error` | 167 | `#alerts-critical` |
| CPU machine check | `Machine check events logged` | 3 (pve, 10-03 to 10-05) | `#alerts-critical` |
| Kernel lockup or CPU thermal throttling | `soft lockup`, `hard LOCKUP`, `temperature above threshold` | **0, unverified** | `#alerts-critical` |
| Out-of-memory kill | `Out of memory: Killed process`, `Memory cgroup out of memory` | 21 | `#alerts-warning` |

All four exclude VLAN 70 (`NOT relay_src_ip:192.168.70.*`, 2,648 messages a month that are not lab findings), group by host, and
use a grace period (24 h; 12 h for OOM) so a failing disk gives at most one message per host per day. `EDAC` is not a pattern: it
matched 58 harmless startup lines on healthy hosts. `blk_update_request` had 0 hits (modern kernels print `I/O error, dev`).
The expected NAS `GazaarBackup` failure (15 hits) matches none of the four, so it needs no exclusion until a broader rule exists.

**What the data showed (worth acting on, separately):** `pve` OOM-killed `redis-server` (once at 10.6 GB, Greenbone scans) nearly
every night from 2026-09-29 to 10-16, and Grafana on 10-16; `pve-tiny` lost `dockerd` on 10-23. A second `pve-tiny` disk (`sdb`)
had read errors on 10-23. `pve` logged CPU machine-check lines at 03:21 on 10-03, 04 and 05 ("Bank 21 is reserved", zero
addresses: probably a bogus read, but flagged uncorrected).

**Limits, stated plainly:**

- **Discord only.** Graylog cannot post to Telegram and the relay that would is future state, so these never page. The Grafana
  hardware rules still page for NVMe and SMART faults; the log rules add what metrics cannot see (I/O errors, machine checks, OOM).
- **There is no Graylog silence.** The Grafana NVMe silence does not cover these. While the pve-tiny drive awaits its RMA the
  storage rule re-notifies once a day (the 24 h grace period) until the host is retired or the drive replaced.
- **`--validate` checks structure, not logic.** It rejects a zero-length window but accepts a wrong condition reference, so the
  drill below is the real test. The lockup/thermal patterns have never matched here.
- **Graylog keeps these in its database**, so a graylog-stack rebuild loses them: run `--apply` again afterwards.

### Operator: apply and prove Phase 2

**Done 2026-10-24.** Two bugs found by running it: Graylog 7 create endpoints need the body wrapped in `{"entity": ...}` (updates take the bare object), and the notification test path is `/events/notifications/{id}/test`. Kept as the rebuild runbook.

Production wrapper, as for any Graylog change (`./with-secrets` loads the retired test profile). Each command is safe to
repeat. Run from the repo root:

```bash
TASK_APPROVAL=graylog-log-alerts ./with-secrets-prod python3 scripts/graylog_alerts.py           # read-only: expect both notifications MISSING
TASK_APPROVAL=graylog-log-alerts ./with-secrets-prod python3 scripts/graylog_alerts.py --validate # expect four "ok"
TASK_APPROVAL=graylog-log-alerts ./with-secrets-prod python3 scripts/graylog_alerts.py --apply    # creates 2 notifications and 4 definitions
TASK_APPROVAL=graylog-log-alerts ./with-secrets-prod python3 scripts/graylog_alerts.py --test     # a test message in each Discord channel
```

Then the drill, which exercises the real rule: the workstation ships warning and above, so this synthetic line matches the
storage rule. Within about 10 minutes `Storage fault in a kernel log` should reach Discord `#alerts-critical` naming `garuda`:

```bash
logger -p user.warning 'GRAYLOG_ALERT_DRILL critical medium error, dev nvme9n9 (synthetic)'
```

The notification message text uses Graylog's own `${...}` template variables, which cannot be checked offline: if the Discord
message arrives with blank or literal fields, say so and the template line in `graylog_alerts.py` is the one to fix.

## Phase 3: the alert relay on the OCI box

> **FUTURE STATE (operator decision 2026-10-24).** Parked. The relay is built and tested but
> will not be deployed now, and whether it is the right tool (versus Uptime Kuma, or Grafana's own
> contact points plus silences) is undecided. The status text below is kept for when this resumes.

**Status 2026-10-24: 3a built and tested, not deployed.** Deploy it with
[relay-deploy.md](relay-deploy.md). Do this straight after Phase 1, before
Phase 2: it closes "nothing tells me when Grafana is down", and Phase 4
depends on it.

What exists, in the `~/git/oci` working tree (`roles/alert_relay/`). Nothing to commit
there: the Pangolin source is being moved into this repo's `oci/`
(`task/oci-security-prs-integration`, unmerged), and `roles/alert_relay/` is carried across
when that merges:

- `files/relay.py`: standard-library Python, SQLite state, about 30 MB.
  `POST /v1/alerts` (Grafana webhook or a generic JSON body),
  `POST /v1/heartbeat/<name>`, `GET /healthz` (open), `GET /metrics` (token).
  Critical alerts go to Telegram with **Ack | Snooze 1h | 4h | 24h** buttons
  and repeat every 30 minutes; heartbeat alerts are mirrored to Discord.
  Ack = quiet until resolved; snooze = quiet, then back at once if still
  firing. Only the configured chat can press buttons or send `/status` and
  `/snoozed`.
- `files/test_relay.py`: 39 tests (lifecycle, ack/snooze rules, heartbeats,
  failing channels, persistence, the HTTP layer over a local socket).
- The Ansible role, the Traefik route (no `badger`, only `/healthz`, `/metrics`
  and `/v1/*` are routed) and the container settings: non-root, read-only
  filesystem, all capabilities dropped, 128 MB limit, on the `pangolin`
  Docker network.

Two bugs the tests found before deployment: a resolve during a snooze lost
the all-clear message, and a restart gave stale heartbeat timestamps that
would have paged immediately. Both are fixed and have regression tests.

Not yet exercised against the real Telegram API from the relay (its own client
is separate from `telegram_setup.py`'s): the fire drill in the runbook is that
test.

**3b (next, after 3a is proven):** add a Grafana webhook contact point for the
relay (bearer token from OpenBao) to the critical route, so Grafana's critical
alerts also reach Telegram. Discord stays as it is.

## Phase 4 (outline): watching the watchers

> **FUTURE STATE.** Depends on Phase 3 or an off-the-shelf equivalent. Until then nothing watches
> Grafana, VictoriaMetrics, Graylog or the monitoring host.

Goal: if Grafana, VictoriaMetrics, Graylog, the monitoring host or a whole
production node dies, you are told, with no SaaS and nothing on `framework`.

- **Pinger:** a systemd timer on `pve` and on `pve-tiny`, every 5 minutes. It
  checks Grafana `/api/health`, VictoriaMetrics `/health` and Graylog
  `/api/system/lbstatus`, then POSTs a heartbeat named after the node to the
  relay with the per-component results (so a Grafana outage names Grafana). A
  few `curl` calls every five minutes; negligible load.
- **Relay behaviour:** a failed component alerts at once; no heartbeat from a
  node for about 12 minutes raises "node silent"; both silent raises "lab
  silent". All have Ack and Snooze buttons.
- **Lab watches OCI:** the relay serves `/metrics` (a heartbeat-age gauge and a
  version); VictoriaMetrics scrapes it; the Phase 1 target-down rule covers it.
- **Grafana watchdog (optional):** an always-firing rule routed to the relay
  with a 5-minute repeat proves the alert engine itself works end to end, not
  just that it is up.

Accepted residual risk: the lab and the OCI box failing at the same moment, or
Telegram and Discord both being unreachable.

## Phase 4b (outline): service checks for the alert chain (blackbox_exporter)

> **FUTURE STATE.** Probes 1 and 2 (the relay's health and certificate) wait for the relay; probes
> 3 to 7 do not depend on it.

The Nagios-style layer: active checks of services, with the same Discord
routing, Ack and Snooze as everything else.

**Scope rule, set by the operator: this monitors only the services the alert
and notification path depends on. It is not a general service monitor. Do not
add probes for other services unless the operator asks.** Icinga is the
planned upgrade if richer Nagios semantics (dependencies, escalations) turn
out to be needed.

Runs as a small sidecar in monitoring-stack (about 20 MB, like the Omada
exporter), scraped by VictoriaMetrics, with its rules in a new
`homelab-alert-chain.yml` routed critical through the existing policy. It does
not probe Grafana or VictoriaMetrics (the Phase 4 pingers and the existing
`up` rules cover them), nor OpenBao, Authentik, Harbor or anything else.

| # | Probe | Target | Success means |
|---|---|---|---|
| 1 | Relay health | `https://alerts.gibbsgreatly.xyz/healthz` | HTTP 200 |
| 2 | Relay certificate | same | more than 14 days left |
| 3 | Discord reachable | `https://discord.com/api/v10/gateway` | HTTP 200 (verified 2026-10-24, no auth) |
| 4 | Telegram reachable | `https://api.telegram.org` | HTTP 302 (verified 2026-10-24; reachable, not logged in) |
| 5 | DNS | resolve `discord.com` and `api.telegram.org` via Technitium `192.168.20.15` and `.17` | an answer from each |
| 6 | Log path | TCP `192.168.20.14:514` | connection accepted |
| 7 | Graylog API | `http://192.168.20.14:9000/api/system/lbstatus` | body `ALIVE` |

Probes 3 and 4 were checked from both a workstation and the monitoring host.
They matter because Grafana can be perfectly healthy and still unable to send
a page (DNS or internet out); probe 5 catches the DNS half of that.

To find before the steps are written: the monitoring-stack compose layout, how
the `omada_exporter` sidecar and its scrape job are wired (to copy the pattern),
and a pinned `prom/blackbox-exporter` image available through the Harbor
`dockerhub/` proxy.

## Phase 5: new critical vulnerabilities

**Status 2026-10-24: built, not yet deployed.** Goal: a critical finding that **first appears** alerts, not the roughly 700
that already exist. `terraform/lxc/stacks/monitoring-stack/alerting/homelab-vulnerabilities.yml`, two Grafana rules
over VictoriaMetrics, copied by the monitoring-stack deploy.

| Rule | Data | Fires when |
|---|---|---|
| New critical vulnerability in a Harbor image | `harbor_findings_vulnerabilities_total{severity="Critical"}` from the Harbor findings exporter (labels `project`, `repository`) | a repository's critical count is higher than 3 hours ago, or the repository is new |
| New high-severity finding in a Greenbone scan | `gvm_task_last_results{severity="hole"}` (Greenbone's "high"), per task | a task's high count is higher than 3 hours ago, or the task is new |

- **Routing:** `category: security`, severity warning: Discord `#security` only. Never a page. Telegram waits for known-exploited (KEV)
  enrichment, which does not exist yet.
- **The window is 3 hours, shorter than the 4 h repeat interval**, so a finding gives one message and then clears. Comparing with a
  day ago would repeat it six times.
- **Replayed over 14 days of real data before encoding:** Harbor would have alerted for 21 repositories, in batches after the daily
  scan around 16:00 (grouped, so about one message a day); the GVM rule would have been silent (its metric only started on 2026-10-15).
- **Guard:** each rule also needs more than 10 series to have existed 3 hours ago. Without it an exporter outage would make every
  repository look new at once; with it the metric's first day (27 series, 15 October) correctly produced nothing.
- **Excluded on purpose:** GVM tasks that scan `pentest_seg` or were launched for a pentest (results are not lab findings), and the
  decommissioned pentagi project and `vxcontrol/*` images.
- **On the first deploy** anything that became new in the previous 3 hours fires once (two Harbor repositories at the time of writing).
- **Limits:** "new" means a higher count, so a critical that is fixed while another appears in the same repository is not seen; a
  first scan of an image that was never scanned counts as new; Wazuh and UVM findings are not covered yet.

## Phase 6 (outline): the rest

- **Proxmox and PBS notification targets** to Discord via webhook, severity
  matcher, errors to `#alerts-warning`, info to `#events` (plan 13 item 13.5).
- **Weekly digest email**, Monday 07:00 `Pacific/Auckland`: alerts fired and
  snoozed, new findings, disk-fill trend, backup pass/fail, SMART changes.
  Sender and relay (a Gmail app password was the default) are decided here.
- **Native-integration review** of the services listed in the README.
- **Monthly fire drill**, written as a runbook: stop the watchdog and confirm
  Telegram fires from OCI; fire a test critical and ack it; snooze one and
  confirm it returns; replay a kernel `critical medium error` line and confirm
  the Graylog path.
- **Firmware-update alerts:** `omada_device_need_upgrade`, MikroTik
  RouterOS/RouterBOARD from Phase 0b, and Proxmox package updates.
