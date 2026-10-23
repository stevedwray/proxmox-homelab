# alerting plan

Workspace README (decisions, design rules, hand-backs): [README.md](README.md).
Replaces `docs/catch-up/07-baseline-alerting.md`, whose OpenBao-health and
alert-rule steps are reused below by id.

## How to read this

- Steps are fenced YAML blocks under their own heading, per
  `docs/agent-design/step-packet-schema.md`. A step is local-model work: edit
  files, run its gates, stop. **No step deploys anything.**
- Anything that touches a running system is plain prose under an "Operator"
  heading. The operator runs it; production runs go through
  `./with-secrets-prod*` with a named `TASK_APPROVAL`.
- **Phases 0 and 1 are fully written.** Phases 2 to 6 are outlines on purpose:
  each depends on facts that only exist after the phase before it lands, and
  its first task is to find them. Their step packets get written when the
  previous phase's hand-back is in. Do not run an outline.
- Branch: cut `work/alerting-*` from current `stable`. Phase 0 and 1 only add
  files and edit the playbooks named in each step.

## Phase 0: log and metrics coverage

A rule can't fire on logs that never arrive. Phase 0 closes the gaps found by
the 2026-10-24 sweep.

| Item | State |
|---|---|
| 0.1 Relay stamps the real sender IP (`relay_src_ip`) | **Done**, live |
| 0.3 `pentest_seg` in its own stream; MikroTik 514/443 rules narrowed | **Done**, live |
| 0.2 T-Pot relabel | **Dropped**: its source is already the generic `raspberrypi` and its own logs never say "tpot" |
| 0.4 Workstation `garuda` into Graylog, warning and above | Steps 00 and 01 below |
| 0.5 argon-01 / argon-02 into Graylog | Step 02 below |
| 0.6 MikroTik hardware and firmware metrics (mktxp) | Outline, Phase 0b below |
| 0.7 Omada metrics missing from VictoriaMetrics | Closed by the Phase 1 monitoring-stack deploy |
| 0.8 NAS (Asustor Drivestor) | Operator, below |
| 0.9 Ignore the expected `GazaarBackup` failure | Phase 2 (Graylog event definitions) |

### alerting-00-journal-forwarder

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

No production-trust node is involved, so plain `./with-secrets` is right.

Preflight: targets are the workstation (this machine, `192.168.1.104`) and
`argon-01` / `argon-02` (`192.168.1.22` / `.23`); mutating (a script, a
systemd unit, a package install on the Pis, one service restart each); out of
scope: everything else on those hosts.

```bash
./with-secrets ansible-playbook -i ansible/inventory/inventory.yml \
  ansible/00-initial-setup/graylog-workstation-forwarder.yml --limit garuda --ask-become-pass

ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ./with-secrets ansible-playbook \
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

Result: a real Discord alert for the failure classes found on 2026-10-24.
Telegram is not involved yet. Critical alerts go to `#alerts-critical`,
warnings to `#alerts-warning`, vulnerability findings to `#security`.

### Operator: prerequisites, in order

**A. Repair the node_exporter fleet.** Without this, the target-down rule
fires for seven stacks the moment it is switched on.

Preflight: targets every pve LXC, every pve-tiny LXC and the bare-metal
hosts; mutating (restarts node_exporter, installs a systemd drop-in); out of
scope: anything else. Confirm the checkout has the fix, then dry-run:

```bash
git merge-base --is-ancestor 56c611bb HEAD && echo has-fix
export TASK_APPROVAL=node-exporter-renew-fix
./with-secrets-prod       scripts/node-exporter-renew-fix.sh --check
./with-secrets-prod       scripts/node-exporter-renew-fix.sh
./with-secrets-prod-tiny  scripts/node-exporter-renew-fix.sh
./with-secrets-prod       scripts/node-exporter-renew-fix.sh --hw-hosts
```

Verify: `curl -s --data-urlencode 'query=up==0' http://192.168.20.12:8428/api/v1/query`
should list only the PentAGI targets (`192.168.70.10`, plan 08), `pve-test`
(laptop, off on purpose) and possibly `llamacpp` on framework (open item 1 in
the README).

**B. OpenBao health metric.** Run plan 07's `catchup-07-openbao-health-script`
and `catchup-07-openbao-health-units` (steps in
`docs/catch-up/07-baseline-alerting.md`), then its "Operator: deploy the
health exporter" block (approval `catchup-07b-openbao-health`). Also do its
Part A check of why no nightly snapshot metric exists.

**C. Create the Discord channels and webhooks, then store them.** Follow
[discord-setup.md](discord-setup.md): the manual server and bot setup, then
`scripts/discord_bootstrap.py`, which creates the four channels and webhooks
and writes the four URLs to OpenBao (`services/grafana`) itself. Do this
**before** the manifest step lands, because the wrappers fail closed on any
manifest field that is empty in OpenBao. Afterwards confirm the four existing
Grafana fields still read back (`./with-secrets-prod env | grep -c GRAFANA_`).

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
          labels: {severity: critical, category: hardware}
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
          labels: {severity: critical, category: hardware}
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
          labels: {severity: critical, category: hardware}
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
          labels: {severity: critical, category: hardware}
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
          labels: {severity: critical, category: hardware}
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
          labels: {severity: critical, category: hardware}
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
          labels: {severity: critical, category: hardware}
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
          labels: {severity: critical, category: hardware}
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
    - "Removing any scrape job or target (PentAGI targets belong to plan 08)"
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

### Operator: deploy and prove Phase 1 (approval `alerting-monitoring`)

Prerequisites: A, B and C above done, and the manifest step on the branch
being deployed.

Preflight: target `monitoring-stack` (`192.168.20.12`, `pve`); mutating
(provisioning files, scrape config, one Grafana restart). This **also
restores the Omada scrape jobs**, which are on stable but missing from the
running stack. Out of scope: dashboards and every other stack.

```bash
./with-secrets-prod bash -c 'for v in DISCORD_WEBHOOK_CRITICAL DISCORD_WEBHOOK_WARNING DISCORD_WEBHOOK_SECURITY; do test -n "${!v}" && echo "$v loaded"; done'
TASK_APPROVAL=alerting-monitoring ./with-secrets-prod scripts/provision.sh --stack monitoring-stack
```

Prove it:

1. Grafana, Alerting, Alert rules: folder "Homelab alerts" with 24 rules
   (7 baseline + 17 hardware), none in Error.
2. Contact points: Test each of the three. A message reaches the matching
   channel.
3. Real fire: `ssh root@192.168.20.12 'docker stop cadvisor'`. Within about
   7 minutes "Scrape target down" reaches `#alerts-critical`, and again every
   30 minutes while it stays down. `docker start cadvisor` brings the
   resolved message.
4. `curl -s --data-urlencode 'query=count({__name__=~"omada_.*"})' http://192.168.20.12:8428/api/v1/query`
   returns a non-zero count (closes Phase 0.7).
5. Hardware replay: `increase(nvme_media_errors_total{job="node_exporter_hw"}[24h])`
   for pve-tiny shows the real failure the rule exists for. The rule itself
   fires on any burst; pve-tiny's drive is awaiting RMA, so expect it to page
   while it keeps erroring. Ack it in Grafana until the Phase 3 buttons exist.

## Phase 2 (outline): Graylog log alerts

Goal: the pve-tiny drive failure would have paged from the logs alone.

Decided: Graylog event definitions on **exact message patterns**, never on
level; notifications go to the relay (Phase 3), and to Discord directly until
the relay exists.

Patterns to confirm first by counting 30-day hits for each in Graylog (so none
is encoded unverified): `critical medium error`, `NVMe error count increased`
(both verified present), `EXT4-fs error`, `Machine check` / `Hardware Error`
(kernel), thermal throttling messages, `soft lockup`, and the OOM killer
(warning, not critical). The `EDAC` keyword must not be used: it matches
harmless node_exporter startup lines. Exclude the expected NAS
`GazaarBackup` failure. Exclude the `Pentest Segment` stream.

To find before the steps are written: how Graylog 7.1.9's events API is
driven from Ansible in this repo (event definitions are not provisioned
anywhere yet), and what notification types it offers (HTTP, Slack-compatible).

## Phase 3 (outline): the alert relay on the OCI box

**Do this straight after Phase 1, before Phase 2.** It is the piece that
closes "nothing tells me when Grafana is down", and Phase 4 depends on it.

Goal: one small self-hosted service on the OCI box that takes alerts and
heartbeats, pages Telegram with Ack and Snooze buttons, and mirrors to
Discord `#alerts-critical`. The contract is in the README. This is new
software; its step packets will be literal code with unit tests.

Decided: a single standard-library Python process (small enough for a micro
instance), SQLite for state, run as its own compose project attached to the
existing `pangolin` Docker network so Pangolin redeploys never touch it.
Exposed through a new Traefik router on the OCI box (a hostname such as
`alerts.gibbsgreatly.xyz`, certificate from the existing Let's Encrypt
resolver), **without** the `badger` auth plugin: the relay does its own
bearer-token check (constant-time compare), allows only `/v1/heartbeat/*`,
`/v1/alerts` and `/healthz`, and is rate limited. Traffic is outbound from the
lab only; the relay can reach nothing inside it. Secrets (Telegram token,
chat id, ingest token) go in the `oci` repo's untracked mode-0600 `.env`.

To find before the steps are written: the OCI instance's memory and CPU; how
`oci-edge-reconcile.sh` creates DNS records (the repo holds a Cloudflare
token); the exact router/service layout in `dynamic_config.yml.j2` so the new
route is additive; and the `roles/pangolin` structure so the relay becomes a
sibling role.

Operator tasks: create the bot with @BotFather and note the token; start a
chat with it and note the chat id; add `RELAY_INGEST_TOKEN` to OpenBao
`services/grafana` (same procedure as the Discord fields); approve the
hostname.

Then Grafana's critical route and Graylog's notification gain the relay as a
second receiver. Discord stays as the mirror.

## Phase 4 (outline): watching the watchers

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

## Phase 5 (outline): new critical vulnerabilities

Goal: a critical finding that **first appears** alerts, not the roughly 206
that already exist.

Sources already in Grafana: the "Harbor Findings" and "UVM Findings"
Infinity datasources, the `harbor-findings-exporter` job in VictoriaMetrics,
and GVM/Wazuh data in OpenSearch. Routing: `#security` immediately; Telegram
only once known-exploited (KEV) enrichment exists. **GVM results from
`pentest_seg` are excluded.**

To find before the steps are written: which of these expose a first-seen
timestamp, and what the Harbor exporter's metric labels are.

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
