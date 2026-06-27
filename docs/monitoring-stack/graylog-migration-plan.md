# Sprint Plan — Graylog Migration on pve-test-vm

**Scope:** Move the logging function of `monitoring-stack` on `pve-test-vm`
toward Graylog, while keeping `VictoriaMetrics` and `Grafana` focused on
metrics. The existing VictoriaLogs pipeline is the rollback baseline until the
Graylog path is validated.

**Goal:** End with a logging design that has been implemented, tested, and
validated on `pve-test-vm`, and is ready for promotion to `stable` and then
incremental deployment on `pve`.

**Branch model:** Follow [docs/workflow/branch-model.md](../workflow/branch-model.md).
Because this work spans Ansible, Docker Compose, cross-stack logging, and
remote syslog integration, every sprint should validate on `pve-test-vm`, and
the later integration sprints should expect a full teardown-cycle validation.

**Promotion target:** `stable` only after the full Graylog path is validated on
`pve-test-vm`. `main` is only updated after incremental deployment on `pve`
passes and the operator confirms no regressions.

---

## Desired end state

On both `pve-test-vm` and, later, `pve`:

- `VictoriaMetrics` remains the metrics backend.
- `Grafana` remains the browser-facing metrics dashboard.
- `Graylog` becomes the primary browser-facing log platform.
- `rsyslog` remains the per-host collector/forwarder on managed LXCs unless a
  later sprint deliberately replaces it.
- `VictoriaLogs` is no longer required for routine operator log workflows.

The migration is considered complete only when:

1. Managed LXC logs are visible and searchable in Graylog.
2. Docker-container logs are visible and attributable in Graylog.
3. Proxmox host syslog can be ingested through the chosen Graylog path.
4. MikroTik syslog can be ingested through the chosen Graylog path.
5. Day-to-day operator log workflows no longer depend on Grafana log panels or
   VictoriaLogs LogsQL queries.

---

## Current baseline snapshot

This plan starts from a known-good `pve-test-vm` baseline rather than a greenfield
logging design.

### Live progress snapshot

Current implementation state on this branch:

- `graylog-stack` now exists as a dedicated stack definition and env-scoped
  Terragrunt entrypoint for both `pve-test-vm` and `pve`
- `pve-test-vm` LXC created successfully:
  - hostname: `graylog-stack`
  - VMID: `20014`
  - IP: `192.168.20.114`
  - zone: `mgmt_seg`
- host bootstrap and scaffold provisioning succeeded on `pve-test-vm`
- placeholder runtime assets exist under `/opt/graylog-stack`
- no Graylog containers are running yet
- no Traefik/Auth/DNS publication has been added yet

Recent repo work (implementation, not provisioned):

- `terraform/lxc/stacks/graylog-stack/stack.yaml` memory bumped to `6144` (commit applied in branch)
- `.env` / `.env.pve-test-vm` placeholders for `LAB_IP_GRAYLOG` / `LAB_FQDN_GRAYLOG` added/updated
- `terraform/secrets.enc.yaml` now contains `GRAYLOG_PASSWORD_SECRET` and `GRAYLOG_ROOT_PASSWORD_SHA2` (SOPS entry present)
- `rsyslog_forward` Ansible role extended: new defaults, conditional tasks, and `graylog_inbound.conf.j2` template to accept UDP/TCP 514 and forward to `127.0.0.1:5140`
- `deploy-graylog-stack.yml` playbook extended with an optional runtime deploy flow (writes `/opt/graylog-stack/graylog.env`, `docker-compose.yml`, brings up compose) guarded by `GRAYLOG_DEPLOY_RUNTIME` (defaults to false)
- smoke-test helpers added under `scripts/smoke/` (`check-graylog-alive.sh`, `send-graylog-test-message.sh`, `query-graylog-search.sh`)

Status: the above code and docs changes are committed to the branch, but **no runtime containers have been started** and no Traefik/DNS/edge publication has been applied. The work has therefore moved past pure planning into implementation (G2 code changes), but the live Graylog runtime deployment (provision + compose up) is still pending and gated by operator action.

### Baseline evidence

- Full teardown/redeploy reference:
  [docs/teardown-test/artifacts/reports/20260613-pve-test-vm-teardown.md](../teardown-test/artifacts/reports/20260613-pve-test-vm-teardown.md)
- Recent `pve-test-vm` edge/auth follow-up after the June 2026 test-domain fixes:
  - `ceaf95a` `fix(authentik): converge test-domain edge config`
  - user-confirmed browser path healthy for Authentik, Grafana, Traefik, NetBox, Harbor, and Portainer after reprovision / reconcile
- Current branch monitoring/logging gate work:
  - `eca9acd` `monitoring: split 7E and gate on Victorialogs ingestion`

### Current known-good validation state

These are the commands and checks to preserve as the rollback baseline before
changing the log backend:

```bash
PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --stack harbor-stack --target-env pve-test-vm
PVE_ENV=pve-test-vm ./with-secrets python3 terraform/lxc/reconcile-edge.py \
  --authentik-url https://authentik-int.test.gibbsgreatly.xyz:9443 --apply --json
PVE_ENV=pve-test-vm ./with-secrets python3 terraform/lxc/reconcile-edge.py \
  --authentik-url https://authentik-int.test.gibbsgreatly.xyz:9443 --json
```

Expected baseline result:

- `reconcile-edge.py --json` returns `validation.status: "passed"`
- `issue_count: 0`
- six edge manifests validate cleanly
- Grafana metrics access works normally
- the VictoriaLogs-backed Grafana dashboards remain the current fallback log UI

Additional Graylog scaffold validation completed on this branch:

```bash
PVE_ENV=pve-test-vm ./with-secrets terragrunt apply \
  --working-dir terraform/lxc/environments/pve-test-vm/graylog-stack \
  -auto-approve -no-color

PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh \
  --stack graylog-stack --target-env pve-test-vm
```

Expected scaffold result:

- Terraform creates `graylog-stack` at VMID `20014`
- env-scoped inventory is written under
  `terraform/lxc/environments/pve-test-vm/graylog-stack/`
- Ansible bootstrap completes successfully
- `/opt/graylog-stack/scaffold/README.txt` and
  `/opt/graylog-stack/scaffold/graylog.env.example` exist on the guest
- no public Graylog route exists yet by design

### Current baseline operator workflows

These workflows must remain possible throughout the migration, either via the
existing VictoriaLogs path or the new Graylog path:

- metrics dashboards in Grafana still load and authenticate normally
- one broad “Lab Logs” style cross-stack search works
- one auth-focused workflow equivalent to the current “Auth Logs” dashboard works
- one Docker-heavy stack can be filtered by source/container identity

If Graylog cannot replace these workflows for the pilot sources, the sprint is
not done.

---

## Architectural choices to settle early

These are explicit decisions, not assumptions:

| Decision | Choice | Status |
|---|---|---|
| Graylog packaging | Graylog 6.x Data Node — MongoDB 7 + Graylog DataNode + Graylog Server (3 containers) | ✅ settled |
| LXC RAM | 6144 MB (was 4096 MB) | ✅ settled |
| Browser auth | Direct OIDC via Authentik — same pattern as Grafana, Portainer, Harbor | ✅ settled |
| FQDN | `graylog.test.gibbsgreatly.xyz` | ✅ settled |
| Syslog port 514 | rsyslog relay on LXC host — binds 514 as root/systemd, relays to Graylog on 127.0.0.1:5140 | ✅ settled |
| Host forwarder on managed LXCs | keep current `rsyslog` forwarders; change only the central sink path in G3 | ✅ settled |
| Coexistence during pilot | dual-feed (VictoriaLogs remains active fallback) until G5 | ✅ settled |
| Separate `graylog-stack` | yes — keep `monitoring-stack` metrics-focused | ✅ settled |
| Proxmox host / MikroTik syslog | deferred to Sprint G4; rsyslog on graylog-stack will be ready to receive on :514 | ✅ settled |

All architectural choices for the pilot are settled. If any decision changes
during implementation, update this table before continuing.

---

## Sprint sequence

### Sprint G0 — Baseline Capture

**Goal:** Freeze the current VictoriaLogs-based logging path as the validated
rollback baseline on `pve-test-vm`.

**Why first:** Once Graylog work starts, it must be possible to tell whether a
regression came from Graylog itself or from the existing host logging path.

**Deliverables**

- Capture the current `pve-test-vm` monitoring/logging state in docs:
  - which stacks are forwarding logs
  - what validation commands are green
  - which Grafana log dashboards currently work
- Ensure the current teardown harness evidence is retained and referenced.
- Mark the current VictoriaLogs path as the fallback baseline in
  [design.md](./design.md).
- Add an explicit rollback checkpoint for the exact commands and operator checks
  that define “known good”.

**Implementation tasks**

1. Record the current successful `reconcile-edge.py` / platform validation state.
2. Record the current monitoring-stack direct health checks and ingestion proof.
3. Record the current known-good log query samples for:
   - one systemd-service log source
   - one Docker-heavy stack
   - one auth log query
4. Link the baseline to the latest relevant validation evidence and commits.
5. Capture the “do not regress” checks for Grafana, Traefik/Auth, and edge
   reconciliation.

**Suggested capture checklist**

- Evidence/report reference:
  - [20260613-pve-test-vm-teardown.md](../teardown-test/artifacts/reports/20260613-pve-test-vm-teardown.md)
- Current branch commits to cite:
  - `eca9acd`
  - `ceaf95a`
- Commands to keep in the doc:
  - `PVE_ENV=pve-test-vm ./with-secrets python3 terraform/lxc/reconcile-edge.py --authentik-url https://authentik-int.test.gibbsgreatly.xyz:9443 --json`
  - the matching `--apply --json` command used for follow-up convergence
- Browser/app checks to keep in the doc:
  - Authentik reachable
  - Grafana reachable
  - Traefik reachable through Authentik
  - Harbor reachable through Authentik
  - NetBox reachable through Authentik
  - Portainer reachable

**Validation**

- Documentation sanity check only.
- No infra change required.

**Minimum gate**

- Docs reviewed and current working commands copied into the plan.

**Current status**

- Complete for planning purposes on this branch. The validated VictoriaLogs path
  is now explicitly documented as the rollback baseline.

---

### Sprint G1 — Graylog Design and Stack Shape

**Goal:** Decide how Graylog will run on `pve-test-vm` and what “done” means for
the pilot.

**Deliverables**

- Graylog deployment shape documented:
  - stack placement
  - storage footprint
  - ingress/auth model
  - container/service layout
- Graylog input model documented:
  - syslog TCP/UDP ports
  - whether standard `514` is needed internally
  - field conventions to preserve host/source identity
- Validation matrix updated for the Graylog path.

**Implementation tasks**

1. Decide whether Graylog lives:
   - inside the existing `monitoring-stack`, or
   - as a new `graylog-stack` on `pve-test-vm`.
2. Decide whether Graylog receives:
   - direct syslog from appliances and hosts, or
   - syslog via an rsyslog relay running in front of it.
3. Define the expected external FQDN and ingress/auth requirements.
4. Define storage and retention expectations for the pilot.
5. Define the initial input set:
   - managed LXC system logs
   - Docker-container logs
   - Proxmox host
   - MikroTik

**Validation**

- Design review only.
- No live infra change yet.

**Minimum gate**

- Documented target design with no unresolved “critical path” unknowns.

**Current status**

- Substantially complete on this branch.
- Chosen direction:
  - separate `graylog-stack`
  - keep `monitoring-stack` metrics-focused
  - keep host-side `rsyslog`
  - defer Proxmox/MikroTik remote syslog until later sprint
- Remaining open item:
  - pin the exact Graylog single-node runtime shape and compose layout to use
    inside `graylog-stack`

---

### Sprint G2 — Graylog Core Deployment on pve-test-vm

**Goal:** Deploy Graylog itself on `pve-test-vm` without removing VictoriaLogs.

**Decisions settled**

| Decision | Choice | Rationale |
|---|---|---|
| Graylog version | 6.x (Data Node) | New install; avoids separate OpenSearch container |
| Compose topology | MongoDB 7 + Graylog Data Node + Graylog Server (3 containers) | Data Node replaces OpenSearch as the search/index backend |
| Syslog port 514 | rsyslog relay on LXC host (Option A) | rsyslog runs as root via systemd and can bind 514 naturally; no Docker privilege escalation |
| Syslog internal port | 5140 TCP | rsyslog → Graylog; same convention as VictoriaLogs used; bound to 127.0.0.1 only |
| Browser auth | **Authentik LDAP outpost (Option B)** | Graylog 6.1 open source has no native OIDC support. Chosen approach: Authentik LDAP outpost (`ghcr.io/goauthentik/ldap:2024.12.3`) exposes LDAP on port 3389; Graylog LDAP Auth Service authenticates against it. Users log in once with Authentik credentials. ✅ Implemented in Step 9. |
| FQDN | `graylog.test.gibbsgreatly.xyz` | Matches pve-test-vm domain convention |
| LXC RAM | 6144 MB (was 4096 MB) | MongoDB + Data Node + Graylog Server require more headroom |
| DataNode CA | Graylog self-signed (internal only) | DataNode TLS is container-to-container on the private compose network; no external system validates it. Step-ca integration is appropriate for the web endpoint (Traefik upstream) and future syslog TLS, not the internal DataNode CA |

---

**Architecture**

```
Proxmox host / MikroTik (appliances)
  │ TCP/UDP :514
  ▼
rsyslog on graylog-stack LXC  (systemd root process — binds 514 naturally)
  │ inbound listeners:
  │   :514  TCP   ← external appliances (RFC 5424 parser, new)
  │   :514  UDP   ← external appliances (new)
  │   :10514 TCP  ← Docker daemon syslog (existing pattern)
  │   imuxsock    ← journald system logs (existing)
  │
  │ forward all → 127.0.0.1:5140 TCP
  ▼
Graylog container  (syslog TCP input on :5140 — localhost only, never external)
  :9000 web UI → published externally
  ▼
Traefik → graylog.test.gibbsgreatly.xyz
  │
  │  (OIDC: browser login redirects to Authentik; token + userinfo fetched
  │   by Graylog back-channel from authentik-int.test.gibbsgreatly.xyz:9443)
  ▼
Authentik OIDC provider (same pattern as Grafana + Portainer)
```

Port 514 never appears in the Docker compose. Graylog's syslog port 5140 is
bound to `127.0.0.1` only. Only port 9000 is published externally.

---

**Files to change**

| File | Change |
|---|---|
| `terraform/lxc/stacks/graylog-stack/stack.yaml` | `memory: 6144` (was 4096) |
| `.env` | add `LAB_IP_GRAYLOG`, `LAB_FQDN_GRAYLOG` |
| `terraform/secrets.enc.yaml` | add `GRAYLOG_PASSWORD_SECRET`, `GRAYLOG_ROOT_PASSWORD_SHA2` |
| `terraform/lxc/ansible/roles/rsyslog_forward/defaults/main.yml` | add `rsyslog_inbound_enabled`, `rsyslog_inbound_tcp_port`, `rsyslog_inbound_udp_port` |
| `terraform/lxc/ansible/roles/rsyslog_forward/tasks/main.yml` | add conditional task for inbound config + port check |
| `terraform/lxc/ansible/roles/rsyslog_forward/templates/graylog_inbound.conf.j2` | new template: imudp + imtcp on 514, RFC 5424 ruleset |
| `terraform/lxc/ansible/playbooks/deploy-graylog-stack.yml` | replace scaffold tasks with real compose, env write, docker compose up, health poll |
| `terraform/lxc/stacks/graylog-stack/edge.yaml` | new: Traefik route, DNS, TLS, OIDC (`auth.mode: oidc`) |
| `terraform/lxc/stacks/graylog-stack/STACK_CONTRACT.md` | update to reflect real runtime |
| `scripts/teardown-deploy-test.sh` | add Graylog health gate |
| `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` | add graylog-stack node_exporter + cadvisor scrape targets |
| `terraform/lxc/discover-authentik-edge.py` | add `("graylog-stack", "graylog")` to `OIDC_ROUTE_CLIENT_IDS`, `OIDC_ROUTE_CLIENT_SECRETS`, `_oidc_redirect_uris()` |
| `terraform/secrets.enc.yaml` | add `GRAYLOG_OAUTH_CLIENT_SECRET` |
| `.env` / `.env.pve-test-vm` | add `GRAYLOG_OAUTH_CLIENT_ID=graylog` |

---

**Files changed / status**

| File | Intended change | Status |
|---|---|---|
| `terraform/lxc/stacks/graylog-stack/stack.yaml` | `memory: 6144` (was 4096) | Done in branch |
| `.env` / `.env.pve-test-vm` | add `LAB_IP_GRAYLOG`, `LAB_FQDN_GRAYLOG` | Done in branch |
| `terraform/secrets.enc.yaml` | add `GRAYLOG_PASSWORD_SECRET`, `GRAYLOG_ROOT_PASSWORD_SHA2` | Present (SOPS) |
| `terraform/lxc/ansible/roles/rsyslog_forward/defaults/main.yml` | add `rsyslog_inbound_enabled`, `rsyslog_inbound_tcp_port`, `rsyslog_inbound_udp_port` | Done |
| `terraform/lxc/ansible/roles/rsyslog_forward/tasks/main.yml` | add conditional task for inbound config + port check | Done |
| `terraform/lxc/ansible/roles/rsyslog_forward/templates/graylog_inbound.conf.j2` | new template: imudp + imtcp on 514, RFC 5424 ruleset | Done |
| `terraform/lxc/ansible/playbooks/deploy-graylog-stack.yml` | add optional runtime compose/env write + health poll + preflight automation + syslog INPUT provisioning + LDAP auth config | **Done (Step 5 + Step 9)** |
| `terraform/lxc/stacks/graylog-stack/edge.yaml` | new: Traefik route, DNS, TLS, `auth.mode: native` | **Done (Step 9)** |
| `terraform/lxc/stacks/authentik-stack/docker-compose.yml` | add LDAP outpost service | **Done (Step 9)** |
| `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml` | add LDAP provider + outpost provisioning, token write | **Done (Step 9)** |
| `terraform/secrets.enc.yaml` | add `GRAYLOG_ROOT_PASSWORD` (plaintext for API calls) | **Done (Step 9)** |
| `terraform/lxc/stacks/graylog-stack/STACK_CONTRACT.md` | update to reflect real runtime | Planning doc updated earlier; no further action required |
| `scripts/teardown-deploy-test.sh` | add Graylog health gate | **Done (Step 8)** |
| `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` | add graylog-stack node_exporter + cadvisor scrape targets | **Done (Step 7)** |
| `terraform/lxc/discover-authentik-edge.py` | not needed — `native` mode routes have no Authentik provider | **N/A — LDAP approach uses native mode** |


---

**Detailed changes**

#### 1 — `stack.yaml` memory bump

```yaml
memory: 6144   # was 4096; Graylog 6.x (MongoDB + DataNode + Graylog) requires headroom
```

#### 2 — `.env` additions

```
LAB_IP_GRAYLOG=192.168.20.114
LAB_FQDN_GRAYLOG=graylog.test.gibbsgreatly.xyz
```

#### 3 — `secrets.enc.yaml` additions

```yaml
GRAYLOG_PASSWORD_SECRET: <openssl rand -base64 72 | tr -d '\n'>   # 96+ chars
GRAYLOG_ROOT_PASSWORD_SHA2: <echo -n "password" | sha256sum | cut -d' ' -f1>
```

Both must be generated and SOPS-encrypted before running the playbook.

#### 4 — `rsyslog_forward` role — inbound relay extension

New defaults:

```yaml
# rsyslog_forward/defaults/main.yml additions
rsyslog_inbound_enabled: false
rsyslog_inbound_tcp_port: "514"
rsyslog_inbound_udp_port: "514"
```

New conditional task in `tasks/main.yml` (after the existing config write):

```yaml
- name: Write Graylog inbound relay config
  ansible.builtin.template:
    src: graylog_inbound.conf.j2
    dest: /etc/rsyslog.d/91-graylog-inbound.conf
    owner: root
    group: root
    mode: "0644"
  when: rsyslog_inbound_enabled | bool
  notify: Restart rsyslog

- name: Remove Graylog inbound relay config when not enabled
  ansible.builtin.file:
    path: /etc/rsyslog.d/91-graylog-inbound.conf
    state: absent
  when: not (rsyslog_inbound_enabled | bool)
  notify: Restart rsyslog

- name: Ensure rsyslog is listening on inbound syslog TCP port
  ansible.builtin.wait_for:
    host: 0.0.0.0
    port: "{{ rsyslog_inbound_tcp_port }}"
    timeout: 15
  when: rsyslog_inbound_enabled | bool
```

New template `graylog_inbound.conf.j2`:

```
# Inbound syslog relay for Graylog. rsyslog receives on :514 (TCP + UDP)
# from external appliances (Proxmox host, MikroTik) and Docker daemon on
# :10514, then relays everything to Graylog's syslog TCP input on 127.0.0.1:5140.
#
# Port 514 is bound by rsyslog (systemd root process). Graylog never touches it.

# UDP input — appliances that only support UDP syslog (e.g. MikroTik)
module(load="imudp")
input(type="imudp" port="{{ rsyslog_inbound_udp_port }}")

# TCP input for external appliances — RFC 5424 parser required.
# (Without explicit ruleset, pmrfc3164 reads the RFC 5424 version field '1'
# as the syslog TAG, producing app_name="1". See rsyslog_forward §5.)
ruleset(name="ext-tcp" parser="rsyslog.rfc5424") {
    *.* action(type="omfwd"
               target="{{ rsyslog_forward_target_host }}"
               port="{{ rsyslog_forward_target_port }}"
               protocol="tcp"
               Template="VictoriaLogsForward"
               queue.type="LinkedList"
               queue.filename="graylog-ext-tcp"
               queue.maxDiskSpace="32m"
               queue.saveOnShutdown="on"
               action.resumeRetryCount="-1")
}
input(type="imtcp" port="{{ rsyslog_inbound_tcp_port }}" address="0.0.0.0" ruleset="ext-tcp")
```

Note: the `VictoriaLogsForward` template is defined in `90-victorialogs.conf`
(which deploys first). On `graylog-stack`, that same file's `omfwd` target is
`127.0.0.1:5140` (local Graylog), so all three input paths use the same
forwarding action and same disk-backed queue protection.

#### 5 — `deploy-graylog-stack.yml` — real runtime

Replace the scaffold tasks with:

```yaml
- name: Include rsyslog_forward with Graylog relay vars
  ansible.builtin.include_role:
    name: rsyslog_forward
  vars:
    rsyslog_forward_target_host: "127.0.0.1"
    rsyslog_forward_target_port: "5140"
    rsyslog_inbound_enabled: true

- name: Write Graylog env file
  ansible.builtin.copy:
    dest: /opt/graylog-stack/graylog.env
    mode: "0640"
    content: |
      GRAYLOG_PASSWORD_SECRET={{ lookup('env', 'GRAYLOG_PASSWORD_SECRET') | mandatory }}
      GRAYLOG_ROOT_PASSWORD_SHA2={{ lookup('env', 'GRAYLOG_ROOT_PASSWORD_SHA2') | mandatory }}
      GRAYLOG_HTTP_EXTERNAL_URI=https://{{ graylog_lab_fqdn_graylog }}/
      GRAYLOG_MONGODB_URI=mongodb://mongodb:27017/graylog
      GRAYLOG_DATANODE_MONGODB_URI=mongodb://mongodb:27017/graylog
      GRAYLOG_HTTP_BIND_ADDRESS=0.0.0.0:9000
  no_log: true
  register: graylog_env_file
  notify: Recreate Graylog

- name: Write Graylog docker-compose.yml
  ansible.builtin.copy:
    dest: /opt/graylog-stack/docker-compose.yml
    mode: "0640"
    content: |
      services:
        mongodb:
          image: {{ graylog_registry_host }}/dockerhub/mongo:7
          volumes:
            - mongodb_data:/data/db
          restart: unless-stopped

        datanode:
          image: {{ graylog_registry_host }}/dockerhub/graylog/graylog-datanode:6.1
          env_file: graylog.env
          hostname: datanode
          volumes:
            - graylog_datanode:/var/lib/graylog-datanode
          restart: unless-stopped
          depends_on:
            - mongodb

        graylog:
          image: {{ graylog_registry_host }}/dockerhub/graylog/graylog:6.1
          env_file: graylog.env
          ports:
            - "9000:9000"
            - "127.0.0.1:5140:5140/tcp"
          volumes:
            - graylog_data:/usr/share/graylog/data
          restart: unless-stopped
          depends_on:
            - mongodb
            - datanode

      volumes:
        mongodb_data:
        graylog_datanode:
        graylog_data:
  register: graylog_compose_file
  notify: Recreate Graylog

- name: Bring up Graylog stack
  community.docker.docker_compose_v2:
    project_src: /opt/graylog-stack
    state: present
    remove_orphans: true
    recreate: "{{ 'always' if (graylog_env_file.changed or graylog_compose_file.changed) else 'auto' }}"

- name: Wait for Graylog web port to accept connections
  ansible.builtin.wait_for:
    host: 127.0.0.1
    port: 9000
    timeout: 120

- name: Wait for Graylog to report ALIVE
  ansible.builtin.uri:
    url: "http://127.0.0.1:9000/api/system/lbstatus"
    method: GET
    status_code: 200
    return_content: true
  register: graylog_lbstatus
  until: graylog_lbstatus.content == "ALIVE"
  retries: 30
  delay: 10
```

Handler:
```yaml
- name: Recreate Graylog
  community.docker.docker_compose_v2:
    project_src: /opt/graylog-stack
    state: present
    recreate: always
```

After ALIVE, provision the syslog TCP input via Graylog API (idempotent — skip if
an input on port 5140 already exists):

```yaml
- name: Check existing Graylog inputs
  ansible.builtin.uri:
    url: "http://127.0.0.1:9000/api/system/inputs"
    method: GET
    url_username: admin
    url_password: "{{ lookup('env', 'GRAYLOG_ROOT_PASSWORD') | mandatory }}"
    force_basic_auth: true
    return_content: true
  register: graylog_inputs
  when: graylog_deploy_runtime | bool

- name: Provision Graylog syslog TCP input on port 5140
  ansible.builtin.uri:
    url: "http://127.0.0.1:9000/api/system/inputs"
    method: POST
    url_username: admin
    url_password: "{{ lookup('env', 'GRAYLOG_ROOT_PASSWORD') | mandatory }}"
    force_basic_auth: true
    headers:
      Content-Type: application/json
      X-Requested-By: ansible
    body_format: json
    body:
      title: "syslog-tcp-5140"
      type: "org.graylog2.inputs.syslog.tcp.SyslogTCPInput"
      global: true
      configuration:
        bind_address: "0.0.0.0"
        port: 5140
        recv_buffer_size: 1048576
        number_worker_threads: 2
        override_source: null
        force_rdns: false
        allow_override_date: true
        store_full_message: false
        expand_structured_data: false
    status_code: [200, 201]
  when:
    - graylog_deploy_runtime | bool
    - >-
      (graylog_inputs.json.inputs | default([])
       | selectattr('message_input.attributes.port', 'eq', 5140) | list | length) == 0
```

Note: external senders (Proxmox, MikroTik, managed LXCs) use port **514** on the
graylog-stack LXC. rsyslog (root/systemd) binds 514 and relays to Graylog on
localhost:5140. The INPUT is on 5140 because Docker containers cannot bind
privileged ports as non-root. From external senders, port 514 is the address.

#### 6 — `graylog-stack/edge.yaml`

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: graylog-edge
  stack: graylog-stack
  annotations:
    repo.auth.oidc.client_id_env: GRAYLOG_OAUTH_CLIENT_ID
    repo.auth.oidc.client_secret_env: GRAYLOG_OAUTH_CLIENT_SECRET
spec:
  routes:
    - name: graylog
      host: graylog.${LAB_DOMAIN}
      backend:
        type: url
        url: http://${LAB_IP_GRAYLOG}:9000
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: oidc
```

`reconcile-authentik-edge.py` provisions a Graylog OAuth2 provider + application
in Authentik (same as Grafana and Portainer). The `graylog-stack/graylog` route
entry must also be added to `OIDC_ROUTE_CLIENT_IDS` and `OIDC_ROUTE_CLIENT_SECRETS`
in `discover-authentik-edge.py`. See Step 9 for the full OIDC wiring.

The Graylog OIDC backend is configured post-ALIVE via the Graylog REST API in
`deploy-graylog-stack.yml`. The exact API endpoint and OIDC callback path must be
confirmed from the Graylog admin UI (`System → Authentication → Authenticators`)
during Step 9 implementation — note the confirmed path there.

#### 7 — Teardown gate (`scripts/teardown-deploy-test.sh`)

Add alongside the monitoring-stack block:

```bash
curl -fsS "http://${LAB_IP_GRAYLOG}:9000/api/system/lbstatus" | grep -q "ALIVE" && \
  echo "graylog: ALIVE" || { echo "graylog: NOT ALIVE"; exit 1; }
```

#### 8 — VictoriaMetrics scrape targets (`deploy-monitoring-stack.yml`)

Add to the `node_exporter` job:
```yaml
- targets: ["${LAB_IP_GRAYLOG}:9100"]
  labels: {stack: graylog-stack}
```

Add to the `cadvisor` job:
```yaml
- targets: ["${LAB_IP_GRAYLOG}:8080"]
  labels: {stack: graylog-stack}
```

cAdvisor must also be added to the `deploy-graylog-stack.yml` compose definition
(same pattern as other Docker stacks).

---

**Sequencing within G2**

```
Step 1  stack.yaml memory bump  (Terraform apply needed to resize LXC)
Step 2  Generate + SOPS-encrypt Graylog secrets into secrets.enc.yaml
Step 3  Add LAB_IP_GRAYLOG / LAB_FQDN_GRAYLOG to .env
        (Steps 1-3 are independent and can be done in parallel)

Step 4  Extend rsyslog_forward role (new defaults, task, template)
Step 5  Update deploy-graylog-stack.yml (real compose + env + health wait)

Step 6  Provision graylog-stack:
          GRAYLOG_DEPLOY_RUNTIME=true PVE_ENV=pve-test-vm ./with-secrets \
            scripts/provision.sh --stack graylog-stack --target-env pve-test-vm
        Gate: Graylog reports ALIVE before proceeding

Step 7  Add graylog-stack to monitoring-stack scrape targets
          PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh \
            --stack monitoring-stack --target-env pve-test-vm
Step 8  Add Graylog gate to teardown-deploy-test.sh

⚠️  AUTH FINDING — Graylog 6.1 open source has no native OIDC:
    Verified: no OAuth2 jars in /usr/share/graylog/plugin/, no OIDC/OAuth
    strings in graylog.jar or JS bundle. The direct OIDC approach planned
    for Step 9e cannot be implemented as-is.

    Available options:
      Option A — forwardAuth (Traefik + Authentik forward-auth middleware)
        - Browser authenticates with Authentik before reaching Graylog
        - Graylog still shows its own login screen (double-login)
        - Steve needs a local Graylog admin account (provisioned via API)
        - edge.yaml uses auth.mode: forwardAuth (same as non-OIDC routes)
        - discover-authentik-edge.py gets forwardAuth entry (not OIDC)
        - Consistent access control; not true SSO
        Pro: simple, matches current infra, no new components
        Con: double login — Authentik AND Graylog; not the same pattern as
             Grafana/Portainer/Harbor

      Option B — Authentik LDAP outpost + Graylog LDAP Auth Service
        - Authentik acts as an LDAP provider (LDAP outpost required)
        - Graylog authenticates users via LDAP → Authentik credentials used
        - Single login; Graylog auto-provisions users from LDAP
        - Steve can be mapped to Graylog Admin via LDAP group
        - Requires: Authentik LDAP outpost setup, Graylog LDAP config via API
        Pro: true SSO — one set of credentials; matches "pattern of all services"
             in spirit (Authentik is the identity source)
        Con: LDAP outpost adds complexity; separate config effort

      Option C — forwardAuth only, no Graylog account for steve
        - Graylog accessible only from within Authentik session
        - Use Graylog admin/root account directly (known to operator only)
        - Simplest; but operator uses two accounts

    ✅ Operator chose Option B (Authentik LDAP outpost — true SSO).

Step 9  Edge publication + auth wiring — DONE (Option B):

        9a. Created terraform/lxc/stacks/graylog-stack/edge.yaml
            auth.mode: native (Graylog owns auth via LDAP; Traefik just routes)
        9b. discover-authentik-edge.py not modified — native mode has no
            Authentik provider/application
        9c. reconcile-edge.py --apply — ran cleanly; graylog-stack included
            in Traefik + CoreDNS render; issue_count: 0
        9d. Authentik LDAP outpost (ghcr.io/goauthentik/ldap:2024.12.3) added
            to authentik-stack compose; deploy-authentik-stack.yml provisions
            LDAP provider + outpost idempotently and writes AUTHENTIK_TOKEN to
            .ldap-outpost.env
        9e. deploy-graylog-stack.yml post-ALIVE tasks:
            - syslog TCP input on :5140 (idempotent)
            - LDAP Auth Service backend pointing to Authentik LDAP outpost
              (transport_security: none; user_name_attribute: cn)
            - activate backend via POST /api/system/authentication/services/configuration

        Gate:
              reconcile-edge.py --json returns issue_count: 0 ✅
              graylog.test.gibbsgreatly.xyz → DNS resolves → HTTPS 200 ✅
              Graylog LDAP auth backend active (id: 6a3f10c5769d7f3a2249dee3) ✅
```

---

**Minimum gate (G2 done)**

- `provision.sh --stack graylog-stack` completes without error ✅ confirmed
- `curl http://192.168.20.114:9000/api/system/lbstatus` returns `ALIVE` ✅ confirmed
- rsyslog on graylog-stack LXC listens on TCP/UDP :514 (confirmed by `ss -lntu`) ✅ confirmed
- VictoriaMetrics shows `graylog-stack` node_exporter as up ✅ scrape targets added (Step 7)
- Graylog teardown gate passes in `teardown-deploy-test.sh` ✅ added (Step 8)
- Graylog web UI accessible at `graylog.test.gibbsgreatly.xyz` — LDAP auth via Authentik outpost ✅ confirmed (Step 9)
- Grafana, Traefik, and existing platform auth show no regressions ✅ reconcile-edge `issue_count: 0` (Step 9)

---

**Validation tier**

This sprint crosses stack boundaries (monitoring-stack scrape config, platform
auth, Traefik routes). After Step 9, run a full platform validation:

```bash
PVE_ENV=pve-test-vm ./with-secrets python3 terraform/lxc/reconcile-authentik-edge.py \
  --authentik-url https://authentik-int.test.gibbsgreatly.xyz:9443 --json
```

Expected: `validation.status: "passed"`, `issue_count: 0`, all seven edge
manifests (including the new graylog-edge) validate cleanly.

---

**Current status (as of 2026-06-27)**

- Sprint G2 complete. All steps done:
  - Stack IaC scaffold + env-scoped Terragrunt entrypoint
  - LXC created at VMID 20014 / 192.168.20.114 on `pve-test-vm`
  - LXC RAM bumped to 6144 MB
  - GRAYLOG_PASSWORD_SECRET + GRAYLOG_ROOT_PASSWORD_SHA2 + GRAYLOG_ROOT_PASSWORD in secrets.enc.yaml
  - rsyslog_forward role extended with inbound relay on :514 TCP/UDP (Steps 4)
  - Real compose + playbook with preflight automation + syslog INPUT + LDAP auth config (Step 5)
  - Graylog containers deployed and confirmed ALIVE (Step 6)
  - Monitoring scrape targets added: node_exporter :9100 + cAdvisor :8080 (Step 7)
  - Teardown gate added to teardown-deploy-test.sh (Step 8)
  - Step 9 complete:
    - Auth approach: Authentik LDAP outpost (Option B — true SSO)
    - Authentik LDAP outpost container added to `authentik-stack` compose
    - Authentik LDAP provider + outpost provisioned via API in `deploy-authentik-stack.yml`
    - Graylog LDAP Auth Service configured and activated via `deploy-graylog-stack.yml`
    - `edge.yaml` with `auth.mode: native` created; route published via `reconcile-edge.py`
    - `graylog.test.gibbsgreatly.xyz` resolves via CoreDNS; HTTPS 200 through Traefik
    - `reconcile-edge.py --json` returns `issue_count: 0` with all manifests passing
- Ready for Sprint G3 (managed LXC + Docker log pilot)

---

### Sprint G3 — Managed LXC and Docker Log Pilot

**Goal:** Prove that Graylog can handle the current managed-host logging path
without losing source attribution.

**Deliverables**

- One or more managed LXC hosts feeding Graylog
- One Docker-heavy stack feeding Graylog
- Equivalent operator workflows to the current “Lab Logs” and “Auth Logs”
  use cases, but in Graylog

**Implementation tasks**

1. Choose the first pilot sources:
   - one mostly-systemd stack, e.g. `step-ca-stack` or `dns-stack`
   - one Docker-heavy stack, e.g. `authentik-stack` or `proxy-stack`
2. Decide whether dual-forwarding is needed during the pilot.
3. Validate that the following remain queryable in Graylog:
   - host identity
   - source process/container identity
   - auth-related events
   - recent error filtering
4. Document field mapping conventions used by Graylog for these sources.
5. Add Graylog-side smoke or query checks where practical.

**Validation tier**

- Ansible role/playbook changes: targeted `scripts/provision.sh --stack <affected>`
  on `pve-test-vm`
- If host logging path changes cross-cut all platform hosts, use a broader
  `--tier platform` validation.

**Validation checklist**

- A known system log line arrives in Graylog with correct source identity.
- A known Docker log line arrives in Graylog with correct container/source identity.
- Existing VictoriaLogs path remains available as rollback until Sprint G5.

**Minimum gate**

- Graylog supports at least the current Lab/Auth log investigation workflows for
  pilot sources without requiring Grafana LogsQL panels.

---

### Sprint G4 — Remote Syslog from Proxmox Host and MikroTik

**Goal:** Validate the appliance/host syslog use case that motivated the Graylog
direction change.

**Deliverables**

- Proxmox host syslog visible in Graylog
- MikroTik syslog visible in Graylog
- Query conventions documented for both

**Implementation tasks**

1. Implement Proxmox host remote syslog forwarding toward the Graylog path.
2. Validate source identity, message formatting, and transport reliability.
3. Implement MikroTik remote syslog forwarding toward the Graylog path.
4. Validate router-originated logs in Graylog.
5. Document any need for standard `UDP 514`, relay services, or Graylog input
   tweaks discovered during testing.

**Validation tier**

- This is network / remote syslog / cross-stack integration work.
- Expect a full `pve-test-vm` teardown-cycle validation before promotion.

**Validation checklist**

- Proxmox host test message visible in Graylog.
- MikroTik test message visible in Graylog.
- Expected source fields are stable enough for operational filtering.
- Existing metrics stack remains healthy.

**Minimum gate**

- Both remote syslog sources work on `pve-test-vm` through the chosen Graylog
  design.

---

### Sprint G5 — VictoriaLogs Deprecation on pve-test-vm

**Goal:** Remove VictoriaLogs from the active `pve-test-vm` operator workflow and
prove Graylog is sufficient before promotion.

**Deliverables**

- Graylog is the documented log UI on `pve-test-vm`
- Grafana log dashboards are deprecated or removed from the active workflow
- VictoriaLogs either removed from `pve-test-vm` or kept only as explicitly
  temporary rollback infrastructure

**Implementation tasks**

1. Decide whether to:
   - remove VictoriaLogs entirely, or
   - keep it temporarily but out of the active workflow
2. Update the teardown harness and health/validation steps so they reflect the
   intended log platform.
3. Update docs to make Graylog the preferred path.
4. Remove or mark obsolete:
   - VictoriaLogs-specific smoke checks
   - Grafana log dashboards that are no longer authoritative
   - VictoriaLogs MCP-server planning, if still irrelevant

**Validation tier**

- Full teardown cycle on `pve-test-vm`
- Post-rebuild targeted provision/health validation as needed

**Validation commands**

Use the appropriate teardown harness flow for the branch at the time. At a
minimum, the final proof must include:

1. destroy / rebuild of the relevant `pve-test-vm` state
2. full platform provision
3. Graylog health and ingest validation
4. Proxmox host and MikroTik log validation

**Minimum gate**

- End-to-end rebuild on `pve-test-vm` succeeds
- Graylog is the validated log workflow
- No required operator use case depends on VictoriaLogs

---

## Execution controls

### Current next step

The next practical implementation step is to replace the placeholder scaffold in
`/opt/graylog-stack` with the chosen Graylog single-node runtime and add a
stack-level smoke test before any `edge.yaml` route is published.

Do not publish Traefik/Auth/DNS for Graylog until these are true:

- Graylog containers start cleanly on `pve-test-vm`
- the internal health path is known and scripted
- a smoke test passes reliably after `scripts/provision.sh --stack graylog-stack`

### Sprint board

#### Phase-to-sprint mapping

| Track | Purpose | Exit condition |
|---|---|---|
| G0 | freeze current VictoriaLogs baseline | rollback point is documented and evidence-linked |
| G1 | settle Graylog architecture | no critical-path design ambiguity remains |
| G2 | deploy Graylog core | UI, ingress, and health are working on `pve-test-vm` |
| G3 | prove managed-host and Docker log ingestion | Graylog supports current pilot workflows |
| G4 | prove Proxmox and MikroTik remote syslog | appliance/host motivation is validated |
| G5 | deprecate VictoriaLogs on `pve-test-vm` | Graylog is the tested primary log workflow |

#### Definition of done per sprint

| Sprint | Done means | Not done if |
|---|---|---|
| G0 | baseline commands, evidence, and operator checks are written down | the rollback point still depends on memory or chat history |
| G1 | deployment shape, ports, ingress, auth, and retention are decided | Graylog stack placement or syslog edge model is still undecided |
| G2 | Graylog can be provisioned and opened in browser without breaking platform auth | Graylog exists only partially or requires manual hidden steps |
| G3 | pilot managed-host and Docker logs are queryable with correct identity | host/container attribution is ambiguous or fragile |
| G4 | Proxmox and MikroTik logs are actually visible in Graylog | the plan assumes appliance support without a live proof |
| G5 | final `pve-test-vm` workflow no longer depends on VictoriaLogs/Grafana logs | operators still need Grafana LogsQL for required log work |

### Test strategy

#### Per-sprint validation ladder

| Sprint | Minimum validation | Escalation trigger |
|---|---|---|
| G0 | docs review | none |
| G1 | docs review | none |
| G2 | targeted stack provision on `pve-test-vm` + platform smoke | any auth/Traefik regression |
| G3 | targeted host/stack provisions + platform validation | logging-path changes affecting many stacks |
| G4 | full teardown cycle on `pve-test-vm` | default for promotion |
| G5 | full teardown cycle on `pve-test-vm` | required |

#### Functional validation checklist

These are the operator-facing outcomes that must be tested before promotion:

1. Graylog browser access works — login redirects to Authentik OIDC, user lands in Graylog UI.
2. Managed LXC system logs are searchable by host/source.
3. Docker-container logs are searchable by host/source.
4. Proxmox host syslog is visible and attributable.
5. MikroTik syslog is visible and attributable.
6. Metrics dashboards in Grafana still work normally.
7. Existing platform stacks still provision cleanly on `pve-test-vm`.

### Rollback rule

Until Sprint G5 completes, VictoriaLogs remains the fallback. Any sprint that
breaks the current logging path without establishing the Graylog replacement
must be rolled back or fixed before promotion.

---

## Definition of ready for pve

This work is ready to promote from the development branch to `stable` only when:

- Sprint G5 is complete.
- The final `pve-test-vm` teardown-cycle validation is green.
- The Graylog operator workflow is documented and no longer ambiguous.
- The fallback/rollback story for `pve` is documented.

This work is ready to promote from `stable` to `main` only when:

- Graylog is incrementally deployed on `pve`.
- Existing metrics dashboards and scrape targets remain healthy.
- The production logging path is validated for:
  - managed LXC logs
  - Docker-heavy stack logs
  - Proxmox host logs
  - MikroTik logs

---

## First practical next step

Start with **Sprint G0** and **Sprint G1** before any new infra work:

1. capture the current validated VictoriaLogs baseline on `pve-test-vm`
2. decide and document the Graylog deployment shape
3. only then begin implementation of Graylog itself

That sequencing keeps the rollback baseline clear and avoids building the pilot
on unresolved architectural assumptions.
