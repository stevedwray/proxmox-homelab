# omada-controller plan

Adopt the existing Omada controller (CT 114, `192.168.1.252`, Docker image
`mbentley/omada-controller`) into the lab's IaC, pin and manage its version,
back it up, and add monitoring. Current state and decisions:
[README.md](README.md). Step shape: `docs/agent-design/step-packet-schema.md`.

**Scope rule:** nothing here moves, rebuilds, or re-IPs the CT. Docker stays.
The controller data volume `omada_omada-data` is never recreated. The two
switches must keep working throughout (they hold their own config; a
controller restart of a few minutes does not interrupt switching).

**Everything that touches `pve` is a production mutation** and goes through the
approval flow in `CLAUDE.md` (Preflight Summary → "Proceed" → `TASK_APPROVAL`
→ run → After-Action Summary), one approval per phase below. Steps in
`yaml` blocks are file edits only — local-model work, no deploys. Everything
else is plain prose for the operator.

## Phase overview

| Phase | What | Mutates pve? |
|---|---|---|
| A | Safety net: PBS snapshot + controller backup export + SSH preflight | yes (vzdump / key install) |
| B | Adopt: stack dir, pinned compose, Ansible playbook (steps 01–03), then deploy | yes |
| C | Monitoring: exporters, scrape config, secrets (steps 04–07), then deploy | yes |
| D | Security upgrade 5.15 → 6.x (prose, operator-led) | yes |
| E | Closeout: verify, docs, deferred items | no |

Order matters: **C before D** so the exporter is proven on 5.15 first and any
6.x breakage is attributable to the upgrade.

## Phase A — safety net (operator, prose)

A1. Branch check: `git branch --show-current` must print
`work/omada-controller-adoption` before any commit.

A2. SSH preflight (the CT has never been Ansible-managed; root SSH with the
lab key is unconfirmed):

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 root@192.168.1.252 'hostname && docker ps --format "{{.Names}} {{.Image}}"'
```

Expected: `omada-controller`, and `omada-controller mbentley/omada-controller:latest`.
If it fails with a permission error, install the lab public key from the pve
node (mutating — needs approval):
`ssh root@pve.gibbsgreatly.xyz "pct exec 114 -- bash -c 'mkdir -p /root/.ssh && cat >> /root/.ssh/authorized_keys'" < ~/.ssh/id_ed25519.pub`
and re-run the check above.

A3. On-demand PBS snapshot of CT 114 (production mutation — approve first):

```bash
ssh root@pve.gibbsgreatly.xyz 'vzdump 114 --storage pbs-iscsi --mode snapshot --notes-template "omada pre-adoption"'
```

Confirm the task ends `OK` and the backup shows in
`pvesm list pbs-iscsi --vmid 114`.

A4. Controller-level backup (UI, cannot be scripted from here): in the Omada
UI (`https://192.168.1.252:8043`) → Settings → Maintenance → Backup → download
a **Backup** (`.cfg`) to the NAS. Also enable **Auto Backup** (weekly, keep
several) on that page — it writes into `data/autobackup`, which the daily
vzdump then captures. Record in the README: Omada version shown in the UI and
the two switches' model, firmware, and management IPs (Devices page) —
needed for step 07.

**Gate to proceed:** A3 snapshot present and A4 `.cfg` file saved.

## Phase B — adopt under IaC

### omada-controller-01-stack-files

```yaml
id: omada-controller-01-stack-files
title: Add the omada-controller stack directory (inventory + stack.yaml)
depends_on: []

change: >
  Create terraform/lxc/stacks/omada-controller/inventory.yml and
  terraform/lxc/stacks/omada-controller/stack.yaml with exactly the content
  below (same shape as the legacy flat-LAN precedent
  terraform/lxc/stacks/management-stack/; no terragrunt.hcl — the CT is not
  Terraform-managed and must not become so in this plan).

  inventory.yml:
  ---
  all:
    children:
      omada_controller:
        hosts:
          omada-controller:
            ansible_host: 192.168.1.252
            ansible_user: root
            ansible_ssh_private_key_file: ~/.ssh/id_ed25519
            ansible_ssh_common_args: '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
            stack_name: omada-controller
            ansible_playbook: deploy-omada-controller
            vmid: 114
            pve_host: pve.gibbsgreatly.xyz
            dns_server: 192.168.1.1
            omada_version: "5.15.24.19"

  stack.yaml:
  hostname: omada-controller
  ip_address: "192.168.1.252"
  dns_server: "192.168.1.1"
  vmid: 114
  portainer_agent: true

  (inventory.yml starts with the three-dash line; omit the "inventory.yml:" /
  "stack.yaml:" label lines from the files. The pinned version equals what is
  running today, so the first deploy changes the image reference only, not the
  software.)

scope:
  allowed_paths:
    - terraform/lxc/stacks/omada-controller/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Creating terragrunt.hcl or any Terraform file"
    - "Any provision.sh / ansible-playbook run"

gates:
  - id: yaml-valid-and-pinned
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/omada-controller/inventory.yml')); h=d['all']['children']['omada_controller']['hosts']['omada-controller']; assert h['omada_version']=='5.15.24.19' and h['vmid']==114 and h['ansible_host']=='192.168.1.252'; s=yaml.safe_load(open('terraform/lxc/stacks/omada-controller/stack.yaml')); assert s['vmid']==114 and s['hostname']=='omada-controller'; print('ok')\""
    expect: "prints ok, exit 0"
    critical: true
  - id: no-terraform
    cmd: "test -z \"$(ls terraform/lxc/stacks/omada-controller | grep -E 'hcl|\\.tf$')\""
    expect: "exit 0"
    critical: true
```

### omada-controller-02-playbook

```yaml
id: omada-controller-02-playbook
title: Add deploy-omada-controller.yml (pinned compose, safety asserts)
depends_on: [omada-controller-01-stack-files]

change: |
  Create terraform/lxc/ansible/playbooks/deploy-omada-controller.yml with
  exactly the content below. It reproduces the live compose file byte-for-byte
  in behaviour (same env, same volumes, same `host` networking), pinned to
  omada_version, and refuses to run if the data volume is missing or the
  version is floating. Do NOT add docker_base (it can restart dockerd, and the
  controller with it). Do NOT rename the compose project or volumes.

  ---
  # Adopts the hand-built Omada controller CT (VMID 114, 192.168.1.252) into the
  # lab's Ansible flow. See docs/omada-controller/plan.md.
  #
  # Deliberately NOT included: docker_base (Docker is already installed and
  # configured on this CT; re-running the role could restart dockerd and with it
  # the controller). The compose project name (`omada`) and volume names
  # (omada_omada-data, omada_omada-logs) must stay exactly as they are -- they
  # hold the controller database and every switch's configuration.
  #
  # Run (production approval flow, see CLAUDE.md):
  #   TASK_APPROVAL=<task> ./with-secrets-prod scripts/provision.sh --stack omada-controller
  - name: Manage the Omada controller CT
    hosts: all
    become: true
    gather_facts: true

    vars:
      omada_compose_dir: /srv/docker/omada
      omada_image: "mbentley/omada-controller:{{ omada_version }}"

    roles:
      - lxc_base

    tasks:
      - name: Refuse to run without a pinned, non-floating version
        ansible.builtin.assert:
          that:
            - omada_version is defined
            - omada_version | regex_search('^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
          fail_msg: "omada_version must be an exact four-part version (e.g. 5.15.24.19), never latest"

      - name: Refuse to run if the controller data volume is missing (would create a blank controller)
        ansible.builtin.command: docker volume inspect omada_omada-data
        changed_when: false

      - name: Ensure the compose project directory exists
        ansible.builtin.file:
          path: "{{ omada_compose_dir }}"
          state: directory
          owner: root
          group: root
          mode: "0755"

      - name: Install the pinned compose file
        ansible.builtin.copy:
          dest: "{{ omada_compose_dir }}/docker-compose.yaml"
          owner: root
          group: root
          mode: "0644"
          backup: true
          content: |
            name: omada
            services:
              omada-controller:
                image: {{ omada_image }}
                container_name: omada-controller
                restart: unless-stopped
                network_mode: host   # Required for device discovery/adoption
                environment:
                  - JAVA_OPTS=-Xms512m -Xmx1024m
                  - PUID=508
                  - PGID=508
                  - MANAGE_HTTP_PORT=8088
                  - MANAGE_HTTPS_PORT=8043
                  - PORTAL_HTTP_PORT=8888
                  - PORTAL_HTTPS_PORT=8843
                  - SHOW_SERVER_LOGS=true
                  - SHOW_MONGODB_LOGS=false
                  - SSL_CERT_NAME=tls.crt
                  - SSL_KEY_NAME=tls.key
                  - TZ=Pacific/Auckland
                volumes:
                  - omada-data:/opt/tplink/EAPController/data
                  - omada-logs:/opt/tplink/EAPController/logs
            volumes:
              omada-data:
              omada-logs:
        register: omada_compose

      - name: Apply the compose file (recreates the container only when it changed)
        ansible.builtin.command: docker compose -f {{ omada_compose_dir }}/docker-compose.yaml up -d
        args:
          chdir: "{{ omada_compose_dir }}"
        when: omada_compose.changed

      - name: Wait for the controller management port
        ansible.builtin.wait_for:
          host: 127.0.0.1
          port: 8043
          timeout: 300
        when: not ansible_check_mode

      - name: Wait for the controller container to report healthy
        ansible.builtin.command: docker inspect -f '{% raw %}{{.State.Health.Status}}{% endraw %}' omada-controller
        register: omada_health
        until: omada_health.stdout == 'healthy'
        retries: 30
        delay: 10
        changed_when: false
        when: not ansible_check_mode

  (The file starts with the three-dash line. `{% raw %}` is required — without
  it Ansible would try to template `{{.State.Health.Status}}`.)

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-omada-controller.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Adding docker_base or any role other than lxc_base"
    - "Any provision.sh / ansible-playbook run other than --syntax-check"

gates:
  - id: syntax-check
    cmd: "ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg ansible-playbook --syntax-check -i terraform/lxc/stacks/omada-controller/inventory.yml terraform/lxc/ansible/playbooks/deploy-omada-controller.yml"
    expect: "exit 0, last line 'playbook: terraform/lxc/ansible/playbooks/deploy-omada-controller.yml'"
    critical: true
  - id: volume-guard-present
    cmd: "grep -c 'docker volume inspect omada_omada-data' terraform/lxc/ansible/playbooks/deploy-omada-controller.yml"
    expect: "1"
    critical: true
  - id: no-docker-base
    cmd: "grep -c 'docker_base$' terraform/lxc/ansible/playbooks/deploy-omada-controller.yml"
    expect: "0 (grep exits 1; that is the pass)"
    critical: true
  - id: no-floating-tag
    cmd: "grep -c ':latest' terraform/lxc/ansible/playbooks/deploy-omada-controller.yml"
    expect: "0 (grep exits 1; that is the pass)"
    critical: true
```

### omada-controller-03-handback-note

```yaml
id: omada-controller-03-handback-note
title: Record that steps 01-03 landed in the workspace README
depends_on: [omada-controller-02-playbook]

change: >
  In docs/omada-controller/README.md, replace the line `## Hand-backs` and its
  `_(none yet)_` line with a `## Hand-backs` section that is otherwise empty
  except for the sentence "Steps 01-03 landed: stack dir + pinned playbook
  exist; not yet deployed." — this is the only edit. Do not touch any other
  docs file.

scope:
  allowed_paths:
    - docs/omada-controller/README.md
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: handback-written
    cmd: "grep -c 'Steps 01-03 landed' docs/omada-controller/README.md"
    expect: "1"
    critical: true
```

### Phase B deploy (operator, prose — production mutation)

B1. Syntax + check mode first (read-only against the CT; the wrapper still
classifies `ansible-playbook` as mutating, so this needs approval too):

```bash
export TASK_APPROVAL=omada-controller-adopt
./with-secrets-prod scripts/provision.sh --stack omada-controller --check
```

Review the diff. Expected changes: `lxc_base` housekeeping (resolv.conf,
homelab root CA, node_exporter install/TLS cert, rsyslog forwarder) and the
compose file image line `latest` → `5.15.24.19`. **Stop and reassess** if the
diff shows anything touching Docker daemon config, the volumes, or
`/etc/resolv.conf` pointing somewhere other than `192.168.1.1`.

B2. Apply:

```bash
export TASK_APPROVAL=omada-controller-adopt
./with-secrets-prod scripts/provision.sh --stack omada-controller
```

The container is recreated once (pinned tag, same software). Expect the
Omada UI to be unavailable for roughly 2–5 minutes. Switches keep forwarding.

B3. Verify:
- `curl -sk -o /dev/null -w '%{http_code}\n' https://192.168.1.252:8043/` → `200`
- Omada UI → Devices: both switches **Connected** (not Disconnected/Pending).
- `ssh root@192.168.1.252 'docker inspect omada-controller --format "{{.Config.Image}}"'` → `mbentley/omada-controller:5.15.24.19`
- `ssh root@192.168.1.252 'systemctl is-active prometheus-node-exporter'` → `active`
- Graylog: search `source:omada` over the last 15 minutes returns messages.

If either switch shows Disconnected for >10 minutes: roll back with
`ssh root@192.168.1.252 'cp /srv/docker/omada/docker-compose.yaml.* /tmp/ && ls /tmp/docker-compose.yaml.*'`
(Ansible's `backup: true` keeps the previous file), restore it over
`docker-compose.yaml`, run `docker compose up -d` there, and stop for review.
The A3 PBS snapshot is the last-resort restore.

## Phase C — monitoring

Prerequisites (operator, UI + OpenBao — do before step 04's deploy, not
before writing the files):

C1. In the Omada UI create a **read-only (Viewer-role) local user**
`exporter` — not an admin. Note: the exporter logs in with this user's
credentials on every scrape cycle; do not enable MFA on it.

C2. Enable SNMP for the switches. In the Omada UI this is a site-level
setting (wording and location vary by controller version — search the site
settings for "SNMP"). Use **v2c** with a read-only community unique to this
purpose; restrict allowed sources to `192.168.40.0/24` (monitoring-stack is
in `infra_seg`) if the setting exposes that. If the switches only offer v3,
stop and tell the planner — the auth block in step 04 must change.

C3. Store the three secrets — the human, via OIDC login (agents never write
OpenBao):

```bash
bao login -method=oidc -no-store
scripts/openbao_write.py services/omada OMADA_EXPORTER_USER exporter
scripts/openbao_write.py services/omada OMADA_EXPORTER_PASSWORD '<password>'
scripts/openbao_write.py services/omada OMADA_SNMP_COMMUNITY '<community>'
```

(Check `scripts/openbao_write.py --help` first for the exact argument form;
`docs/reference/secrets-management.md` is authoritative.) Secret values are
never written into files or chat.

### omada-controller-04-secrets-manifest

```yaml
id: omada-controller-04-secrets-manifest
title: Declare the services/omada secret entry and add it to the pve profile
depends_on: []

change: >
  In secrets/manifest.json, add one entry to "entries" directly after the
  "services/nextcloud" line:
  `"services/omada": {"fields": ["OMADA_EXPORTER_PASSWORD", "OMADA_EXPORTER_USER", "OMADA_SNMP_COMMUNITY"]},`
  and add `"services/omada"` to the "pve" profile's "entries" array,
  immediately after `"services/nextcloud"`. Add it to no other profile and
  change nothing else (the wrapper fails closed on declared-but-empty fields,
  so C3 must be done before the first deploy that reads this profile).

scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Adding services/omada to any profile other than pve"
    - "Writing any secret value anywhere"

gates:
  - id: manifest-valid
    cmd: "python3 -c \"import json; m=json.load(open('secrets/manifest.json')); assert m['entries']['services/omada']['fields']==['OMADA_EXPORTER_PASSWORD','OMADA_EXPORTER_USER','OMADA_SNMP_COMMUNITY']; assert 'services/omada' in m['profiles']['pve']['entries']; assert all('services/omada' not in v['entries'] for k,v in m['profiles'].items() if k!='pve'); print('ok')\""
    expect: "prints ok, exit 0"
    critical: true
```

### omada-controller-05-monitoring-playbook

```yaml
id: omada-controller-05-monitoring-playbook
title: Add deploy-omada-monitoring.yml (omada_exporter + snmp-exporter sidecars)
depends_on: [omada-controller-04-secrets-manifest]

change: |
  Create terraform/lxc/ansible/playbooks/deploy-omada-monitoring.yml with
  exactly the content below. Images go through Harbor proxy-cache (FQDN, not
  IP), pinned. omada_exporter env names (OMADA_HOST/USER/PASS/SITE/INSECURE)
  were verified against its README. snmp-exporter loads the image's built-in
  modules (if_mib) plus our own auth file via a second --config.file; do not
  replace the built-in snmp.yml.

  ---
  # Omada controller metrics sidecars on CT 114 (192.168.1.252):
  #   omada_exporter  :9202  controller API -> devices, ports, PoE, clients
  #   snmp-exporter   :9116  per-port counters from the TP-Link switches
  # monitoring-stack scrapes both (deploy-monitoring-stack.yml, jobs
  # omada_exporter / snmp_switches). docs/omada-controller/plan.md.
  #
  # Needs OMADA_EXPORTER_USER, OMADA_EXPORTER_PASSWORD and OMADA_SNMP_COMMUNITY
  # (OpenBao services/omada, injected by ./with-secrets-prod).
  #
  # Run (production approval flow):
  #   TASK_APPROVAL=<task> ./with-secrets-prod ansible-playbook \
  #     -i terraform/lxc/stacks/omada-controller/inventory.yml \
  #     terraform/lxc/ansible/playbooks/deploy-omada-monitoring.yml
  - name: Deploy omada_exporter and snmp-exporter on the Omada controller CT
    hosts: all
    become: true
    gather_facts: false

    vars:
      omm_dir: /srv/docker/omada-monitoring
      omm_lab_domain: "{{ lookup('env', 'LAB_DOMAIN') | default('lab.gibbsgreatly.xyz', true) }}"
      # Must be the FQDN (routed through Traefik), not LAB_IP_HARBOR -- see
      # docs/harbor-stack/image-sourcing-enforcement.md.
      omm_registry_host: "{{ lookup('env', 'LAB_FQDN_HARBOR') | default('harbor.' ~ omm_lab_domain, true) }}"
      omm_exporter_image: "{{ omm_registry_host }}/ghcr/charlie-haley/omada_exporter:0.12.0"
      omm_snmp_image: "{{ omm_registry_host }}/dockerhub/prom/snmp-exporter:v0.30.1"
      omm_exporter_user: "{{ lookup('env', 'OMADA_EXPORTER_USER') | mandatory('OMADA_EXPORTER_USER env var is required') }}"
      omm_exporter_password: "{{ lookup('env', 'OMADA_EXPORTER_PASSWORD') | mandatory('OMADA_EXPORTER_PASSWORD env var is required') }}"
      omm_snmp_community: "{{ lookup('env', 'OMADA_SNMP_COMMUNITY') | mandatory('OMADA_SNMP_COMMUNITY env var is required') }}"

    tasks:
      - name: Create the sidecar project directory
        ansible.builtin.file:
          path: "{{ omm_dir }}"
          state: directory
          owner: root
          group: root
          mode: "0750"

      - name: Write the exporter credentials env file
        ansible.builtin.copy:
          dest: "{{ omm_dir }}/exporter.env"
          owner: root
          group: root
          mode: "0600"
          content: |
            OMADA_USER={{ omm_exporter_user }}
            OMADA_PASS={{ omm_exporter_password }}
        no_log: true
        register: omm_env

      - name: Write the snmp-exporter auth file (merged with the image's built-in modules)
        ansible.builtin.copy:
          dest: "{{ omm_dir }}/snmp-auth.yml"
          owner: root
          group: root
          mode: "0644"
          content: |
            auths:
              omada_v2:
                community: "{{ omm_snmp_community }}"
                version: 2
        no_log: true
        register: omm_auth

      - name: Install the sidecar compose project
        ansible.builtin.copy:
          dest: "{{ omm_dir }}/compose.yaml"
          owner: root
          group: root
          mode: "0640"
          content: |
            services:
              omada-exporter:
                image: {{ omm_exporter_image }}
                container_name: omada-exporter
                restart: unless-stopped
                env_file: exporter.env
                environment:
                  - OMADA_HOST=https://{{ ansible_host }}:8043
                  - OMADA_SITE=Default
                  - OMADA_INSECURE=true
                ports:
                  - "{{ ansible_host }}:9202:9202"
              snmp-exporter:
                image: {{ omm_snmp_image }}
                container_name: omada-snmp-exporter
                restart: unless-stopped
                command:
                  - --config.file=/etc/snmp_exporter/snmp.yml
                  - --config.file=/etc/snmp_exporter/snmp-auth.yml
                volumes:
                  - ./snmp-auth.yml:/etc/snmp_exporter/snmp-auth.yml:ro
                ports:
                  - "{{ ansible_host }}:9116:9116"
        register: omm_compose

      - name: Pull and start the sidecars
        ansible.builtin.command: docker compose -f {{ omm_dir }}/compose.yaml up -d --pull missing
        args:
          chdir: "{{ omm_dir }}"
        when: not ansible_check_mode

      - name: Restart the sidecars when credentials changed
        ansible.builtin.command: docker compose -f {{ omm_dir }}/compose.yaml restart
        args:
          chdir: "{{ omm_dir }}"
        when: not ansible_check_mode and (omm_env.changed or omm_auth.changed) and not omm_compose.changed

  (The file starts with the three-dash line.)

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-omada-monitoring.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Writing any secret value into the file"
    - "Any ansible-playbook run other than --syntax-check"

gates:
  - id: syntax-check
    cmd: "ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg ansible-playbook --syntax-check -i terraform/lxc/stacks/omada-controller/inventory.yml terraform/lxc/ansible/playbooks/deploy-omada-monitoring.yml"
    expect: "exit 0, last line 'playbook: terraform/lxc/ansible/playbooks/deploy-omada-monitoring.yml'"
    critical: true
  - id: images-pinned-via-harbor
    cmd: "grep -c -E 'ghcr/charlie-haley/omada_exporter:0\\.12\\.0|dockerhub/prom/snmp-exporter:v0\\.30\\.1' terraform/lxc/ansible/playbooks/deploy-omada-monitoring.yml"
    expect: "2"
    critical: true
  - id: no-latest
    cmd: "grep -c ':latest' terraform/lxc/ansible/playbooks/deploy-omada-monitoring.yml"
    expect: "0 (grep exits 1; that is the pass)"
    critical: true
```

### omada-controller-06-switch-targets

```yaml
id: omada-controller-06-switch-targets
title: Add the switch/controller target list read by monitoring-stack
depends_on: []

change: |
  Create terraform/lxc/stacks/omada-controller/switches.yml with the content
  below. The two `<<NEEDS OPERATOR INPUT>>` values are the switches' management
  IPs, recorded by the operator in Phase A4 (README "Hand-backs"); they cannot
  be discovered from the repo. If the operator has not supplied them, STOP —
  do not invent addresses, and do not leave the placeholder in a committed
  file that step 07's apply would read. If only the name differs from
  A4's, use the operator's name; keep names lowercase-with-hyphens.

  ---
  # Read by terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml.
  # docs/omada-controller/plan.md. `name` becomes the Grafana `switch` label.
  omada_controller_host: 192.168.1.252
  omada_switches:
    - {name: switch-01, target: "<<NEEDS OPERATOR INPUT>>"}
    - {name: switch-02, target: "<<NEEDS OPERATOR INPUT>>"}

scope:
  allowed_paths:
    - terraform/lxc/stacks/omada-controller/switches.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Guessing switch IP addresses"

gates:
  - id: yaml-valid
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/omada-controller/switches.yml')); assert d['omada_controller_host']=='192.168.1.252' and len(d['omada_switches'])==2; print('ok')\""
    expect: "prints ok, exit 0"
    critical: true
```

### omada-controller-07-scrape-config

```yaml
id: omada-controller-07-scrape-config
title: Add omada scrape jobs to deploy-monitoring-stack.yml
depends_on: [omada-controller-06-switch-targets]

change: |
  Make exactly four edits to
  terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml. Match the
  anchor text exactly (each anchor occurs once as written); indentation shown
  is the real indentation.

  EDIT 1 — in `vars_files:`, directly below the hwmon-hosts.yml line, add:
      - "{{ playbook_dir }}/../../stacks/omada-controller/switches.yml"

  EDIT 2 — insert this task, with a blank line after it, directly ABOVE the
  line `    - name: Build hwmon base relabel rules`. Indentation below is the
  real indentation (the YAML block's own 2-space margin already removed):
    - name: Build Omada switch SNMP scrape targets
      ansible.builtin.set_fact:
        omada_snmp_static_configs: "{{ (omada_snmp_static_configs | default([])) + [{'targets': [item.target], 'labels': {'stack': 'omada-controller', 'switch': item.name}}] }}"
      loop: "{{ omada_switches | default([]) }}"

  EDIT 3 — in the `node_exporter` job's static_configs, directly after the
  two lines
                - targets: ["{{ lookup('env', 'LAB_IP_GRAYLOG') }}:9100"]
                  labels: {stack: graylog-stack}
  add:
                - targets: ["{{ omada_controller_host }}:9100"]
                  labels: {stack: omada-controller}

  EDIT 4 — insert these two jobs directly ABOVE the line
  `            - job_name: cadvisor` (12-space indent, same as it), keeping a
  blank line after them:
            # Omada controller API (omada_exporter sidecar, deploy-omada-monitoring.yml).
            - job_name: omada_exporter
              scrape_interval: 60s
              scrape_timeout: 30s
              static_configs:
                - targets: ["{{ omada_controller_host }}:9202"]
                  labels: {stack: omada-controller}

            # TP-Link switch port counters via the snmp-exporter sidecar on the
            # same CT (multi-target pattern: the switch is a URL param, the
            # scrape goes to the exporter).
            - job_name: snmp_switches
              scrape_interval: 60s
              scrape_timeout: 30s
              metrics_path: /snmp
              params:
                module: [if_mib]
                auth: [omada_v2]
              static_configs: {{ omada_snmp_static_configs | default([]) | to_json }}
              relabel_configs:
                - source_labels: [__address__]
                  target_label: __param_target
                - source_labels: [__param_target]
                  target_label: instance
                - target_label: __address__
                  replacement: "{{ omada_controller_host }}:9116"

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any edit other than the four listed"
    - "Any ansible-playbook run other than --syntax-check"

gates:
  - id: syntax-check
    cmd: "ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg ansible-playbook --syntax-check -i terraform/lxc/stacks/monitoring-stack/inventory.yml terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml"
    expect: "exit 0"
    critical: true
  - id: edits-present
    cmd: "grep -c -E 'omada_controller_host|omada_snmp_static_configs|job_name: omada_exporter|job_name: snmp_switches|stacks/omada-controller/switches.yml' terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml"
    expect: "a number >= 8"
    critical: true
  - id: diff-is-additive
    cmd: "git diff --numstat -- terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml | awk '{print $2}'"
    expect: "0 (no deleted lines)"
    critical: true
```

### Phase C deploy (operator, prose — production mutations, one approval each)

Preflight: `grep -c 'NEEDS OPERATOR INPUT' terraform/lxc/stacks/omada-controller/switches.yml`
must print `0`, and C1–C3 must be done.

C4. Sidecars on CT 114:

```bash
export TASK_APPROVAL=omada-monitoring-sidecars
./with-secrets-prod ansible-playbook \
  -i terraform/lxc/stacks/omada-controller/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-omada-monitoring.yml
```

Verify from the CT: `curl -s 127.0.0.1:9202/metrics | head` shows `omada_*`
series (no login error); `curl -s "127.0.0.1:9116/snmp?module=if_mib&auth=omada_v2&target=<switch-ip>" | head`
shows `ifHCInOctets`. **If the exporter logs a login/parse error:** record it,
leave the sidecar running, and stop — do not work around it in this plan. If
the first Harbor pull of `ghcr/…` or `dockerhub/…` fails (the Harbor project
may need to exist/warm up), `docker pull` it once manually from the CT and
re-run; do not switch the playbook to Docker Hub/GHCR directly.

C5. Redeploy monitoring-stack (regenerates the scrape config):

```bash
export TASK_APPROVAL=omada-monitoring-scrape
./with-secrets-prod scripts/provision.sh --stack monitoring-stack
```

C6. Verify in VictoriaMetrics (`monitoring-stack` :8428) that these are `up == 1`:
`up{stack="omada-controller"}` for jobs `node_exporter`, `omada_exporter`,
`snmp_switches` (one series per switch). If `node_exporter` for the CT is down
but the CT answers locally, the MikroTik forward rules from `infra_seg` to
`192.168.1.252` are the first thing to check (other flat-LAN hosts, e.g.
`argon-01`, are already scraped, so a rule probably exists but may be
port-scoped to 9100 only — 9202 and 9116 may need adding; that is a MikroTik
change and needs its own approval).

Dashboards and alert rules are **not** in this plan: metric names are only
knowable from the live exporter output. After C6 passes, plan a follow-up
(Grafana dashboard JSON in `terraform/lxc/stacks/monitoring-stack/dashboards/`,
plus alerts for switch down / port flaps / PoE budget) against the real series.

## Phase D — security upgrade 5.15 → 6.x (operator-led, prose)

Do not start until Phase C is verified and a fresh A3/A4 backup pair exists
(redo both — the controller database changes across major versions and a
5.x controller **cannot** import a 6.x backup).

D1. Decide the target. Candidates (Docker Hub tags, checked 2026-10-23):
`6.0.0.25`, `6.1.0.19`, `6.2.14.11` (newest stable). TP-Link's advisories
name **6.3.0.45** as fixed, but Docker Hub only has 6.3 as `beta-*` — re-check
for a stable `6.3.x` tag first:
```bash
curl -s 'https://hub.docker.com/v2/repositories/mbentley/omada-controller/tags?page_size=100&name=6.3' | python3 -c "import sys,json; print([t['name'] for t in json.load(sys.stdin)['results'] if not t['name'].startswith('beta')])"
```
Read TP-Link's release notes for the target and the intermediate versions:
confirm 5.15 → target is a supported direct upgrade (if not, step through the
intermediate tags one at a time), and that the two switches' **firmware is
supported by the target controller version**. Re-read the advisories to
confirm whether 5.15.24.19 is actually in the affected range.

D2. Upgrade: change `omada_version` in
`terraform/lxc/stacks/omada-controller/inventory.yml` to the chosen tag
(exact four-part version), commit, then:
```bash
export TASK_APPROVAL=omada-controller-upgrade
./with-secrets-prod scripts/provision.sh --stack omada-controller
```
First start after a major upgrade runs a database migration — allow up to ~10
minutes before judging it hung (`docker logs -f omada-controller` on the CT).

D3. Verify as in B3, plus: `omada_exporter` still returns `omada_*` metrics
(if not, this is the compatibility risk noted in README — pin the exporter to
a newer release and re-run C4, or accept SNMP-only monitoring and record it);
Graylog still receiving; both switches Connected and their port/VLAN config
unchanged against the A4 record.

D4. Rollback: set `omada_version` back **and** restore the pre-upgrade PBS
snapshot (a 5.x controller cannot read the migrated 6.x data volume). The
snapshot restore replaces the whole CT; confirm with the operator before
doing it.

## Phase E — closeout

- Update `docs/omada-controller/README.md`: live state, hand-backs, version history.
- Update the "never Ansible-managed" mentions: `docs/lxc-scan-and-monitoring-rollout/README.md:169`
  and `docs/gvm-coverage-cleanup/plan.md` (its `EXTRA_HOSTS` note) — both
  still list omada-controller as having no playbook.
- Memory: add a `project_omada_controller_status` entry.
- Commit per step with the attribution trailer; per `CLAUDE.md`, PR to
  `stable` only when the operator decides — do not auto-PR.

## Deferred / open (explicitly not in this plan)

| Item | Why deferred |
|---|---|
| Controller TLS from step-ca (replace the self-signed cert; image already expects `tls.crt`/`tls.key`) | Needs its own cert-issue + renewal design; Traefik cannot route to self-signed HTTPS backends, so any `omada.<lab domain>` front door needs the controller cert or a plain-HTTP path first |
| `omada.gibbsgreatly.xyz` → `192.168.1.4` DNS record | Looks stale (that is management-stack). Verify what answers on .4 before changing; belongs with the Technitium zone work |
| SSO (Authentik) for the controller login | Omada has no OIDC/SAML for admin login; would be a forwardAuth front door — depends on the TLS item |
| Wazuh agent on the CT | Remaining gap from `docs/lxc-scan-and-monitoring-rollout/`; needs a `wazuh_agent_group` decision for a flat-LAN host |
| Portainer agent on the CT | Leave as-is (running, untouched by this plan) |
| Terraform ownership of CT 114 | Same stance as management-stack/media-stack: flat-LAN legacy CTs stay Ansible-only; importing into Terraform would be its own high-risk piece of work |
| Native-`.deb`-in-LXC re-platform | Rejected for now (see README); revisit only if TP-Link ships a signed apt repo or Debian 13 support |
| Dashboards + alert rules | Need real metric names from the live exporters (see C6) |
