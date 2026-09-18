# CyberSecEval Control Panel — Plan

Design record and step-by-step plan for the control panel described in
`README.md`. Steps follow `docs/agent-design/step-packet-schema.md` exactly —
each fenced YAML block is unconditionally local-model-executable work; any
step below written as plain prose instead is a deliberate operator/first-
production-mutation action, not an oversight.

Real facts this plan is built on (from research, not assumed):
`scaffold-stack.sh` is dead (exits 1 unconditionally, deprecated
2026-09-04) — every new-stack file below is hand-authored, not
scaffolded. `mgmt_seg` (VLAN 20, `192.168.20.0/24`) is where every
existing dashboard/ops stack lives on the `pve` node (`monitoring-stack`
VMID 20012, `graylog-stack` VMID 20014, `portainer-stack` VMID 20020);
`.30`/`20030` is the next free IP/VMID in that shared subnet. **This
stack itself runs on `pve-tiny`, not `pve`** (operator's explicit choice,
2026-09-19) — `mgmt_seg` is already defined there too
(`terraform/lxc/network/pve-tiny.yaml`, same VLAN 20/subnet/gateway as
`pve`'s, MikroTik trunk already tagged for it per that file's own header
comment), currently with zero occupants, so this is the first thing to
actually land in it — not a new zone-extension project. `pve-tiny` is
confirmed standalone (not clustered with `pve`), so VMID `20030` has no
collision risk regardless of node. Web-UI stacks route through a
centralized `edge.yaml` "EdgeManifest" + reconciler (not per-stack
Traefik labels), which also provisions the Authentik proxy-provider
automatically — there is no separate manual Authentik-wiring step needed
once `edge.yaml` is written and the edge-reconcile phase of
`provision.sh` runs. `cse-controller`/`cse-code-eval` currently have no
`daemon.json` `log-driver: syslog` task at all (confirmed missing from
both `deploy-cse-controller.yml`/`deploy-cse-code-eval.yml`), unlike
every other stack — the literal fix already exists and is proven, in
`deploy-netbox-stack.yml`.

---

## Part A — `cse-panel-stack` (new stack, `mgmt_seg`, `pve-tiny` node)

### cse-panel-01-stack-yaml

```yaml
id: cse-panel-01-stack-yaml
title: Author cse-panel-stack's stack.yaml
depends_on: []

change: >
  Create terraform/lxc/stacks/cse-panel-stack/stack.yaml with exactly the
  content below (mirrors monitoring-stack/stack.yaml's real shape, adapted
  for this stack's own zone/IP/VMID/resources).

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/stack.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply run -- this step only creates the file"

gates:
  - id: file-exists
    cmd: "test -f terraform/lxc/stacks/cse-panel-stack/stack.yaml"
    expect: "exit 0"
    critical: true
  - id: yaml-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/stack.yaml'))\""
    expect: "exit 0"
    critical: true
```

Literal content for `terraform/lxc/stacks/cse-panel-stack/stack.yaml`:

```yaml
# CyberSecEval control panel (Redis + Flower + panel-web) -- mgmt_seg zone
# on pve-tiny (operator's choice 2026-09-19 -- see plan.md's header note).
hostname: cse-panel-stack
ip_address: "${lab_ip_cse_panel}/24"
gateway: "${lab_gw_mgmt}"
dns_server: "${lab_gw_mgmt}"
network:
  zone: mgmt_seg
vmid: 20030
cores: 1
memory: 1024
swap: 512
rootfs_size: 8
storage_profile: platform-default
docker_storage_size: "8G"
template_name: "debian-13.1-2-docker-template.tar.gz"
tags:
  - cyberseceval
  - control-panel
  - dashboard
  - docker
# Empty, matching cse-controller/cse-code-eval's own precedent on
# pve-tiny -- Harbor/Authentik/Traefik are real cross-node runtime
# dependencies (see STACK_CONTRACT.md's Dependencies table) but aren't
# listed here, since there's no existing precedent on this node for a
# depends_on entry naming a stack on a different physical node, and
# cse-controller/cse-code-eval both leave this empty for the same reason.
depends_on: []
provides:
  - service: panel-web-http
    port: 8000
    protocol: tcp
  - service: flower-http
    port: 5555
    protocol: tcp
ansible_playbook: "deploy-cse-panel-stack"
deployment_tier: apps
portainer_agent: false
```

---

### cse-panel-02-compose

```yaml
id: cse-panel-02-compose
title: Author cse-panel-stack's docker-compose.yml
depends_on: [cse-panel-01-stack-yaml]

change: >
  Create terraform/lxc/stacks/cse-panel-stack/docker-compose.yml with
  exactly the content below: three services (redis, flower, panel-web),
  panel-web using a stock python:3.10-slim image with its own code
  bind-mounted in (matching cse-controller's own docker-compose.yml
  shape), not a custom-built image.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/docker-compose.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Building or pushing any container image"

gates:
  - id: compose-config
    cmd: "docker compose -f terraform/lxc/stacks/cse-panel-stack/docker-compose.yml config"
    expect: "exit 0"
    critical: true
```

Literal content for `terraform/lxc/stacks/cse-panel-stack/docker-compose.yml`
(image tags pinned, not `latest` — matches this repo's own pinning
convention elsewhere; `redis`/`flower` pulled through Harbor's Docker Hub
proxy-cache exactly like every other off-the-shelf image in this repo):

```yaml
version: '3.8'
services:
  redis:
    image: harbor.lab.gibbsgreatly.xyz/dockerhub/library/redis:7.4-alpine
    container_name: cse-panel-redis
    volumes:
      - /srv/cse-panel/redis-data:/data
    command: ["redis-server", "--appendonly", "yes"]
    restart: unless-stopped

  flower:
    image: harbor.lab.gibbsgreatly.xyz/dockerhub/mher/flower:2.0.1
    container_name: cse-panel-flower
    environment:
      - CELERY_BROKER_URL=redis://cse-panel-redis:6379/0
      - FLOWER_PORT=5555
    ports:
      - "5555:5555"
    depends_on:
      - redis
    restart: unless-stopped

  panel-web:
    image: harbor.lab.gibbsgreatly.xyz/dockerhub/library/python:3.10-slim
    container_name: cse-panel-web
    volumes:
      - /srv/cse-panel/app:/app
    working_dir: /app
    command: ["bash", "-c", "pip install --no-cache-dir -r requirements.txt && uvicorn app:app --host 0.0.0.0 --port 8000"]
    environment:
      - CELERY_BROKER_URL=redis://cse-panel-redis:6379/0
      - CELERY_RESULT_BACKEND=redis://cse-panel-redis:6379/1
      - LAB_DOMAIN=${LAB_DOMAIN}
    ports:
      - "8000:8000"
    depends_on:
      - redis
    restart: unless-stopped
```

---

### cse-panel-03-contract

```yaml
id: cse-panel-03-contract
title: Author cse-panel-stack's STACK_CONTRACT.md
depends_on: [cse-panel-01-stack-yaml, cse-panel-02-compose]

change: >
  Create terraform/lxc/stacks/cse-panel-stack/STACK_CONTRACT.md using
  exactly the section headings every other stack's STACK_CONTRACT.md
  uses (Purpose/Network/Inputs/Provides/Dependencies/Persistent State/
  What May Depend on This Stack/What Must Not Be Edited Casually/
  Playbook/Implementation Files), filled in with this stack's own real
  facts from stack.yaml and docker-compose.yml above.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: has-required-sections
    cmd: "grep -c '^## ' terraform/lxc/stacks/cse-panel-stack/STACK_CONTRACT.md"
    expect: "output >= 8"
    critical: true
  - id: contract-validator
    cmd: "./with-secrets terraform/lxc/scripts/validate-stack-metadata.sh --check-contract-sections cse-panel-stack"
    expect: "exit 0"
    critical: false
```

Literal content for `terraform/lxc/stacks/cse-panel-stack/STACK_CONTRACT.md`:

```markdown
# cse-panel-stack — Stack Contract

## Purpose

Web control panel for triggering CyberSecEval benchmark runs against
`cse-controller`/`cse-code-eval` and viewing their live progress, replacing
the ad hoc Ansible-driven shell scripts used earlier in this
implementation (see
`docs/cyberseceval-implementation/current-state.md`). Does not run any
benchmark itself — it only submits jobs to a Celery worker that runs on
`cse-controller` (see `docs/cyberseceval-panel/plan.md` Part B), where the
actual PurpleLlama checkout/datasets/agent keys live.

## Network

| Field   | Value |
|---|---|
| Zone | `mgmt_seg` (VLAN 20) |
| IP | `192.168.20.30/24` |
| Gateway | `192.168.20.1` |
| VMID | 20030 |
| Node | `pve-tiny` (not `pve` — see below) |

`mgmt_seg` is the same physical VLAN/subnet as `pve`'s `mgmt_seg`
(where Grafana/Graylog/Portainer actually run), already defined on
`pve-tiny` for exactly this kind of move but with zero occupants until
this stack — so this shares the zone's existing cross-zone firewall
rules (e.g. `edge_seg -> mgmt_seg` forward-auth) automatically, without
being on the same physical node as those other three stacks.

Reachable from `edge_seg` (Traefik forward-auth, matching every other
mgmt_seg web UI) and reachable *from* `cse_seg` on port 6379 only (the
worker on `cse-controller` connecting out to this stack's Redis) — see
`docs/cyberseceval-panel/plan.md`'s cross-zone firewall step. This stack
does not itself reach into `cse_seg`; the connection is always initiated
from the isolated side outward, matching `cse_seg`'s own default-deny
design (narrow egress allows, never inbound).

## Inputs

None via `.env`/SOPS beyond the standard `lab_ip_cse_panel`/`lab_gw_mgmt`
template variables. `panel-web` trusts the `X-Authentik-Username`/
`X-Authentik-Email` headers Traefik's forward-auth adds (same pattern as
`netbox-stack`'s `REMOTE_AUTH_HEADER`) for attributing who submitted a
job — not for authorization; Authentik/Traefik forward-auth is the actual
access gate.

## Provides

| Service | Port | Protocol |
|---|---|---|
| `panel-web-http` | 8000 | tcp |
| `flower-http` | 5555 | tcp |

Both exposed to the browser only through Traefik/Authentik forward-auth
(see `edge.yaml`), never directly.

## Dependencies

| Stack | Why |
|---|---|
| Harbor, via Traefik/`edge_seg` | Docker image pulls (`redis`, `flower`, `python:3.10-slim`, all via Harbor's Docker Hub proxy-cache) |
| Authentik-stack | forward-auth for both `panel-web` and `flower`'s browser routes |
| Proxy-stack (Traefik) | Ingress routing for both routes |
| `cse-controller` (cross-zone, `cse_seg`) | The actual benchmark execution -- this stack only submits jobs and displays their status; the Celery worker consuming them runs on `cse-controller`, not here |

## Persistent State

- `/srv/cse-panel/redis-data` — Redis's `appendonly` persistence, so
  queued/recent job state survives a container restart. Not a durable-nvme
  extra mount (this is dashboard state, not benchmark data) — ordinary
  LXC rootfs storage is sufficient.
- `/srv/cse-panel/app` — `panel-web`'s own application code
  (`app.py`/`requirements.txt`), written by the deploy playbook, not
  baked into the image (matches `cse-controller`'s own bind-mount-not-image
  convention).

## What May Depend on This Stack

Nothing yet — this is a leaf/operator-facing stack, not infrastructure
other stacks build on.

## What Must Not Be Edited Casually

- `panel-web`'s image stays a stock `python:3.10-slim`, not a custom
  build — its code lives in the bind-mounted `/srv/cse-panel/app`
  directory specifically so a container recreate never loses
  hand-maintained application code, same reasoning as `cse-controller`'s
  own `STACK_CONTRACT.md`.
- The cross-zone firewall rule this stack depends on
  (`cse_seg -> mgmt_seg:6379`) is scoped to `cse-controller`'s specific
  source IP, not the whole `cse_seg` subnet — do not widen it to a
  subnet-wide allow without a real reason; see the firewall step's own
  comment for why.

## Playbook

`deploy-cse-panel-stack` (roles: `lxc_base`, `docker_base`)

## Implementation Files

| File | Role |
|---|---|
| `terraform/lxc/stacks/cse-panel-stack/stack.yaml` | Terraform-side stack definition |
| `terraform/lxc/stacks/cse-panel-stack/docker-compose.yml` | Redis/Flower/panel-web container definitions |
| `terraform/lxc/stacks/cse-panel-stack/app/app.py` | panel-web's FastAPI application |
| `terraform/lxc/stacks/cse-panel-stack/edge.yaml` | Traefik/Authentik routing (EdgeManifest) |
| `terraform/lxc/environments/pve-tiny/cse-panel-stack/terragrunt.hcl` | Terragrunt entrypoint |
| `terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml` | Stack playbook |
```

---

### cse-panel-04-terragrunt

```yaml
id: cse-panel-04-terragrunt
title: Author cse-panel-stack's terragrunt.hcl entrypoint
depends_on: [cse-panel-01-stack-yaml]

change: >
  Create terraform/lxc/environments/pve-tiny/cse-panel-stack/terragrunt.hcl
  with exactly the boilerplate content below -- this is byte-for-byte
  identical in shape to every other stack's terragrunt.hcl in this repo
  (confirmed by reading cse-controller's own), only the directory
  location differs.

scope:
  allowed_paths:
    - terraform/lxc/environments/pve-tiny/cse-panel-stack/terragrunt.hcl
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any terragrunt apply / plan run -- this step only creates the file"

gates:
  - id: file-exists
    cmd: "test -f terraform/lxc/environments/pve-tiny/cse-panel-stack/terragrunt.hcl"
    expect: "exit 0"
    critical: true
```

Literal content for `terraform/lxc/environments/pve-tiny/cse-panel-stack/terragrunt.hcl`:

```hcl
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "${get_repo_root()}/terraform/lxc//"
}

inputs = {
  stack_name      = basename(get_terragrunt_dir())
  stack_yaml_path = "${get_repo_root()}/terraform/lxc/stacks/${basename(get_terragrunt_dir())}/stack.yaml"
  generated_dir   = get_terragrunt_dir()
}
```

---

### cse-panel-05-env-vars

```yaml
id: cse-panel-05-env-vars
title: Add cse-panel-stack's IP to .env (both naming conventions)
depends_on: []

change: >
  In .env, add two new lines near the existing LAB_IP_PORTAINER/
  lab_ip_portainer block: LAB_IP_CSE_PANEL='192.168.20.30' (uppercase
  block, with the other LAB_IP_* mgmt_seg entries) and
  lab_ip_cse_panel='192.168.20.30' plus TF_VAR_lab_ip_cse_panel
  (lowercase/TF_VAR blocks, alongside lab_ip_portainer/
  TF_VAR_lab_ip_portainer), matching this repo's exact three-form
  variable-naming convention for every other lab_ip_* entry.

scope:
  allowed_paths:
    - .env
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Removing or reordering any existing line in .env"

gates:
  - id: all-three-forms-present
    cmd: "grep -c 'cse_panel\\|CSE_PANEL' .env"
    expect: "output == 3"
    critical: true
```

---

### cse-panel-06-edge-manifest

```yaml
id: cse-panel-06-edge-manifest
title: Author cse-panel-stack's edge.yaml (Traefik + Authentik routing)
depends_on: [cse-panel-01-stack-yaml, cse-panel-02-compose]

change: >
  Create terraform/lxc/stacks/cse-panel-stack/edge.yaml with exactly the
  content below -- two routes (panel-web on 8000, flower on 5555), both
  forwardAuth, following netbox-stack/edge.yaml's exact real schema
  (apiVersion/kind/metadata/spec.routes[].host/backend/dns/tls/auth).

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/edge.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running any edge-reconcile / provision.sh phase -- this step only creates the file"

gates:
  - id: yaml-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/edge.yaml'))\""
    expect: "exit 0"
    critical: true
```

Literal content for `terraform/lxc/stacks/cse-panel-stack/edge.yaml`:

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: cse-panel-edge
  stack: cse-panel-stack
spec:
  routes:
    - name: cse-panel
      host: cse-panel.${LAB_DOMAIN}
      backend:
        type: url
        url: http://${LAB_IP_CSE_PANEL}:8000
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
    - name: cse-panel-flower
      host: cse-panel-flower.${LAB_DOMAIN}
      backend:
        type: url
        url: http://${LAB_IP_CSE_PANEL}:5555
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
```

---

### cse-panel-07-network-zone

```yaml
id: cse-panel-07-network-zone
title: Register cse-panel-stack in mgmt_seg's zone member list
depends_on: [cse-panel-01-stack-yaml]

change: >
  In terraform/lxc/network/pve-tiny.yaml's zones.mgmt_seg block, replace
  the line `containers: []  # empty -- this pass only creates the zone;
  graylog-stack has not moved yet` with a real one-entry list:
  containers:\n  - "cse-panel-stack (VMID 20030) — ${lab_ip_cse_panel}",
  matching the exact string format cse_seg's own containers list already
  uses in this same file (e.g. "cse-controller (LXC, VMID 40070) —
  192.168.100.70").

scope:
  allowed_paths:
    - terraform/lxc/network/pve-tiny.yaml
  forbidden_actions:
    - "Any change outside the zones.mgmt_seg.containers list"
    - "Any change to firewall rules in this file -- that is a separate step"

gates:
  - id: entry-present
    cmd: "grep -c 'cse-panel-stack (VMID 20030)' terraform/lxc/network/pve-tiny.yaml"
    expect: "output == 1"
    critical: true
```

---

### cse-panel-08-deploy-playbook

```yaml
id: cse-panel-08-deploy-playbook
title: Author deploy-cse-panel-stack.yml
depends_on: [cse-panel-02-compose, cse-panel-03-contract]

change: >
  Create terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml,
  following deploy-cse-controller.yml's shape (roles lxc_base/docker_base,
  write compose, docker compose up -d, wait-for-ready), plus writing
  panel-web's app.py/requirements.txt to /srv/cse-panel/app and creating
  /srv/cse-panel/redis-data, and including the standard log-driver
  syslog daemon.json task (same literal task as deploy-netbox-stack.yml's,
  see Part C) since this is a newly-created stack and should not repeat
  the log-driver gap Part C is fixing elsewhere.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any ansible-playbook run against a real host -- syntax-check only in this step"

gates:
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ../../../with-secrets ansible-playbook --syntax-check playbooks/deploy-cse-panel-stack.yml"
    expect: "exit 0"
    critical: true
```

Literal content for `terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml`:

```yaml
---
- name: Deploy cse-panel-stack
  hosts: all
  become: true
  gather_facts: true

  vars:
    cse_panel_stack_name: "{{ stack_name | default('cse-panel-stack') }}"
    cse_panel_compose_content: "{{ lookup('file', '../../stacks/' + cse_panel_stack_name + '/docker-compose.yml') }}"
    cse_panel_stack_dir: "/opt/stacks/{{ cse_panel_stack_name }}"
    cse_panel_app_dir: /srv/cse-panel/app

  roles:
    - lxc_base
    - docker_base

  tasks:
    - name: Trust Harbor HTTP registry and forward container logs to Graylog
      ansible.builtin.copy:
        dest: /etc/docker/daemon.json
        mode: "0644"
        content: |
          {
            "insecure-registries": ["{{ docker_registry_host }}"],
            "log-driver": "syslog",
            "log-opts": {
              "syslog-address": "tcp://127.0.0.1:10514",
              "syslog-format": "rfc5424",
              "tag": "{% raw %}docker-{{.Name}}{% endraw %}"
            },
            "storage-driver": "overlay2",
            "live-restore": true
          }
      notify: Restart Docker
      register: cse_panel_daemon_config

    - name: Flush handlers to apply Docker daemon config before stack deploy
      ansible.builtin.meta: flush_handlers

    - name: Create Redis persistence directory
      ansible.builtin.file:
        path: /srv/cse-panel/redis-data
        state: directory
        mode: "0755"

    - name: Create panel-web app directory
      ansible.builtin.file:
        path: "{{ cse_panel_app_dir }}"
        state: directory
        mode: "0755"

    - name: Write panel-web's app.py (source-controlled, see Part B for the matching Celery task)
      ansible.builtin.copy:
        src: "../../stacks/{{ cse_panel_stack_name }}/app/app.py"
        dest: "{{ cse_panel_app_dir }}/app.py"
        mode: "0644"

    - name: Write panel-web's requirements.txt
      ansible.builtin.copy:
        src: "../../stacks/{{ cse_panel_stack_name }}/app/requirements.txt"
        dest: "{{ cse_panel_app_dir }}/requirements.txt"
        mode: "0644"

    - name: Create stack directory
      ansible.builtin.file:
        path: "{{ cse_panel_stack_dir }}"
        state: directory
        mode: "0755"

    - name: Write docker-compose.yml to stack directory
      ansible.builtin.copy:
        content: "{{ cse_panel_compose_content }}"
        dest: "{{ cse_panel_stack_dir }}/docker-compose.yml"
        mode: "0644"

    - name: Validate docker compose configuration
      ansible.builtin.command:
        cmd: docker compose config
        chdir: "{{ cse_panel_stack_dir }}"
      register: cse_panel_compose_check
      changed_when: false
      when: not ansible_check_mode

    - name: Start cse-panel-stack via docker compose
      ansible.builtin.command:
        cmd: docker compose up -d
        chdir: "{{ cse_panel_stack_dir }}"
      register: cse_panel_compose_up
      changed_when: "'Started' in cse_panel_compose_up.stdout or 'Created' in cse_panel_compose_up.stdout"
      when: not ansible_check_mode

    - name: Wait for panel-web to respond
      ansible.builtin.uri:
        url: "http://localhost:8000/healthz"
        status_code: 200
      register: cse_panel_web_health
      until: cse_panel_web_health.status == 200
      retries: 10
      delay: 3
      when: not ansible_check_mode

  handlers:
    - name: Restart Docker
      ansible.builtin.systemd:
        name: docker
        state: restarted

- name: Enable unattended security updates (fleet rollout, 2026-08-30)
  hosts: all
  become: true
  gather_facts: false
  roles:
    - unattended_upgrades
```

---

## Part B — `panel-web` application code and the `cse-controller` Celery worker

### cse-panel-09-panel-web-app

```yaml
id: cse-panel-09-panel-web-app
title: Author panel-web's FastAPI application
depends_on: []

change: >
  Create terraform/lxc/stacks/cse-panel-stack/app/app.py and
  terraform/lxc/stacks/cse-panel-stack/app/requirements.txt with exactly
  the content below -- a minimal FastAPI app that submits Celery tasks
  by name to the shared Redis broker and reports their status, plus a
  bare HTML form.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/app/app.py
    - terraform/lxc/stacks/cse-panel-stack/app/requirements.txt
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running this app or installing its dependencies -- authoring only in this step"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/stacks/cse-panel-stack/app/app.py"
    expect: "exit 0"
    critical: true
```

Literal content for `terraform/lxc/stacks/cse-panel-stack/app/requirements.txt`:

```text
fastapi==0.115.6
uvicorn==0.34.0
celery==5.4.0
redis==5.2.1
```

Literal content for `terraform/lxc/stacks/cse-panel-stack/app/app.py`:

```python
"""cse-panel-stack's panel-web: submits CyberSecEval benchmark runs as
Celery tasks and reports their status. The actual benchmark execution
happens in the Celery worker on cse-controller (see
terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py) --
this app never runs benchmark code itself.
"""
import os
from celery import Celery
from celery.result import AsyncResult
from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse

BROKER_URL = os.environ["CELERY_BROKER_URL"]
RESULT_BACKEND = os.environ["CELERY_RESULT_BACKEND"]

celery_app = Celery("cse_panel", broker=BROKER_URL, backend=RESULT_BACKEND)

# Must match the task name registered by cse_tasks.py's worker exactly --
# Celery routes by string name, not by import, since the worker and this
# submitter are different processes on different hosts.
TASK_NAME = "cse_tasks.run_benchmark"

# The set of benchmarks proven to work in the 2026-09-19 small-batch run
# (docs/cyberseceval-implementation/current-state.md) -- deliberately not
# auto-discovered from the PurpleLlama checkout, so a new/untested
# benchmark id can't be submitted by accident.
KNOWN_BENCHMARKS = [
    "mitre",
    "mitre-frr",
    "prompt-injection",
    "interpreter",
    "instruct",
    "autocomplete",
    "malware_analysis",
    "threat_intel_reasoning",
    "multiturn-phishing",
    "autonomous-uplift",
]

RECENT_JOBS_KEY = "cse_panel:recent_job_ids"
RECENT_JOBS_MAX = 50

app = FastAPI(title="CyberSecEval Control Panel")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/benchmarks")
def list_benchmarks():
    return {"benchmarks": KNOWN_BENCHMARKS}


@app.post("/jobs")
def submit_job(
    benchmark: str,
    num_test_cases: int = 2,
    x_authentik_username: str | None = Header(default=None),
):
    if benchmark not in KNOWN_BENCHMARKS:
        return {"error": f"unknown benchmark '{benchmark}', must be one of {KNOWN_BENCHMARKS}"}
    result = celery_app.send_task(
        TASK_NAME,
        kwargs={
            "benchmark": benchmark,
            "num_test_cases": num_test_cases,
            "submitted_by": x_authentik_username or "unknown",
        },
    )
    celery_app.backend.client.lpush(RECENT_JOBS_KEY, result.id)
    celery_app.backend.client.ltrim(RECENT_JOBS_KEY, 0, RECENT_JOBS_MAX - 1)
    return {"job_id": result.id, "benchmark": benchmark}


@app.get("/jobs")
def list_recent_jobs():
    ids = celery_app.backend.client.lrange(RECENT_JOBS_KEY, 0, -1)
    jobs = []
    for raw_id in ids:
        job_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        res = AsyncResult(job_id, app=celery_app)
        jobs.append({"job_id": job_id, "state": res.state})
    return {"jobs": jobs}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    res = AsyncResult(job_id, app=celery_app)
    body = {"job_id": job_id, "state": res.state}
    if res.state == "SUCCESS":
        body["result"] = res.result
    elif res.state == "FAILURE":
        body["error"] = str(res.result)
    return body


@app.get("/", response_class=HTMLResponse)
def index():
    options = "".join(f'<option value="{b}">{b}</option>' for b in KNOWN_BENCHMARKS)
    lab_domain = os.environ.get("LAB_DOMAIN", "")
    flower_url = f"https://cse-panel-flower.{lab_domain}" if lab_domain else "#"
    return f"""
    <html><head><title>CyberSecEval Control Panel</title></head>
    <body>
      <h1>CyberSecEval Control Panel</h1>
      <form id="submit-form">
        <label>Benchmark: <select name="benchmark">{options}</select></label>
        <label>Num test cases: <input name="num_test_cases" type="number" value="2" min="1" max="10"></label>
        <button type="submit">Run</button>
      </form>
      <p><a href="/jobs">Recent jobs (JSON)</a> &middot;
         <a href="/docs">API docs</a> &middot;
         <a href="{flower_url}">Flower (live task detail)</a></p>
      <script>
        document.getElementById('submit-form').addEventListener('submit', async (e) => {{
          e.preventDefault();
          const form = new FormData(e.target);
          const params = new URLSearchParams(form);
          const res = await fetch('/jobs?' + params.toString(), {{method: 'POST'}});
          const body = await res.json();
          alert(JSON.stringify(body));
        }});
      </script>
    </body></html>
    """
```

---

### cse-panel-10-worker-tasks

```yaml
id: cse-panel-10-worker-tasks
title: Author cse-controller's Celery task module (cse_tasks.py)
depends_on: [cse-panel-09-panel-web-app]

change: >
  Create terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py
  with exactly the content below -- a Celery worker app registering one
  task, run_benchmark, which builds and runs the same benchmark.run CLI
  invocations already proven in ansible/00-initial-setup/
  cse-small-batch-run.yml, parameterized by benchmark name and
  num_test_cases, writing output under /srv/cyberseceval/runs/panel-<job-id>/.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running this module -- authoring only in this step"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py"
    expect: "exit 0"
    critical: true
```

Literal content for
`terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py`:

```python
"""Celery worker for cse-controller -- runs on cse-controller itself (see
docker-compose.yml's `worker` service), consuming jobs submitted by
cse-panel-stack's panel-web across the cse_seg -> mgmt_seg:6379 firewall
rule. One task, run_benchmark, covers every benchmark proven in the
2026-09-19 small-batch run (see
docs/cyberseceval-implementation/current-state.md) -- the same CLI shapes
as ansible/00-initial-setup/cse-small-batch-run.yml's run-batch.sh,
parameterized instead of hardcoded per-benchmark.
"""
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from celery import Celery

BROKER_URL = os.environ["CELERY_BROKER_URL"]
RESULT_BACKEND = os.environ["CELERY_RESULT_BACKEND"]

app = Celery("cse_tasks", broker=BROKER_URL, backend=RESULT_BACKEND)

REPO_DIR = Path("/srv/cyberseceval/repo/PurpleLlama")
VENV_PY = Path("/srv/cyberseceval/.venv/bin/python3")
RUNS_DIR = Path("/srv/cyberseceval/runs")

# Framework's llama-server, matching the exact spec proven in Phase 2
# (docs/cyberseceval-implementation/current-state.md) and reused by
# cse-small-batch-run.yml.
MUT_SPEC = (
    "OPENAI::/models/qwen3.8-flash-next-q4/UD-Q4_K_XL/"
    "Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf::not-needed::"
    "http://framework.gibbsgreatly.xyz:8080/v1"
)


def _judge_spec() -> str:
    key = os.environ["OPENAI_API_KEY"]
    return f"OPENAI::gpt-4o-mini::{key}"


# Each entry: the exact argv (minus python3/module prefix) run.py needs,
# using {run_dir} as the per-job output directory placeholder.
_BENCHMARK_COMMANDS = {
    "mitre": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=mitre",
        "--prompt-path=CybersecurityBenchmarks/datasets/mitre/mitre_benchmark_100_per_category_with_augmentation.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--judge-llm={_judge_spec()}", f"--expansion-llm={_judge_spec()}",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "mitre-frr": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=mitre-frr",
        "--prompt-path=CybersecurityBenchmarks/datasets/mitre_frr/mitre_frr.json",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "prompt-injection": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=prompt-injection",
        "--prompt-path=CybersecurityBenchmarks/datasets/prompt_injection/prompt_injection.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--judge-llm={_judge_spec()}",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "interpreter": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=interpreter",
        "--prompt-path=CybersecurityBenchmarks/datasets/interpreter/interpreter.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--judge-llm={_judge_spec()}",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "instruct": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=instruct",
        "--prompt-path=CybersecurityBenchmarks/datasets/instruct/instruct-v2.json",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "autocomplete": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=autocomplete",
        "--prompt-path=CybersecurityBenchmarks/datasets/autocomplete/autocomplete.json",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "malware_analysis": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=malware_analysis",
        "--prompt-path=CybersecurityBenchmarks/datasets/crwd_meta/malware_analysis/questions.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stats.json",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "threat_intel_reasoning": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=threat_intel_reasoning",
        "--prompt-path=CybersecurityBenchmarks/datasets/crwd_meta/threat_intel_reasoning/report_questions.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stats.json",
        "--input-modality=text",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
    "multiturn-phishing": lambda run_dir, n: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=multiturn-phishing",
        "--prompt-path=CybersecurityBenchmarks/datasets/spear_phishing/multiturn_phishing_challenges.json",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stats.json",
        f"--judge-llm={MUT_SPEC}",
        f"--llm-under-test={MUT_SPEC}", f"--num-test-cases={n}",
    ],
}


def _run_autonomous_uplift(run_dir: Path, shots: int) -> dict:
    gen_cmd = [
        str(VENV_PY), "-m", "CybersecurityBenchmarks.datasets.autonomous_uplift.test_case_generator",
        "--ssh-key-file=/srv/cyberseceval/config/cse-kali-agent-key",
        "--ssh-username=kali",
        "--cyber-range-file=/srv/cyberseceval/config/cyber_range_pairs.json",
        "--system-prompt-file=CybersecurityBenchmarks/datasets/autonomous_uplift/in/system_prompt.txt",
        f"--out-file={run_dir}/prompts.json",
        f"--shots-per-run={shots}", "--runs-per-range=1",
    ]
    gen = subprocess.run(gen_cmd, cwd=REPO_DIR, capture_output=True, text=True)
    if gen.returncode != 0:
        return {"rc": gen.returncode, "stage": "generate", "log": gen.stdout + gen.stderr}
    attack_cmd = [
        str(VENV_PY), "-m", "CybersecurityBenchmarks.benchmark.run",
        "--benchmark=autonomous-uplift",
        f"--prompt-path={run_dir}/prompts.json",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={MUT_SPEC}",
    ]
    attack = subprocess.run(attack_cmd, cwd=REPO_DIR, capture_output=True, text=True)
    return {"rc": attack.returncode, "stage": "attack", "log": attack.stdout + attack.stderr}


@app.task(name="cse_tasks.run_benchmark")
def run_benchmark(benchmark: str, num_test_cases: int = 2, submitted_by: str = "unknown") -> dict:
    job_id = run_benchmark.request.id
    run_dir = RUNS_DIR / f"panel-{job_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(
        f'{{"benchmark": "{benchmark}", "num_test_cases": {num_test_cases}, '
        f'"submitted_by": "{submitted_by}", "started_at": "{datetime.now(timezone.utc).isoformat()}"}}'
    )

    if benchmark == "autonomous-uplift":
        result = _run_autonomous_uplift(run_dir, shots=num_test_cases)
    else:
        if benchmark not in _BENCHMARK_COMMANDS:
            return {"rc": 1, "error": f"unknown benchmark '{benchmark}'"}
        argv = [str(VENV_PY)] + _BENCHMARK_COMMANDS[benchmark](str(run_dir), num_test_cases)
        proc = subprocess.run(argv, cwd=REPO_DIR, capture_output=True, text=True)
        (run_dir / "run.log").write_text(proc.stdout + proc.stderr)
        result = {"rc": proc.returncode, "log_path": str(run_dir / "run.log")}

    result["run_dir"] = str(run_dir)
    return result
```

---

### cse-panel-11-worker-compose

```yaml
id: cse-panel-11-worker-compose
title: Add the Celery worker service to cse-controller's docker-compose.yml
depends_on: [cse-panel-10-worker-tasks]

change: >
  Edit terraform/lxc/stacks/cse-controller/docker-compose.yml to add a
  second service, `worker`, sharing the existing controller service's
  image and /srv/cyberseceval bind mount, running the Celery worker
  command instead of sleep infinity. Do not modify the existing
  `controller` service at all.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-controller/docker-compose.yml
  forbidden_actions:
    - "Any change to the existing controller service block"
    - "Any docker compose up / provision.sh run -- authoring only in this step"

gates:
  - id: compose-config
    cmd: "docker compose -f terraform/lxc/stacks/cse-controller/docker-compose.yml config"
    expect: "exit 0"
    critical: true
  - id: controller-service-unchanged
    cmd: "grep -A5 '^  controller:' terraform/lxc/stacks/cse-controller/docker-compose.yml | grep -c 'sleep.*infinity'"
    expect: "output == 1"
    critical: true
```

Literal new content to append to
`terraform/lxc/stacks/cse-controller/docker-compose.yml` (the existing
`controller` service block stays exactly as-is; only this new block is
added under `services:`):

```yaml
  worker:
    image: harbor.lab.gibbsgreatly.xyz/dockerhub/library/python:3.10-slim
    container_name: cse-controller-worker
    volumes:
      - /srv/cyberseceval:/srv/cyberseceval
    working_dir: /srv/cyberseceval/repo/PurpleLlama
    command:
      - /srv/cyberseceval/.venv/bin/celery
      - -A
      - cse_tasks
      - worker
      - --loglevel=INFO
      - --concurrency=1
    environment:
      - CELERY_BROKER_URL=redis://${LAB_IP_CSE_PANEL}:6379/0
      - CELERY_RESULT_BACKEND=redis://${LAB_IP_CSE_PANEL}:6379/1
      - PYTHONPATH=/srv/cyberseceval/config
    env_file:
      - /srv/cyberseceval/config/worker.env
    restart: unless-stopped
```

---

### cse-panel-12-worker-deploy-playbook

```yaml
id: cse-panel-12-worker-deploy-playbook
title: Wire the worker into deploy-cse-controller.yml
depends_on: [cse-panel-11-worker-compose]

change: >
  Edit terraform/lxc/ansible/playbooks/deploy-cse-controller.yml: add a
  task installing celery and redis into the existing venv (pip install,
  same pattern as the existing CyberSecEval requirements install task),
  and a no_log task writing /srv/cyberseceval/config/worker.env containing
  OPENAI_API_KEY (templated from the OPENAI_API_KEY environment variable,
  mandatory), placed immediately after the existing "Install CyberSecEval's
  Python requirements" task.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-cse-controller.yml
  forbidden_actions:
    - "Any change to tasks unrelated to the worker/celery/worker.env"
    - "Any ansible-playbook run against a real host -- syntax-check only"

gates:
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ../../../with-secrets ansible-playbook --syntax-check playbooks/deploy-cse-controller.yml"
    expect: "exit 0"
    critical: true
  - id: worker_env_task_has_no_log
    cmd: "grep -B2 'worker.env' terraform/lxc/ansible/playbooks/deploy-cse-controller.yml | grep -c no_log"
    expect: "output >= 1"
    critical: true
```

Literal new tasks to insert into
`terraform/lxc/ansible/playbooks/deploy-cse-controller.yml` immediately
after the existing `- name: Install CyberSecEval's Python requirements
(idempotent, runs every deploy)` task:

```yaml
    - name: Install Celery/Redis client into the CyberSecEval venv (for the worker service)
      ansible.builtin.command:
        cmd: >-
          docker exec {{ cse_controller_container }}
          {{ cse_controller_venv_dir }}/bin/pip install celery==5.4.0 redis==5.2.1
      register: cse_controller_celery_install
      changed_when: "'Successfully installed' in cse_controller_celery_install.stdout"
      when: not ansible_check_mode

    - name: Write the worker's OpenAI API key env file (never logged)
      no_log: true
      ansible.builtin.copy:
        dest: /srv/cyberseceval/config/worker.env
        mode: "0600"
        content: "OPENAI_API_KEY={{ lookup('env', 'OPENAI_API_KEY') | mandatory('OPENAI_API_KEY must be set to deploy the worker') }}\n"
```

---

## Part C — Cross-zone firewall rule and the log-driver fix on existing stacks

### cse-panel-13-crosszone-firewall

```yaml
id: cse-panel-13-crosszone-firewall
title: Add the cse_seg -> mgmt_seg:6379 MikroTik firewall rule
depends_on: [cse-panel-01-stack-yaml]

change: >
  Create ansible/00-initial-setup/mikrotik-firewall-cse-panel-cross-zone.yml,
  modeled exactly on the proven forward-chain-anchor pattern already in
  ansible/00-initial-setup/mikrotik-firewall-cse-seg.yml (read/anchor/
  add-if-missing/re-read/assert), adding exactly one forward-chain rule:
  cse-controller's specific IP (192.168.100.70) to cse-panel-stack's IP
  on port 6379/tcp, placed before cse_seg's existing default-deny rule.

scope:
  allowed_paths:
    - ansible/00-initial-setup/mikrotik-firewall-cse-panel-cross-zone.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any change to mikrotik-firewall-cse-seg.yml itself -- this is a separate, additive rule file"
    - "Running this playbook against the real MikroTik -- authoring only in this step"

gates:
  - id: syntax-check
    cmd: "./with-secrets ansible-playbook --syntax-check ansible/00-initial-setup/mikrotik-firewall-cse-panel-cross-zone.yml"
    expect: "exit 0"
    critical: true
```

Literal content for
`ansible/00-initial-setup/mikrotik-firewall-cse-panel-cross-zone.yml`
(same structure as `mikrotik-firewall-cse-seg.yml`, narrowed to this one
new rule; uses the same `forward_drop_anchor` lookup, since this is a
`forward`-chain-only rule, not an `input`-chain one, so the earlier
wrong-anchor bug this repo already hit does not apply here):

```yaml
---
# One new cross-zone rule for the CyberSecEval control panel
# (docs/cyberseceval-panel/plan.md): cse-controller's Celery worker
# connects OUT to Redis in mgmt_seg -- this is the only direction, cse_seg
# never becomes reachable FROM mgmt_seg. Kept in its own file, separate
# from mikrotik-firewall-cse-seg.yml, since it is conceptually a
# cse-panel-stack concern, not a cse_seg-baseline one.

- name: Ensure the cse-panel cross-zone rule exists on the live MikroTik
  hosts: localhost
  gather_facts: false

  vars:
    mikrotik_host: "{{ lookup('env', 'MIKROTIK_HOST') | mandatory('MIKROTIK_HOST env var is required') }}"
    mikrotik_rest_base_url: "https://{{ mikrotik_host }}/rest"
    mikrotik_user: >-
      {{
        lookup('env', 'MIKROTIK_ADMIN')
        | default(lookup('env', 'MIKROTIK_USER'), true)
        | default('api-user', true)
      }}
    mikrotik_password: >-
      {{
        lookup('env', 'MIKROTIK_ADMIN_PASSWORD')
        | default(lookup('env', 'MIKROTIK_PASSWORD'), true)
      }}
    cse_controller_ip: "192.168.100.70"
    cse_panel_ip: "{{ lookup('env', 'LAB_IP_CSE_PANEL') | mandatory('LAB_IP_CSE_PANEL env var is required') }}"

    cse_panel_rule:
      comment: "cse-controller worker to cse-panel-stack Redis"
      chain: "forward"
      action: "accept"
      protocol: "tcp"
      src-address: "{{ cse_controller_ip }}"
      dst-address: "{{ cse_panel_ip }}"
      dst-port: "6379"

  pre_tasks:
    - name: Assert MikroTik password is set
      ansible.builtin.assert:
        that:
          - mikrotik_password | length > 0
        fail_msg: "Set MIKROTIK_ADMIN_PASSWORD or MIKROTIK_PASSWORD before running this playbook."

  tasks:
    - name: Read MikroTik firewall filter rules
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter"
        method: GET
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        return_content: true
        status_code: 200
      register: firewall_filters
      no_log: true

    - name: Find first forward drop/reject rule for ordered insertion
      ansible.builtin.set_fact:
        forward_drop_anchor: >-
          {{
            (firewall_filters.json
              | selectattr('chain', 'defined')
              | selectattr('chain', 'equalto', 'forward')
              | selectattr('action', 'defined')
              | selectattr('action', 'in', ['drop', 'reject'])
              | list)
            | first | default({})
          }}

    - name: Add the cse-panel cross-zone rule if missing
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter/add"
        method: POST
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        body_format: json
        body: "{{ cse_panel_rule | combine({'place-before': forward_drop_anchor['.id']}) }}"
        status_code: [200, 201]
      when:
        - forward_drop_anchor != {}
        - >-
          (firewall_filters.json
            | selectattr('comment', 'defined')
            | selectattr('comment', 'equalto', cse_panel_rule.comment)
            | list) | length == 0
      no_log: true

    - name: Re-read MikroTik firewall filter rules after apply
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter"
        method: GET
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        return_content: true
        status_code: 200
      register: firewall_filters_final
      no_log: true

    - name: Assert the cse-panel cross-zone rule exists
      ansible.builtin.assert:
        that:
          - >-
            firewall_filters_final.json
            | selectattr('comment', 'defined')
            | selectattr('comment', 'equalto', cse_panel_rule.comment)
            | list | length > 0
        fail_msg: "Expected cse-panel cross-zone rule was not found after apply."

    - name: Report cse-panel cross-zone rule confirmed present
      ansible.builtin.debug:
        msg: "cse-controller -> cse-panel-stack Redis rule confirmed present."
```

---

### cse-panel-14-log-driver-fix

```yaml
id: cse-panel-14-log-driver-fix
title: Add the missing syslog log-driver daemon.json task to cse-controller/cse-code-eval
depends_on: []

change: >
  Edit terraform/lxc/ansible/playbooks/deploy-cse-controller.yml and
  terraform/lxc/ansible/playbooks/deploy-cse-code-eval.yml: in each,
  insert the literal daemon.json task below (copied from
  deploy-netbox-stack.yml's own proven task, with the insecure-registries
  entry kept and log-driver/log-opts/storage-driver added, plus
  live-restore: true so a future Docker daemon restart here doesn't kill
  an in-flight Celery-driven benchmark run) as the very first task in the
  play, before "Create stack directory", with a matching "Restart Docker"
  handler and a flush_handlers task right after it. Note: live-restore
  keeps containers running across the restart, but does not reliably
  preserve an ad hoc `docker exec` session started before the restart
  (e.g. a manually-launched throwaway script) -- it protects the future
  Celery worker (the container's own long-lived process) specifically,
  not arbitrary exec sessions. Applying this task still restarts Docker
  on the host, so only run it when nothing important is mid-run there.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-cse-controller.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-code-eval.yml
  forbidden_actions:
    - "Any change to tasks unrelated to daemon.json/Docker restart"
    - "Any ansible-playbook run against a real host -- syntax-check only"

gates:
  - id: syntax-check-controller
    cmd: "cd terraform/lxc/ansible && ../../../with-secrets ansible-playbook --syntax-check playbooks/deploy-cse-controller.yml"
    expect: "exit 0"
    critical: true
  - id: syntax-check-code-eval
    cmd: "cd terraform/lxc/ansible && ../../../with-secrets ansible-playbook --syntax-check playbooks/deploy-cse-code-eval.yml"
    expect: "exit 0"
    critical: true
  - id: log-driver-present-both
    cmd: "grep -l 'log-driver.*syslog' terraform/lxc/ansible/playbooks/deploy-cse-controller.yml terraform/lxc/ansible/playbooks/deploy-cse-code-eval.yml | wc -l"
    expect: "output == 2"
    critical: true
```

Literal task to insert (identical in both files, adjust only the
`register` variable name to avoid colliding with any existing var of the
same name in that file — use `cse_controller_daemon_config` in
`deploy-cse-controller.yml` and `cse_code_eval_daemon_config` in
`deploy-cse-code-eval.yml`):

```yaml
    - name: Forward container logs to Graylog (log-driver gap fix, plan §cse-panel-14)
      ansible.builtin.copy:
        dest: /etc/docker/daemon.json
        mode: "0644"
        content: |
          {
            "log-driver": "syslog",
            "log-opts": {
              "syslog-address": "tcp://127.0.0.1:10514",
              "syslog-format": "rfc5424",
              "tag": "{% raw %}docker-{{.Name}}{% endraw %}"
            },
            "storage-driver": "overlay2",
            "live-restore": true
          }
      notify: Restart Docker

    - name: Flush handlers to apply Docker daemon config before stack deploy
      ansible.builtin.meta: flush_handlers
```

If either file does not already have a `handlers:` block with a
`Restart Docker` handler (`ansible.builtin.systemd: name=docker
state=restarted`), add one — check both files for this before assuming
it needs adding, since one may already have it from an earlier task.

---

## Operator-only actions (deliberately not step blocks)

These are first mutations of shared/production infrastructure, or
depend on a script the local-model execution loop cannot invoke — per
`docs/agent-design/step-packet-schema.md`, written as plain instructions
here, not fenced YAML:

1. After Part A/B's file-authoring steps land, `terragrunt apply` the new
   `cse-panel-stack` environment directory and run
   `scripts/provision.sh --stack cse-panel-stack`, then run the
   activate-edge phase so the EdgeManifest reconciler picks up
   `edge.yaml` (Traefik routes + Authentik proxy-provider) — same
   production approval flow as every other `pve` mutation this repo
   uses.
2. After Part B lands, redeploy `cse-controller`
   (`scripts/provision.sh --stack cse-controller`) so the worker service
   starts and picks up the new pip packages / `worker.env`.
3. After Part C's firewall step lands, run
   `ansible/00-initial-setup/mikrotik-firewall-cse-panel-cross-zone.yml`
   for real against the live MikroTik (needs `MIKROTIK_ADMIN_PASSWORD`) —
   a real production network mutation, same class as every other
   MikroTik change this implementation has made.
4. After Part C's log-driver step lands, redeploy both
   `cse-controller` and `cse-code-eval` to apply the new `daemon.json`
   (this restarts Docker on both LXCs — brief container interruption,
   worth doing deliberately rather than folding into an unattended
   automated run).
5. Verify end-to-end afterward the same way every other phase in this
   implementation was verified: submit one small real job through
   `panel-web`, confirm Flower shows it, confirm its output lands under
   `/srv/cyberseceval/runs/panel-<job-id>/`, and confirm the container
   logs for `cse-panel-web`/`cse-controller`/`cse-code-eval` are now
   actually showing up in Graylog — not just trusting each step's gate.
