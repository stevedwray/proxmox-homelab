# 07 — Baseline alerting to Discord

**When:** this week, **after plan 08** (08 removes the PentAGI scrape targets,
which are down and would page immediately) · **Effort:** 1–2 sessions ·
**Value:** High
**Approval names:** `catchup-07b-openbao-health`, `catchup-07c-monitoring-alerting`

## State on 2026-09-28 (read-only VictoriaMetrics queries)

- Grafana 13.0.2 in `monitoring-stack`. No vmalert, no Alertmanager, no
  Grafana contact points or alert rules. Nothing pages anyone.
- 43 scrape targets. **7 are already down:** coredns `192.168.20.13:9153`
  (dns-stack destroyed 2026-09-08), three PentAGI targets (`192.168.70.10`,
  container gone; plan 08), and on gaming-stack-lab cAdvisor `:8080`,
  `minecraft-status :8081` and `minecraft-jvm :9404` (Foreverworld's old
  Compose exporters, dead since the move to Wings).
- OpenBao metrics exist through node_exporter's textfile collector on
  `192.168.20.16`: `openbao_snapshot_last_success_timestamp_seconds`,
  `openbao_snapshot_last_run_success`, `openbao_kv_manifest_drift` (sum 0).
  **But only `kind="postwrite"` series exist. There is no `kind="nightly"`
  series,** so the 03:30 nightly snapshot is either not running or not
  writing metrics. Part A checks this.
- No metric reports whether OpenBao is sealed.
- The NAS (`192.168.1.3`, 8 TB, `nfs4`) is **84% used**. It appears as a mount
  on openbao, portainer and media-stack-lab.

Operator decision: alerts go to a Discord webhook.

## Design

- **Delivery:** one Grafana contact point `homelab-discord`, used as the
  root notification policy.
- **Datasource:** a new provisioned datasource `VictoriaMetrics (alerting)`
  with the fixed UID `vm-alerting`, same URL as the existing one. The existing
  `VictoriaMetrics` datasource has no UID in its provisioning (dashboards
  resolve it by name), and alert rules need a real UID. A separate one avoids
  touching what the dashboards use.
- **Secret:** the webhook URL is a new OpenBao field
  `services/grafana` → `DISCORD_ALERT_WEBHOOK_URL`. Ansible writes it into
  a root-only provisioning file (same pattern as the existing datasource file).
- **Rules** (static file in the repo, copied without Jinja so Grafana's
  `{{ $labels }}` templates survive):

  | Rule | Expression | Fires when | For |
  |---|---|---|---|
  | Scrape target down | `up{job!~"minecraft-status\|minecraft-jvm",instance!="192.168.60.10:8080"}` | `< 1` | 5m |
  | Local disk above 85% | used % on `fstype=~"ext4\|zfs\|xfs\|btrfs"` | `> 85` | 15m |
  | NAS above 90% | `max` used % over `fstype="nfs4"` | `> 90` | 30m |
  | OpenBao sealed or unreachable | `openbao_sealed` (new, Part B) | `> 0` | 2m; no data = alert |
  | OpenBao snapshot stale | `time() - max(openbao_snapshot_last_success_timestamp_seconds)` | `> 129600` (36 h) | 10m; no data = alert |
  | OpenBao snapshot failed | `openbao_snapshot_last_run_success` | `< 1` | 5m |
  | OpenBao manifest drift | `sum(openbao_kv_manifest_drift)` | `> 0` | 30m |

  The Foreverworld exporters and the gaming-stack-lab cAdvisor are
  excluded rather than deleted. Whether to restore them under Wings is an
  open item in plan 13.

## Part A — operator pre-checks (read-only)

```bash
# Why is there no nightly snapshot metric?
ssh root@192.168.20.16 'systemctl list-timers openbao-snapshot-nightly.timer --no-pager; systemctl status openbao-snapshot@nightly.service --no-pager | head -15; journalctl -u openbao-snapshot@nightly.service -n 40 --no-pager; ls -l /var/lib/node_exporter/textfile/'
```

Record the result in the hand-back. If the timer isn't enabled, or the last
nightly run failed, that's a real finding. Fix it before Part C, or the
"snapshot stale" rule has only `postwrite` to go on (still correct, since it
uses `max` over kinds, but nightly coverage is the point).

## Part B — OpenBao seal-status metric

### catchup-07-openbao-health-script

```yaml
id: catchup-07-openbao-health-script
title: Add the OpenBao health textfile exporter script
depends_on: []

change: |
  Create terraform/lxc/ansible/files/openbao/openbao_health.py with exactly
  this LITERAL content:

  #!/usr/bin/env python3
  """Publish OpenBao seal status for node_exporter's textfile collector.

  Run every minute by openbao-health.timer (deploy-openbao.yml).
  /v1/sys/health needs no token. The query string makes it answer 200 in
  every state, so the JSON body can always be read (by default it returns
  503 when sealed and 501 when uninitialised).

  Writes /var/lib/node_exporter/textfile/openbao_health.prom:
    openbao_health_up  1 if the API answered, else 0
    openbao_sealed     1 if sealed or unreachable, else 0
  """
  from __future__ import annotations

  import json
  import ssl
  import urllib.request
  from pathlib import Path

  ADDR = "https://192.168.20.16:8200"
  CACERT = "/usr/local/share/ca-certificates/homelab-root.crt"
  TEXTFILE = Path("/var/lib/node_exporter/textfile/openbao_health.prom")
  QUERY = "standbyok=true&perfstandbyok=true&sealedcode=200&uninitcode=200"


  def main() -> int:
      up, sealed = 0, 1
      try:
          ctx = ssl.create_default_context(cafile=CACERT)
          opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
          with opener.open(f"{ADDR}/v1/sys/health?{QUERY}", timeout=10) as resp:
              body = json.load(resp)
          up = 1
          sealed = 1 if body.get("sealed", True) else 0
      except (OSError, ValueError):
          pass
      lines = [
          "# HELP openbao_health_up 1 if OpenBao's /v1/sys/health answered.",
          "# TYPE openbao_health_up gauge",
          f"openbao_health_up {up}",
          "# HELP openbao_sealed 1 if OpenBao reports sealed or could not be reached.",
          "# TYPE openbao_sealed gauge",
          f"openbao_sealed {sealed}",
      ]
      tmp = TEXTFILE.with_suffix(".prom.tmp")
      tmp.write_text("\n".join(lines) + "\n")
      tmp.replace(TEXTFILE)
      return 0


  if __name__ == "__main__":
      raise SystemExit(main())

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/openbao/openbao_health.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the script"

gates:
  - id: compiles
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/openbao/openbao_health.py && echo ok"
    expect: "prints ok"
    critical: true
  - id: ruff
    cmd: "ruff check terraform/lxc/ansible/files/openbao/openbao_health.py"
    expect: "exit 0"
    critical: true
```

### catchup-07-openbao-health-units

```yaml
id: catchup-07-openbao-health-units
title: Install and schedule the OpenBao health exporter in deploy-openbao.yml
depends_on: [catchup-07-openbao-health-script]

change: |
  Edit terraform/lxc/ansible/playbooks/deploy-openbao.yml. Make exactly
  these three edits and nothing else:

  1. Directly before the task line "    - name: Reload systemd units",
     insert this LITERAL block (4-space task indentation, a blank line
     after it):

      # ---- Seal-status metric for alerting (docs/catch-up/07) -----------
      - name: Install health exporter script
        ansible.builtin.copy:
          src: "{{ playbook_dir }}/../files/openbao/openbao_health.py"
          dest: /usr/local/sbin/openbao_health.py
          owner: root
          group: root
          mode: "0750"

      - name: Write health exporter service and timer
        ansible.builtin.copy:
          dest: "/etc/systemd/system/{{ item.name }}"
          owner: root
          group: root
          mode: "0644"  # nosonar: ansible:S2612 -- systemd unit files must be world-readable
          content: "{{ item.content }}"
        loop:
          - name: openbao-health.service
            content: |
              [Unit]
              Description=OpenBao seal status for node_exporter (textfile)
              After=openbao.service network-online.target
              Wants=network-online.target

              [Service]
              Type=oneshot
              ExecStart=/usr/bin/python3 /usr/local/sbin/openbao_health.py
          - name: openbao-health.timer
            content: |
              [Unit]
              Description=Refresh the OpenBao seal-status metric every minute

              [Timer]
              OnCalendar=*:*:00
              Persistent=true

              [Install]
              WantedBy=timers.target

  2. In the task "    - name: Enable timers", add the list item
     "        - openbao-health.timer" as the last entry of its loop, after
     "        - openbao-inventory.timer".

  3. Nothing else: don't reorder, reformat or touch any other task.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-openbao.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-openbao.yml"
    expect: "exit 0"
    critical: true
  - id: timer-enabled
    cmd: "sed -n '/name: Enable timers/,/^$/p' terraform/lxc/ansible/playbooks/deploy-openbao.yml | grep -c 'openbao-health.timer'"
    expect: "prints 1"
    critical: true
  - id: lint
    cmd: "cd terraform/lxc/ansible && ansible-lint playbooks/deploy-openbao.yml"
    expect: "no new failures compared with the same command on the pre-edit file"
    critical: true
```

### Operator: deploy the health exporter (approval `catchup-07b-openbao-health`)

Preflight: target the OpenBao LXC (`192.168.20.16`, `pve`); mutating
(installs one script and two units, enables one timer); re-runs
`deploy-openbao.yml`, which is idempotent for everything else; out of scope:
config, policies, seal. Check mode first:

```bash
./with-secrets-prod ansible-playbook -i terraform/lxc/stacks/openbao-stack/inventory.yml -u root terraform/lxc/ansible/playbooks/deploy-openbao.yml --check --diff
```

Expect `changed` only on the three new tasks and "Enable timers". **Any
other `changed` task: stop and look before the real run.**

```bash
TASK_APPROVAL=catchup-07b-openbao-health ./with-secrets-prod ansible-playbook -i terraform/lxc/stacks/openbao-stack/inventory.yml -u root terraform/lxc/ansible/playbooks/deploy-openbao.yml
sleep 90; curl -s --data-urlencode 'query=openbao_sealed' http://192.168.20.12:8428/api/v1/query
```

Expect one series, value `0`.

## Part C — Grafana alerting

### Operator: create the webhook and store it (before Part C's deploy)

1. Discord → your server → channel for alerts → Edit Channel → Integrations
   → Webhooks → New Webhook → name `homelab-alerts` → Copy Webhook URL.
2. Store it (explicit human OIDC login; agents never write secrets):

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py services/grafana DISCORD_ALERT_WEBHOOK_URL
unset BAO_TOKEN
```

### catchup-07-manifest-field

```yaml
id: catchup-07-manifest-field
title: Add DISCORD_ALERT_WEBHOOK_URL to the services/grafana manifest entry
depends_on: []

change: |
  In secrets/manifest.json, in the "services/grafana" entry's "fields" list,
  append the string "DISCORD_ALERT_WEBHOOK_URL" as the last element (after
  "GRAFANA_OAUTH_CLIENT_SECRET"). Keep the file's existing one-entry-per-line
  formatting. Change nothing else.

scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Adding any secret value anywhere"

gates:
  - id: field-present
    cmd: >-
      python3 -c "import json;m=json.load(open('secrets/manifest.json'));f=m['entries']['services/grafana']['fields'];assert f[-1]=='DISCORD_ALERT_WEBHOOK_URL' and len(f)==5;print('ok')"
    expect: "prints ok"
    critical: true
  - id: diff-size
    cmd: "git diff --numstat -- secrets/manifest.json"
    expect: "1 line added, 1 removed (the one entry line)"
    critical: true
```

### catchup-07-alert-rules-file

```yaml
id: catchup-07-alert-rules-file
title: Add the static Grafana alert-rule provisioning file
depends_on: []

change: |
  Create terraform/lxc/stacks/monitoring-stack/alerting/homelab-baseline.yml
  with exactly this LITERAL content (it's copied verbatim to Grafana; the
  {{ $labels.* }} parts are Grafana templates, not Jinja):

  # Grafana file-provisioned alert rules (docs/catch-up/07-baseline-alerting.md).
  # Copied as-is by deploy-monitoring-stack.yml; never templated by Ansible.
  # Datasource vm-alerting is provisioned in the same playbook.
  apiVersion: 1
  groups:
    - orgId: 1
      name: homelab-baseline
      folder: Homelab alerts
      interval: 1m
      rules:
        - uid: homelab-target-down
          title: Scrape target down
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 300, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'up{job!~"minecraft-status|minecraft-jvm",instance!="192.168.60.10:8080"}'
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
          labels: {severity: critical}
          annotations:
            summary: '{{ $labels.job }} target {{ $labels.instance }} ({{ $labels.stack }}) is down'

        - uid: homelab-disk-high
          title: Local disk above 85%
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: '100 * (1 - node_filesystem_avail_bytes{fstype=~"ext4|zfs|xfs|btrfs"} / node_filesystem_size_bytes{fstype=~"ext4|zfs|xfs|btrfs"})'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [85]}
          for: 15m
          noDataState: OK
          execErrState: Error
          labels: {severity: warning}
          annotations:
            summary: '{{ $labels.stack }} {{ $labels.mountpoint }} is {{ humanize $values.A.Value }}% full'

        - uid: homelab-nas-high
          title: NAS above 90%
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'max(100 * (1 - node_filesystem_avail_bytes{fstype="nfs4"} / node_filesystem_size_bytes{fstype="nfs4"}))'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [90]}
          for: 30m
          noDataState: OK
          execErrState: Error
          labels: {severity: warning}
          annotations:
            summary: 'NAS (192.168.1.3) is {{ humanize $values.A.Value }}% full'

        - uid: homelab-openbao-sealed
          title: OpenBao sealed or unreachable
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 300, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'openbao_sealed'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [0]}
          for: 2m
          noDataState: Alerting
          execErrState: Error
          labels: {severity: critical}
          annotations:
            summary: 'OpenBao is sealed or its health endpoint is unreachable; every deploy wrapper will fail'

        - uid: homelab-openbao-snapshot-stale
          title: OpenBao snapshot older than 36h
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'time() - max(openbao_snapshot_last_success_timestamp_seconds)'
            - refId: C
              datasourceUid: __expr__
              model:
                refId: C
                type: threshold
                expression: A
                conditions:
                  - evaluator: {type: gt, params: [129600]}
          for: 10m
          noDataState: Alerting
          execErrState: Error
          labels: {severity: critical}
          annotations:
            summary: 'Newest successful OpenBao snapshot is {{ humanizeDuration $values.A.Value }} old'

        - uid: homelab-openbao-snapshot-failed
          title: OpenBao snapshot run failed
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'openbao_snapshot_last_run_success'
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
          labels: {severity: critical}
          annotations:
            summary: 'Last OpenBao {{ $labels.kind }} snapshot run failed'

        - uid: homelab-openbao-manifest-drift
          title: OpenBao manifest drift
          condition: C
          data:
            - refId: A
              relativeTimeRange: {from: 600, to: 0}
              datasourceUid: vm-alerting
              model:
                refId: A
                instant: true
                expr: 'sum(openbao_kv_manifest_drift)'
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
          labels: {severity: warning}
          annotations:
            summary: '{{ $values.A.Value }} secrets-manifest entries are missing from OpenBao or from the manifest'

scope:
  allowed_paths:
    - terraform/lxc/stacks/monitoring-stack/alerting/homelab-baseline.yml
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: parses
    cmd: >-
      python3 -c "import yaml;d=yaml.safe_load(open('terraform/lxc/stacks/monitoring-stack/alerting/homelab-baseline.yml'));r=d['groups'][0]['rules'];assert len(r)==7 and all(x['data'][0]['datasourceUid']=='vm-alerting' for x in r);print('ok')"
    expect: "prints ok"
    critical: true
  - id: queries-valid
    cmd: >-
      python3 -c "import yaml,json,urllib.request,urllib.parse;d=yaml.safe_load(open('terraform/lxc/stacks/monitoring-stack/alerting/homelab-baseline.yml'));[print(x['uid'],json.load(urllib.request.urlopen('http://192.168.20.12:8428/api/v1/query?'+urllib.parse.urlencode({'query':x['data'][0]['model']['expr']}),timeout=10))['status']) for x in d['groups'][0]['rules']]"
    expect: "7 lines, each ending in 'success' (read-only query against VictoriaMetrics; openbao_sealed may return an empty result before Part B is deployed, which is still 'success')"
    critical: true
```

### catchup-07-monitoring-playbook

```yaml
id: catchup-07-monitoring-playbook
title: Wire Discord contact point, alerting datasource and rules into deploy-monitoring-stack.yml; drop the dead coredns job
depends_on: [catchup-07-manifest-field, catchup-07-alert-rules-file]

change: |
  Edit terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml. Make
  exactly these six edits:

  1. Directly after the vars line that begins
     "    grafana_oauth_client_secret: " insert the LITERAL line:
      grafana_discord_alert_webhook_url: "{{ lookup('env', 'DISCORD_ALERT_WEBHOOK_URL') | mandatory('DISCORD_ALERT_WEBHOOK_URL env var is not set') }}"
     (4-space indentation, like its neighbours.)

  2. In the directory-creation loop, directly after the item
     "        - { path: \"{{ monitoring_compose_dir }}/grafana/provisioning/dashboards\", mode: \"0750\" }"
     insert the LITERAL item:
          - { path: "{{ monitoring_compose_dir }}/grafana/provisioning/alerting", mode: "0750" }

  3. In the task "    - name: Write Grafana datasource provisioning", add
     "      register: grafana_datasources_provisioning" as the last key of the
     task (same indentation as "ansible.builtin.copy:"), and inside its
     content, directly after the VictoriaMetrics datasource's line
     "              editable: true" (the first occurrence), insert this LITERAL
     block (12 spaces before "- name", 14 before the other keys, matching
     the existing entries):
              - name: VictoriaMetrics (alerting)
                uid: vm-alerting
                type: prometheus
                access: proxy
                url: http://victoriametrics:8428  # nosonar: ansible:S5332 — Docker-internal hostname, never reaches SDN
                isDefault: false
                editable: false

  4. Directly before the task "    - name: Write Grafana dashboard provider config",
     insert this LITERAL block (4-space task indentation, blank line after):
      - name: Copy Grafana alert rules (static file; Grafana templates, never Jinja)
        ansible.builtin.copy:
          src: "{{ playbook_dir }}/../../stacks/monitoring-stack/alerting/homelab-baseline.yml"
          dest: "{{ monitoring_compose_dir }}/grafana/provisioning/alerting/homelab-baseline.yml"
          mode: "0640"
        register: grafana_alert_rules_provisioning

      - name: Write Grafana Discord contact point and notification policy
        ansible.builtin.copy:
          dest: "{{ monitoring_compose_dir }}/grafana/provisioning/alerting/contact-points.yml"
          mode: "0640"
          content: |
            apiVersion: 1
            contactPoints:
              - orgId: 1
                name: homelab-discord
                receivers:
                  - uid: homelab-discord
                    type: discord
                    settings:
                      url: "{{ grafana_discord_alert_webhook_url }}"
                      use_discord_username: false
                    disableResolveMessage: false
            policies:
              - orgId: 1
                receiver: homelab-discord
                group_by: ['grafana_folder', 'alertname']
                group_wait: 30s
                group_interval: 5m
                repeat_interval: 4h
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

  6. Delete the whole "coredns" scrape job: the line
     "            - job_name: coredns" and the four lines after it, through
     "                    - \"{{ lookup('env', 'LAB_IP_DNS') }}:9153\"",
     plus the one blank line that follows. Also delete the file
     terraform/lxc/stacks/monitoring-stack/dashboards/coredns.json
     (its only data source was that job; dns-stack was destroyed 2026-09-08).

  Change nothing else.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
    - terraform/lxc/stacks/monitoring-stack/dashboards/coredns.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Removing any other scrape job or target (PentAGI targets belong to plan 08)"
    - "Running the playbook or provision.sh"

gates:
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-monitoring-stack.yml"
    expect: "exit 0"
    critical: true
  - id: wiring
    cmd: >-
      bash -c 'f=terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml; for p in "grafana_discord_alert_webhook_url:" "provisioning/alerting\", mode" "uid: vm-alerting" "register: grafana_alert_rules_provisioning" "register: grafana_contact_points_provisioning" "register: grafana_datasources_provisioning" "Restart Grafana after alerting"; do grep -qF "$p" $f || { echo "missing: $p"; exit 1; }; done; ! grep -q "job_name: coredns" $f && [ ! -e terraform/lxc/stacks/monitoring-stack/dashboards/coredns.json ] && echo ok'
    expect: "prints ok"
    critical: true
  - id: lint
    cmd: "cd terraform/lxc/ansible && ansible-lint playbooks/deploy-monitoring-stack.yml"
    expect: "no new failures compared with the same command on the pre-edit file"
    critical: true
```

### Operator: deploy (approval `catchup-07c-monitoring-alerting`)

Prerequisites: Part B deployed (`openbao_sealed` = 0), the webhook stored,
plan 08's scrape-target removal merged, and the manifest change on the branch
being deployed.

Preflight: target `monitoring-stack` (`192.168.20.12`, `pve`); mutating
(provisioning files, VictoriaMetrics scrape config, one Grafana restart);
out of scope: dashboards other than removing `coredns.json`, other stacks.

```bash
./with-secrets-prod bash -c 'test -n "$DISCORD_ALERT_WEBHOOK_URL" && echo webhook-loaded'
TASK_APPROVAL=catchup-07c-monitoring-alerting ./with-secrets-prod scripts/provision.sh --stack monitoring-stack
```

### Operator: verify

1. Grafana → Alerting → Alert rules: folder "Homelab alerts" with 7 rules, all
   provisioned, none in Error.
2. Grafana → Alerting → Contact points → `homelab-discord` → **Test**. A
   message arrives in the Discord channel.
3. Real end-to-end fire: stop one harmless exporter, e.g.
   `ssh root@192.168.20.12 'docker stop cadvisor'`. Within ~6–7 minutes
   "Scrape target down … monitoring-stack" arrives in Discord. Then
   `docker start cadvisor` and see the resolved message.
4. `curl -s --data-urlencode 'query=up==0' http://192.168.20.12:8428/api/v1/query`
   lists only the three excluded gaming-stack-lab targets.

## Done when

- `openbao_sealed` is scraped; 7 rules are live; Discord got both a test
  message and a real fire/resolve pair.
- The Part A nightly-snapshot finding is recorded, and fixed or ticketed.
- Proxmox's own notifications to Discord are tracked in plan 13.
