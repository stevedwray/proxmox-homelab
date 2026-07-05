# Sprint Plan — Graylog Migration on pve-test-vm

**Scope:** Move the logging function of `monitoring-stack` on `pve-test-vm`
toward Graylog, while keeping `VictoriaMetrics` and `Grafana` focused on
metrics. The VictoriaLogs path is now historical baseline context rather than
an active dependency on the validated `pve-test-vm` source path.

**Goal:** End with a logging design that has been implemented, tested, and
validated on `pve-test-vm`, promoted to `stable`, and ready for incremental
deployment on `pve`.

**Branch model:** Follow [docs/workflow/branch-model.md](../workflow/branch-model.md).
Because this work spans Ansible, Docker Compose, cross-stack logging, and
remote syslog integration, every sprint should validate on `pve-test-vm`, and
the later integration sprints should expect a full teardown-cycle validation.

**Promotion target:** The `pve-test-vm` validation and `stable` promotion gate
have now been met. `main` is only updated after incremental deployment on `pve`
passes and the operator confirms no regressions.

**Everything below this line (through "Definition of ready for pve") is the
`pve-test-vm` pilot record (Sprints G0–G5), kept as-is for history.** The
production rollout itself — the actual work now underway — is planned in
[Part 2 — Production Rollout on `pve`](#part-2--production-rollout-on-pve) at
the end of this document, in Sprints P0–P6.

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

Current implementation state on the validated `stable` path (as of 2026-07-02):

- `graylog-stack` deployed and fully operational on `pve-test-vm`
  - hostname: `graylog-stack`, VMID: `20014`, IP: `192.168.20.114`, zone: `mgmt_seg`
  - Graylog 7.1.3 Data Node running (MongoDB 7 + DataNode + Graylog Server)
  - Traefik/Auth/DNS published: accessible at `https://graylog.test.gibbsgreatly.xyz`
  - LDAP auth backend configured; Authentik login works
- targeted Graylog destroy/redeploy validation succeeded after the teardown RCA fixes
  - Harbor-backed Graylog, MongoDB, and cAdvisor images confirmed in live runtime
  - browser validation succeeded after targeted redeploy
  - startup may require several smoke-test retries before `ALIVE`, but the current targeted path is healthy
- latest teardown RCA narrowed the last `pve-test-vm` blocker to Graylog first-boot preflight sequencing on a truly blank stack
  - full teardown reproduced this more reliably than follow-up reprovision work because it exercised Graylog cold start from empty container volumes
  - the validated remediation finalizes Graylog preflight before requiring later post-ALIVE provisioning
- All active pve-test-vm stacks dual-feeding Graylog (G3 complete)
- MikroTik and NAS remote syslog feeding Graylog (G4 complete)
- Proxmox host rsyslog forwarding configured via Ansible (G4 complete)
- targeted Graylog cold-start destroy/redeploy validation passed
- full teardown-cycle revalidation passed on `pve-test-vm`
- the Graylog teardown recovery chain has been merged to `stable`
- `terraform/secrets.enc.yaml` now contains `GRAYLOG_PASSWORD_SECRET` and `GRAYLOG_ROOT_PASSWORD_SHA2` (SOPS entry present)
- `rsyslog_forward` Ansible role extended: new defaults, conditional tasks, and `graylog_inbound.conf.j2` template to accept UDP/TCP 514 and forward to `127.0.0.1:5140`
- `deploy-graylog-stack.yml` now provisions the real runtime path used in targeted redeploy validation, cleans legacy Portainer-agent residue on the Graylog host, skips missing-dashboard warnings cleanly, and no longer writes scaffold assets during normal runtime deploys
- smoke-test helpers added under `scripts/smoke/` (`check-graylog-alive.sh`, `send-graylog-test-message.sh`, `query-graylog-search.sh`)

### Baseline evidence

- Full teardown/redeploy reference was previously recorded in a tracked
  teardown report that has now been removed as transient artifact material.
  Use `docs/teardown-test/README.md`, `docs/teardown-test/lessons-learned.md`,
  the relevant commits, and git history for recovery if the raw report is ever
  needed again.
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
- the metrics dashboards in Grafana remain healthy while Graylog owns the log workflow

Additional Graylog validation completed on this branch:

```bash
PVE_ENV=pve-test-vm ./with-secrets terragrunt apply \
  --working-dir terraform/lxc/environments/pve-test-vm/graylog-stack \
  -auto-approve -no-color

PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh \
  --stack graylog-stack --target-env pve-test-vm
```

Expected current result:

- Terraform creates `graylog-stack` at VMID `20014`
- env-scoped inventory is written under
  `terraform/lxc/environments/pve-test-vm/graylog-stack/`
- Ansible runtime provision completes successfully
- `/opt/graylog-stack/graylog.env` and `/opt/graylog-stack/docker-compose.yml`
  exist on the guest
- Graylog reports `ALIVE` after startup retries
- the browser path works at `https://graylog.test.gibbsgreatly.xyz`

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
| Graylog packaging | Graylog 7.1.3 Data Node — MongoDB 7 + Graylog DataNode + Graylog Server (3 containers) | ✅ settled |
| LXC RAM | 6144 MB (was 4096 MB) | ✅ settled |
| Browser auth | Authentik LDAP outpost (Option B) — Graylog Open 7.1.3 still relies on LDAP/AD for open-source SSO; generic OIDC remains an Enterprise feature, so the Authentik LDAP outpost on port 3389 stays the repo path | ✅ settled |
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
  - use `docs/teardown-test/README.md`, `docs/teardown-test/lessons-learned.md`,
    and the associated June 2026 commits as the durable baseline summary
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
- The Graylog single-node runtime shape, ingress, and auth model are now pinned
  in this plan and implemented on the branch.

---

### Sprint G2 — Graylog Core Deployment on pve-test-vm

**Goal:** Deploy Graylog itself on `pve-test-vm` without removing VictoriaLogs.

**Decisions settled**

| Decision | Choice | Rationale |
|---|---|---|
| Graylog version | 7.1.3 (Data Node) | Current dev target; keeps the Data Node architecture and current MongoDB 7 dependency |
| Compose topology | MongoDB 7 + Graylog Data Node + Graylog Server (3 containers) | Data Node replaces OpenSearch as the search/index backend |
| Syslog port 514 | rsyslog relay on LXC host (Option A) | rsyslog runs as root via systemd and can bind 514 naturally; no Docker privilege escalation |
| Syslog internal port | 5140 TCP | rsyslog → Graylog; same convention as VictoriaLogs used; bound to 127.0.0.1 only |
| Browser auth | **Authentik LDAP outpost (Option B)** | Graylog Open 7.1.3 still does not give us a direct Authentik OIDC path in the open-source build. Chosen approach: Authentik LDAP outpost (`ghcr.io/goauthentik/ldap:2026.2.4`) exposes LDAP on port 3389; Graylog LDAP Auth Service authenticates against it. Users log in once with Authentik credentials. ✅ Implemented and validated end-to-end in G2. |
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
  │  (native route only: TLS termination and routing at Traefik;
  │   Graylog handles login itself via LDAP against the Authentik LDAP
  │   outpost on port 3389)
  ▼
Authentik LDAP outpost
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
| `terraform/lxc/stacks/graylog-stack/edge.yaml` | new: Traefik route, DNS, TLS, native auth (`auth.mode: native`) |
| `terraform/lxc/stacks/graylog-stack/STACK_CONTRACT.md` | update to reflect real runtime |
| `scripts/teardown-deploy-test.sh` | add Graylog health gate |
| `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` | add graylog-stack node_exporter + cadvisor scrape targets |
| `terraform/lxc/stacks/authentik-stack/docker-compose.yml` | add LDAP outpost service |
| `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml` | add LDAP provider + outpost provisioning |
| `terraform/secrets.enc.yaml` | add `GRAYLOG_ROOT_PASSWORD` for post-ALIVE API configuration |

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
memory: 6144   # was 4096; Graylog 7.1.3 (MongoDB + DataNode + Graylog) requires headroom
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
          image: {{ graylog_registry_host }}/dockerhub/graylog/graylog-datanode:7.1.3
          env_file: graylog.env
          hostname: datanode
          volumes:
            - graylog_datanode:/var/lib/graylog-datanode
          restart: unless-stopped
          depends_on:
            - mongodb

        graylog:
          image: {{ graylog_registry_host }}/dockerhub/graylog/graylog:7.1.3
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
        mode: native
```

This route stays `native` because Graylog owns browser login via its LDAP auth
service. Traefik publishes the route and handles TLS, but it does not enforce
forward-auth or OIDC for this application. The Authentik integration lives
entirely in Graylog's LDAP backend configuration and the Authentik LDAP outpost
provisioned from `deploy-authentik-stack.yml`.

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
          PVE_ENV=pve-test-vm ./with-secrets \
            scripts/provision.sh --stack graylog-stack --target-env pve-test-vm
        Gate: Graylog reports ALIVE before proceeding

Step 7  Add graylog-stack to monitoring-stack scrape targets
          PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh \
            --stack monitoring-stack --target-env pve-test-vm
Step 8  Add Graylog gate to teardown-deploy-test.sh

⚠️  AUTH FINDING — Graylog Open 7.1.3 still does not provide the direct
OIDC path we want in the open-source build:
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
        - Steve should be elevated to Graylog Admin after LDAP-backed user provisioning
        - Requires: Authentik LDAP outpost setup, Graylog LDAP config via API,
          and a Graylog-side admin role assignment step
        Pro: true SSO — one set of credentials; matches "pattern of all services"
             in spirit (Authentik is the identity source)
        Con: LDAP outpost adds complexity; separate config effort

      Option C — forwardAuth only, no Graylog account for steve
        - Graylog accessible only from within Authentik session
        - Use Graylog admin/root account directly (known to operator only)
        - Simplest; but operator uses two accounts

    ✅ Operator chose Option B (Authentik LDAP outpost — true SSO).

Step 9  Edge publication + auth wiring — PARTIALLY DONE (Option B):

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
              End-to-end LDAP login from Graylog to Authentik ✅ validated
```

---

**Minimum gate (G2 done)**

- `provision.sh --stack graylog-stack` completes without error ✅ confirmed
- `curl http://192.168.20.114:9000/api/system/lbstatus` returns `ALIVE` ✅ confirmed
- rsyslog on graylog-stack LXC listens on TCP/UDP :514 (confirmed by `ss -lntu`) ✅ confirmed
- VictoriaMetrics shows `graylog-stack` node_exporter as up ✅ scrape targets added (Step 7)
- Graylog teardown gate passes in `teardown-deploy-test.sh` ✅ added (Step 8)
- Graylog web UI accessible at `graylog.test.gibbsgreatly.xyz` — route, page load, and LDAP auth via Authentik outpost ✅ validated end-to-end
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

**Current status (as of 2026-06-28) — Sprint G2 COMPLETE**

- End-to-end Graylog ↔ Authentik LDAP login is proven. Sprint G2 is complete.
- All G2 minimum gates are met:
  - ✅ Graylog containers healthy and auto-restart on pve-test-vm
  - ✅ Graylog LDAP auth service active; steve logs in via Authentik credentials
  - ✅ `graylog.test.gibbsgreatly.xyz` resolves via CoreDNS; HTTPS 200 through Traefik
  - ✅ `reconcile-edge.py --json` returns `issue_count: 0` with all manifests passing
  - ✅ Syslog input exists (`syslog-tcp-5140`); injected smoke messages are searchable
  - ✅ Monitoring scrape targets added (node_exporter + cAdvisor)

**Root cause of the LDAP blocker and resolution**

The LDAP bind failures in 2024.12.3 were caused by a session-binding bug in the
LDAP outpost: after the `user_login` stage ran, the session wasn't properly
propagated, causing `/api/v3/core/users/me/` to return 403.

The fix: upgrade Authentik to **2026.2.4** and adopt the new 2026.x LDAP
authorization flow model:

- Authorization flow `ldap-authz-flow` with `designation: authorization`,
  `authentication: none`, containing three stages: identification (order 10),
  password (order 20), user_login (order 30).
- LDAP provider's `authorization_flow` points to `ldap-authz-flow`.
- The separate `graylog-ldap-authentication-flow` (authentication flow) is no
  longer used by the LDAP outpost in 2026.x.

Additional 2026.x API change: the `search_full_directory` permission cannot be
granted via `assigned_by_users/{pk}/assign/` (endpoint removed). A new role
`ldap-search-full-directory` is created, the permission is granted to the role
via `assigned_by_roles/{role_pk}/assign/`, and the role is assigned to ldapservice.

**Live validation evidence**

```
ldapsearch -D "cn=ldapservice,..." "(cn=steve)" -> result: 0 Success, numEntries: 1
ldapsearch -D "cn=steve,..." "(cn=steve)"       -> result: 0 Success
POST /api/system/sessions (Graylog, steve)      -> HTTP 200, session_id returned
LDAP outpost: ldapservice bind -> search (found) -> steve bind (User has access)
```

**Automation committed for this sprint**

- `deploy-authentik-stack.yml`: version 2026.2.4; creates `ldap-authz-flow` with
  auth stages; role-based `search_full_directory` grant; LDAP provider
  authorization_flow = ldap-authz-flow, bind_mode/search_mode = direct
- `deploy-graylog-stack.yml`: LDAP system user = ldapservice, host = LAB_IP_AUTHENTIK

**Status: Sprint G2 complete. Sprint G3 (Managed LXC and Docker Log Pilot) is active.**

---

**Current G3 position (repo state)**

- The repo now contains early G3 implementation work, not just G3 planning:
  - `deploy-authentik-stack.yml` enables dual-feed to Graylog via
    `rsyslog_graylog_enabled: true`
  - `deploy-step-ca.yml` also enables dual-feed to Graylog via
    `rsyslog_graylog_enabled: true`
  - the shared `rsyslog_forward` role supports dual-feed to VictoriaLogs and
    Graylog at the same time, preserving rollback during the pilot
- This means pilot-source wiring has started, with the current likely pilot
  candidates being:
  - Docker-heavy: `authentik-stack`
  - systemd-heavy: `step-ca-stack`
- What is not yet proven in tracked docs is the G3 validation evidence:
  - no documented operator-equivalent Graylog queries yet for the current
    “Lab Logs” / “Auth Logs” workflows

**Live G3 validation evidence (2026-06-28)**

- Pilot sources selected:
  - systemd-heavy: `step-ca-stack` (`192.168.20.111`)
  - Docker-heavy: `authentik-stack` (`192.168.20.110`)
- Entry checks passed:
  - `graylog-stack` (`192.168.20.114`) returns `ALIVE` on
    `/api/system/lbstatus`
  - Graylog API login for `steve` with Authentik credentials returns HTTP 200
    and a valid session
  - Graylog external-user provisioning for `steve` succeeds after correcting the
    LDAP auth-service backend
    `default_roles` value to Graylog's internal Reader role ObjectId rather
    than the human-readable role name
  - both `step-ca-stack` and `authentik-stack` have live rsyslog dual-feed
    config forwarding to VictoriaLogs on `:5140` and Graylog on
    `192.168.20.114:514`
- Managed-LXC proof:
  - emitted test message on `step-ca-stack`:
    `logger -t g3-stepca-test 'G3_STEPCA_20260628T_STEPCA_SYSLOG_PROOF'`
  - Graylog search result returned:
    - `source=step-ca`
    - `application_name=g3-stepca-test`
    - `message=G3_STEPCA_20260628T_STEPCA_SYSLOG_PROOF`
- Docker-heavy proof:
  - recent Authentik LDAP outpost events triggered by Graylog login are present
    in Graylog search results with:
    - `source=authentik-stack`
    - `application_name=docker-authentik-stack-ldap-1`
    - message payloads containing JSON events such as `User has access`
- G3 interpretation:
  - pilot ingestion is now proven for one managed-LXC/systemd source and one
    Docker-heavy source
  - browser login with Authentik credentials is also now re-validated on the
    live `graylog-stack`; the last blocker was Graylog-side provisioning, not
    LDAP bind/search itself
  - additional live dev validation on 2026-06-29 upgraded `graylog-stack`
    in place from Graylog `6.1` to `7.1.3`; `POST /api/system/sessions`
    for `steve` still returned HTTP 200 after the upgrade
  - dual-feed rollback remains active
  - remaining G3 work is to document stable operator query patterns and broaden
    validation beyond these first proof points

**Data Node heap warning note (2026-06-29)**

- Graylog `7.1.3` remains functionally usable on `graylog-stack`
  (`192.168.20.114`): UI/API reachability, LDAP-backed `steve` login, and log
  ingestion are still working.
- However, the Graylog system notification `data_node_heap_warning` is still
  active after the upgrade.
- Live diagnosis showed:
  - the Data Node wrapper JVM was successfully moved to `-Xms3g -Xmx3g`
  - but the embedded OpenSearch process still launched with
    `-Xms1g -Xmx1g`
  - Graylog's notification API still reported the old effective heap as `1 GB`
    and recommended `7g` based on a misleading `15 GB` memory view from inside
    the nested container
- Repo attempts on 2026-06-29 improved the Data Node wrapper heap and confirmed
  the warning is specifically about the inner OpenSearch JVM, not the outer
  Data Node JVM.
- Remaining issue to come back to:
  - identify the real Graylog `7.1.3` control path for the embedded
    OpenSearch heap
  - avoid relying on manual or file-level `jvm.options` overrides unless they
    are proven to win over Graylog's generated config path
  - keep an eye on this warning after future Graylog/Data Node reprovisions and
    upgrades until the live OpenSearch JVM args no longer show `-Xms1g -Xmx1g`

**Auth-service regression note (2026-06-28)**

- Symptom: Graylog browser/API login returned `503 Authentication service unavailable`
  even though the Authentik LDAP outpost logs showed successful bind, search,
  and user bind for `steve`.
- Root cause: the Graylog LDAP auth-service backend was provisioned with
  `default_roles=["Reader"]`. Graylog's external-user provisioner expects role
  ObjectIds here, not role names, so user creation failed with:
  `ProvisionerServiceException: Couldn't provision user: steve` and
  `IllegalArgumentException: hexString has 24 characters`.
- Fix: resolve the built-in Reader role from Graylog Mongo
  (`6a3e04d51548b6dc3d9e79ae` on the current test instance) and use that ID in
  `default_roles`.
- Validation:
  - backend document in `auth_service_backends` shows the Reader ObjectId
  - Graylog restarted cleanly
  - `POST /api/system/sessions` for `steve` returns HTTP 200 with a session
  - `/api/users/steve` now shows `external=true` and
    `auth_service_enabled=true`

**Historical note**

The pre-`2026.2.4` LDAP bind/session debugging above is now superseded by the
working `ldap-authz-flow` + role-based permission model. Keep those notes only
as background for why the Authentik implementation changed; they are no longer
the current blocker.

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

- ✅ A known system log line arrives in Graylog with correct source identity.
- ✅ A known Docker log line arrives in Graylog with correct container/source identity.
- Existing VictoriaLogs path remains available as rollback until Sprint G5.

**Minimum gate**

- Graylog supports at least the current Lab/Auth log investigation workflows for
  pilot sources without requiring Grafana LogsQL panels.

---

**Current status — Sprint G3 COMPLETE (2026-06-30)**

All active pve-test-vm managed stacks are dual-feeding Graylog alongside
VictoriaLogs. MikroTik and NAS are also feeding Graylog (see Sprint G4 section).

**Graylog field conventions confirmed for managed-LXC sources:**

| Field | Meaning | Example values |
|---|---|---|
| `source` | LXC hostname | `step-ca`, `authentik-stack`, `proxy-stack` |
| `application_name` | Process or container name | `sshd`, `docker-authentik-stack-ldap-1` |
| `facility` | Syslog facility | `user-level`, `auth` |
| `level` | Syslog severity | `6` (informational), `3` (error) |

Docker container entries use `application_name` prefixed `docker-<stack>-<service>-<n>`.
System/journald entries use the process name directly (e.g., `sshd`, `cron`).

**Graylog query patterns for operator workflows:**

| Workflow | Query |
|---|---|
| All lab logs, recent | `*` (default, scoped to last 5 min) |
| Single host | `source:step-ca` |
| Auth events (all hosts) | `facility:auth` |
| SSH logins | `facility:auth AND application_name:sshd AND (Accepted OR Failed)` |
| Docker container logs | `application_name:docker-*` |
| Specific container | `source:authentik-stack AND application_name:docker-authentik-stack-ldap-1` |
| Errors only | `level:3` or `level:(0 1 2 3)` |

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
- The `pve-test-vm` teardown-cycle validation gate has been satisfied; the next
  promotion gate is incremental deployment on `pve`.

**Validation checklist**

- Proxmox host test message visible in Graylog.
- MikroTik test message visible in Graylog.
- Expected source fields are stable enough for operational filtering.
- Existing metrics stack remains healthy.

**Minimum gate**

- Both remote syslog sources work on `pve-test-vm` through the chosen Graylog
  design.

---

#### MikroTik implementation (completed 2026-06-29)

MikroTik was already sending syslog to `192.168.20.114:514` (UDP) before G4
started — the remote logging action and topic rules were in place from prior lab
config. The only change needed was the log format.

**Inspect current MikroTik logging config:**

```routeros
/system logging action print
/system logging print where action=remote
```

**Pre-existing state found:**

```
/system logging action:
  name="remote"  target=remote  remote=192.168.20.114  remote-port=514
  src-address=0.0.0.0  remote-log-format=default  remote-protocol=udp

/system logging rules sending to remote:
  topics=!debug,!packet  action=remote   (two rules, same config)
```

**Problem with `remote-log-format=default`:**

MikroTik's default format does not consistently use the system identity as the
syslog HOSTNAME field. Logs arrived in Graylog as two fragmented sources:

- `source=192.168.20.1` — system/DHCP messages (MikroTik used its interface IP)
- `source=dns` — DNS query/response messages (MikroTik used the topic name)

**Fix — switch to BSD syslog format with ISO 8601 timestamps:**

```routeros
/system logging action set [find name=remote] remote-log-format=bsd-syslog
```

When MikroTik prompts for timestamp format, choose **ISO 8601**. BSD syslog
timestamps (`Jun 29 14:30:00`) carry no year and no timezone; ISO 8601 includes
both, giving rsyslog an unambiguous timestamp regardless of timezone skew.

**Result after format change:**

All MikroTik messages now arrive in Graylog under a single unified source:

- `source=hAP` (the MikroTik system identity — verify with `/system identity print`)
- `application_name` = MikroTik topic, e.g. `dhcp,error`, `system,info`, `query`, `done`
- `facility=user-level`, `level=6` (informational) for most messages
- 67 messages confirmed within 5 minutes of the format change

**Graylog query conventions for MikroTik:**

| Goal | Query |
|---|---|
| All MikroTik traffic | `source:hAP` |
| DHCP events | `source:hAP AND application_name:dhcp*` |
| DNS queries | `source:hAP AND application_name:query` |
| System/config changes | `source:hAP AND application_name:system*` |
| Errors only | `source:hAP AND application_name:*error*` |

**No infrastructure change required on the Graylog side.** The
`91-graylog-inbound.conf` on `graylog-stack` already accepts UDP on port 514
and relays to Graylog on `127.0.0.1:5140`. MikroTik sends RFC 3164 (BSD syslog)
which the default rsyslog parser handles correctly on the UDP input.

**Proxmox host syslog:** configured via Ansible — see subsection below.

---

#### NAS implementation (completed 2026-06-30)

NAS configured via its own syslog settings UI to forward to `graylog-stack:514`
UDP. No Ansible required. Logs arrive in Graylog with the NAS hostname as
`source`. Filter with `source:<nas-hostname>`.

---

#### Proxmox host syslog implementation (2026-06-30)

**Approach:** A standalone Ansible playbook in the top-level `ansible/` tree,
targeting the existing `proxmox_testbed` group in `ansible/inventory/dev.yml`.
The Proxmox host is bare metal — it does not go through the `terraform/lxc`
stack provisioning path.

**Files:**

| File | Purpose |
|---|---|
| `ansible/playbooks/configure-proxmox-syslog.yml` | Playbook — installs and configures rsyslog forwarding to Graylog |
| `ansible/templates/rsyslog-graylog-forward.conf.j2` | rsyslog config template — RFC 5424, TCP, disk-backed queue |

**Why not reuse the `rsyslog_forward` LXC role:** The LXC role has
Docker-specific logic (imklog suppression, imtcp Docker listener,
VictoriaLogs dual-feed) that does not apply to a bare-metal Proxmox host.
A purpose-built minimal template is cleaner.

**Run command:**

```bash
PVE_ENV=pve-test-vm ./with-secrets ansible-playbook \
  -i ansible/inventory/dev.yml \
  ansible/playbooks/configure-proxmox-syslog.yml \
  --limit pve-test-vm.gibbsgreatly.xyz
```

**Graylog query conventions for Proxmox host:**

| Goal | Query |
|---|---|
| All Proxmox host logs | `source:pve-test-vm` |
| Kernel messages | `source:pve-test-vm AND application_name:kernel` |
| systemd/service events | `source:pve-test-vm AND application_name:systemd` |
| LXC container starts/stops | `source:pve-test-vm AND pct` |
| Authentication | `source:pve-test-vm AND facility:auth` |

**Validation:** After running the playbook, verify with:

```bash
# On the Proxmox host — emits a probe message
logger -t ansible-proxmox-syslog-test 'G4_PVE_SYSLOG_PROOF'
```

In Graylog: `source:pve-test-vm AND application_name:ansible-proxmox-syslog-test`
should return the probe message.

---

### Sprint G5 — VictoriaLogs Removal on pve-test-vm

**Goal:** Remove VictoriaLogs entirely from `pve-test-vm` and simplify the
rsyslog pipeline to Graylog-only. Prove the result survives a full teardown.

**Decision:** Remove VictoriaLogs entirely (not kept as rollback).

**Deliverables**

- VictoriaLogs container and volume removed from monitoring-stack
- `rsyslog_forward` role simplified to a single unconditional Graylog forward
  (no dual-feed, no conditional vars)
- Grafana VictoriaLogs datasource and log dashboards removed
- Log search workflow is Graylog UI only

**Implementation tasks**

#### 1. Remove VictoriaLogs from `deploy-monitoring-stack.yml`

- Remove `victorialogs_version` and `victorialogs_image` var declarations
- Remove the `victorialogs` Docker service block from the inline compose
- Remove the `victorialogs-data` named volume from the compose
- Remove the VictoriaLogs Grafana datasource provisioning block
  (`name: VictoriaLogs`, `uid: VictoriaLogs`, `url: http://victorialogs:9428`)
- Remove the Prometheus scrape job `job_name: victorialogs`
- Remove the `Wait for VictoriaLogs health endpoint` task

#### 2. Simplify `rsyslog_forward` role to Graylog-only

File: `terraform/lxc/ansible/roles/rsyslog_forward/defaults/main.yml`
- Change `rsyslog_forward_target_host` to default to `LAB_IP_GRAYLOG`
- Change `rsyslog_forward_target_port` to `514`
- Remove `rsyslog_graylog_enabled`, `rsyslog_graylog_target_host`,
  `rsyslog_graylog_target_port`

File: `terraform/lxc/ansible/roles/rsyslog_forward/templates/log-forwarding.conf.j2`
- Rename template `VictoriaLogsForward` → `GraylogForward`
- Remove the primary VictoriaLogs `omfwd` action
- Remove the `{% if rsyslog_graylog_enabled %}` dual-feed blocks — Graylog
  forward becomes the single unconditional action
- Rename queue files: `victorialogs-fwd` → `graylog-fwd`,
  `victorialogs-fwd-docker` → `graylog-docker-fwd`
- Update comment header

#### 3. Update all stack playbooks — remove `rsyslog_graylog_enabled: true`

These vars are no longer meaningful once Graylog is the only target:
- `deploy-apt-cacher-stack.yml`
- `deploy-harbor-stack.yml`
- `deploy-step-ca.yml`
- `deploy-proxy-stack.yml`
- `deploy-portainer-stack.yml`
- `deploy-netbox-stack.yml`
- `deploy-authentik-stack.yml`
- `deploy-monitoring-stack.yml`

#### 4. Keep graylog-stack explicit override

`deploy-graylog-stack.yml` must keep:
```yaml
rsyslog_forward_target_host: "127.0.0.1"
rsyslog_forward_target_port: "5140"
```
The graylog-stack LXC forwards its own logs directly to the local Graylog
syslog input on `127.0.0.1:5140`, not to the external relay on :514.

#### 5. Remove VictoriaLogs Grafana dashboards

Delete from `terraform/lxc/stacks/monitoring-stack/dashboards/`:
- `auth-logs.json` — uses VictoriaLogs datasource
- `lab-logs.json` — uses VictoriaLogs datasource

Log search is now Graylog UI. The Graylog dashboard equivalents will be
`auth-security.json` and `lab-logs-overview.json` in the Graylog dashboards
directory.

#### 6. Run syntax checks

```bash
ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles \
  ansible-playbook --syntax-check \
  terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml

ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles \
  ansible-playbook --syntax-check \
  terraform/lxc/ansible/playbooks/deploy-graylog-stack.yml
```

**Validation tier**

- Full teardown cycle on `pve-test-vm`
- Post-rebuild targeted provision/health validation as needed

**Validation commands**

Use the appropriate teardown harness flow for the branch at the time. At a
minimum, the final proof must include:

1. Destroy / rebuild of the relevant `pve-test-vm` state
2. Full platform provision
3. Graylog health and ingest validation
4. Confirm `source:pve-test-vm`, `source:hAP`, and a managed LXC all appear
   in Graylog after rebuild
5. Confirm monitoring-stack is healthy (Prometheus, Grafana, Alertmanager)
   with no VictoriaLogs references in compose or health checks

**Minimum gate**

- End-to-end rebuild on `pve-test-vm` succeeds
- No VictoriaLogs container or volume exists post-rebuild
- Graylog is the only log workflow
- Grafana shows no broken datasource panels

---

## Execution controls

### Current next step

**Sprints G0-G5 are complete on the active source path, and the `stable`
promotion gate has been met.** The next promotion step is incremental
deployment on `pve`.

G4 exit criteria all met:
- ✅ MikroTik remote syslog — complete (2026-06-29)
- ✅ NAS remote syslog — complete (2026-06-30)
- ✅ Proxmox host syslog via Ansible — `ansible/00-initial-setup/configure-proxmox-syslog.yml`
  validated on pve-test-vm; probe message confirmed in Graylog (2026-06-30)

Sprint G5 status:
- ✅ VictoriaLogs removed from the active monitoring-stack source path
- ✅ `rsyslog_forward` source path is Graylog-only
- ✅ Grafana VictoriaLogs log dashboards removed from monitoring-stack source
- ✅ Full teardown cycle on `pve-test-vm` validated the active source path

### Sprint board

#### Phase-to-sprint mapping

| Track | Purpose | Exit condition |
|---|---|---|
| G0 | freeze current VictoriaLogs baseline | rollback point is documented and evidence-linked |
| G1 | settle Graylog architecture | no critical-path design ambiguity remains |
| G2 | deploy Graylog core | UI, ingress, and health are working on `pve-test-vm` |
| G3 | prove managed-host and Docker log ingestion | Graylog supports current pilot workflows |
| G4 | prove Proxmox and MikroTik remote syslog | appliance/host motivation is validated |
| G5 | remove VictoriaLogs from `pve-test-vm` entirely | Graylog is the tested primary log workflow |

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

1. Graylog browser access works — user logs in with Authentik credentials via LDAP auth backend, lands in Graylog UI. ✅ Passing (G2 complete 2026-06-28).
2. Managed LXC system logs are searchable by host/source. ✅ Passing (G3 complete 2026-06-30).
3. Docker-container logs are searchable by host/source. ✅ Passing (G3 complete 2026-06-30).
4. Proxmox host syslog is visible and attributable. ✅ Passing (G4 complete 2026-06-30).
5. MikroTik syslog is visible and attributable. ✅ Passing (G4, 2026-06-29).
6. Metrics dashboards in Grafana still work normally.
7. Existing platform stacks still provision cleanly on `pve-test-vm`.

### Rollback rule

The Graylog replacement path is now the active validated logging path on
`pve-test-vm`. Any sprint that breaks it must be rolled back or fixed before
promotion to `main`.

---

## Definition of ready for pve

The `stable` promotion gate for the current Graylog path has been achieved:

- the final `pve-test-vm` teardown-cycle validation is green
- the Graylog operator workflow is documented well enough for test-domain use
- the validated `pve-test-vm` source path is Graylog-first and monitoring-stack remains metrics-focused

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

Incrementally deploy the validated Graylog path on `pve` — see
[Part 2 — Production Rollout on `pve`](#part-2--production-rollout-on-pve)
below for the full sprint-by-sprint plan (Sprints P0–P6). Historical
VictoriaLogs-only documentation/tooling cleanup is folded into Sprint P6.

---

# Part 2 — Production Rollout on `pve`

**Status as of 2026-07-06:** Sprints P0–P4 complete and verified on `pve`.
`graylog-stack` is live, publicly reachable, LDAP-SSO'd, and is now the sole
log sink for every managed stack; VictoriaLogs and its Grafana artifacts are
fully removed from production. Sprint P5 (remote syslog: Proxmox host,
MikroTik, NAS) has been handed off to the operator to run directly. Sprint P6
(cleanup + `stable`→`main` promotion) is not yet started. (Note: the *DNS*
refactor — Technitium replacing CoreDNS as the live resolver — already went
to production on 2026-07-04, independently of this plan; see
[dns-refactor/current-state.md](../dns-refactor/current-state.md). That
change was a precondition this plan relied on, not something it repeated.)

**Why this was more than "add one LXC":** production `monitoring-stack` had
been running the pre-Graylog Phase 6/7 pipeline (rsyslog → VictoriaLogs) up
until Sprint P4. Every managed stack on `pve` now forwards syslog to Graylog
instead. Finishing this rollout meant standing up `graylog-stack` on `pve`
**and** repeating the pve-test-vm G2–G5 cutover — LDAP SSO, per-stack rsyslog
repoint, VictoriaLogs removal, and remote syslog (Proxmox/MikroTik/NAS) — against the
real production stacks and the real physical appliances.

**Repo-state findings that shape this plan** (verified 2026-07-06 against the
live tree, not just prior docs):

| Finding | Detail |
|---|---|
| Runtime deploy gate is test-only | `scripts/provision.sh` (~line 555) only sets `GRAYLOG_DEPLOY_RUNTIME=true` when `PVE_ENV=pve-test-vm`. Every real task in `deploy-graylog-stack.yml` is gated on that variable. Deploying to `pve` today would silently run the placeholder/scaffold path only. |
| No production secrets | `terraform/secrets.pve.enc.yaml` has no `GRAYLOG_*` keys. They exist only in the dev/test `terraform/secrets.enc.yaml`. |
| No production env vars | `.env.pve` has no `LAB_IP_GRAYLOG` / `LAB_FQDN_GRAYLOG` entries. `.env.pve.template` is also missing `LAB_FQDN_GRAYLOG` (template gap). |
| VMID/network clear | `20014` is unused on `pve`; `graylog-stack`'s `mgmt_seg` placement has no conflict. |
| Terraform scaffold present, unapplied | `terraform/lxc/environments/pve/graylog-stack/terragrunt.hcl` exists (committed in G2) but nothing indicates the LXC has actually been created on `pve`. |
| `edge.yaml` is environment-agnostic | Already uses `${LAB_DOMAIN}` / `${LAB_IP_GRAYLOG}` / `${LAB_IP_PROXY}` — no changes needed for it to render correctly on `pve` once the env vars above exist. |
| Technitium DNS publish is per-stack-triggered | `render-edge-technitium.py` only runs when `technitium-stack` itself is provisioned. A `graylog-stack` deploy alone will not publish its DNS record. |
| Authentik LDAP outpost provisioning is environment-agnostic | `deploy-authentik-stack.yml`'s LDAP provider/outpost/app tasks have no test-only gating — a normal `authentik-stack` reprovision on `pve` will provision them. |
| Proxmox host syslog playbook is hardcoded to the test host | `ansible/00-initial-setup/configure-proxmox-syslog.yml` line 15: `hosts: pve-test-vm.gibbsgreatly.xyz`. Needs to target `pve.gibbsgreatly.xyz` (group `proxmox_production` already exists in `ansible/inventory/production.yml`). |
| MikroTik / NAS syslog targets are pilot-only, not IaC | Both were pointed at pve-test-vm's Graylog IP by hand (RouterOS CLI / NAS UI) during G4. They must be repointed at the production Graylog IP by hand again — nothing in the repo does this for either environment. |
| Graylog smoke test is test-only (found during P2 execution) | `terraform/lxc/stacks/graylog-stack/smoke-test.sh` unconditionally exited 0 ("skipping") unless `PVE_ENV=pve-test-vm` — same category of gap as the runtime-deploy gate, added by the same commit (`666e5a70`). Fixed alongside P1: the environment check was removed, so the smoke test now actually runs on every environment. |
| Harbor `gcr` proxy-cache project missing on production Harbor (found during P2 execution) | `deploy-graylog-stack.yml` pulls `cadvisor` via `{{ registry_host }}/gcr/cadvisor/cadvisor:v0.49.1`. The `gcr` proxy-cache project was added to `harbor_postconfigure`'s defaults in commit `666e5a70` (2026-07-01) — but that commit is on `stable`, not `main`, so production Harbor's post-configure has never created it. `mongo`/`graylog`/`graylog-datanode` pulled fine (routed through the long-standing `dockerhub` project); only the `gcr`-routed `cadvisor` pull failed with `unauthorized: project gcr not found`. Fix: reprovision `harbor-stack` on `pve` (additive/idempotent — only adds the missing project) before retrying `graylog-stack`. See P2 execution log below. |

## Manual actions required (read this first)

These cannot be done by an agent session running under the standard
production credential controls, or are physical/device actions outside the
repo entirely. Everything else in Sprints P0–P6 can run through
`./with-secrets-prod` with normal preflight/approval.

| # | Action | Sprint | Why it's manual |
|---|---|---|---|
| 1 | Generate and SOPS-encrypt new **production** Graylog secrets into `terraform/secrets.pve.enc.yaml` (`GRAYLOG_PASSWORD_SECRET`, `GRAYLOG_ROOT_PASSWORD_SHA2`, `GRAYLOG_ROOT_PASSWORD`) | P0 | Production secret material — generate/encrypt yourself, or explicitly supervise the SOPS edit; agents should not be given standing write access to SOPS-encrypted files. Must be **different values** from the dev/test secrets, not copied. |
| 2 | Pick the actual free `mgmt_seg` IP for `LAB_IP_GRAYLOG` in `.env.pve` | P0 | `.env.pve` is access-controlled outside normal read tooling; you need to check current allocations and pick the next free address yourself (or explicitly hand it over). |
| 3 | Approve each mutating step (Preflight Summary → say "Proceed" → `export TASK_APPROVAL=...`) | P2, P3, P4, P5 | Standard per-task production approval per `CLAUDE.md` — no standing approval. |
| 4 | Repoint the physical **MikroTik** router's `remote` syslog action from the pve-test Graylog IP to the new production `LAB_IP_GRAYLOG`, and set `remote-log-format=bsd-syslog` with ISO 8601 timestamps | P5 | No MikroTik IaC exists (tracked separately as TM-09); this is a live RouterOS CLI change on the one physical router shared by both environments. |
| 5 | Repoint the physical **NAS**'s syslog forwarding target (its own settings UI) to the new production Graylog IP | P5 | NAS has no Ansible/Terraform management; UI-only device config. |
| 6 | Do the actual browser login test (Authentik credentials → Graylog UI) | P3 | Needs your real credentials; not something a session can validate end-to-end. |

## Sprint P0 — Production Secrets & Config Scaffolding

**Goal:** Stage everything `deploy-graylog-stack.yml` needs to run for real on
`pve`, without deploying anything yet.

**Implementation tasks**

1. Generate fresh production secrets (do not reuse dev/test values):
   ```bash
   openssl rand -base64 72 | tr -d '\n'        # GRAYLOG_PASSWORD_SECRET
   # choose a new root password, then:
   echo -n '<new-root-password>' | sha256sum | cut -d' ' -f1   # GRAYLOG_ROOT_PASSWORD_SHA2
   ```
   SOPS-encrypt `GRAYLOG_PASSWORD_SECRET`, `GRAYLOG_ROOT_PASSWORD_SHA2`, and
   `GRAYLOG_ROOT_PASSWORD` (plaintext, needed for post-ALIVE API calls) into
   `terraform/secrets.pve.enc.yaml` — **manual action #1 above.**
2. Add to `.env.pve`:
   ```
   LAB_IP_GRAYLOG=<next free mgmt_seg address>
   LAB_FQDN_GRAYLOG=graylog.${LAB_DOMAIN}
   ```
   — **manual action #2 above** (IP selection). The `LAB_FQDN_GRAYLOG` line
   itself is not secret and can be added directly.
3. Add the missing `LAB_FQDN_GRAYLOG` entry to `.env.pve.template` (currently
   only has `LAB_IP_GRAYLOG` / `TF_VAR_lab_ip_graylog`) so the template stays
   in sync — non-secret, can be done directly.
4. Confirm `20014` is still free on `pve` (already confirmed 2026-07-06 — no
   conflict found across all `stack.yaml` VMIDs).

**Validation**

```bash
PVE_ENV=pve ./with-secrets-prod terragrunt plan \
  --working-dir terraform/lxc/environments/pve/graylog-stack
```
Expected: a clean plan to create exactly one new LXC (20014), no errors about
missing variables/secrets.

**Minimum gate**

- Env vars and secrets present; `terragrunt plan` clean; nothing deployed yet.

---

## Sprint P1 — Flip the Runtime Gate for Production

**Goal:** Make `scripts/provision.sh` run the real Graylog runtime (not the
scaffold-only placeholder) when targeting `pve`.

**Decision:** Rather than special-casing `pve` alongside `pve-test-vm`, drop
the environment condition entirely. The scaffold-only path was a temporary
safety valve for while the pilot was unproven — that condition no longer
holds for either environment now that G0–G5 passed a full teardown-cycle
validation. Collapse `deploy-graylog-stack.yml` to always run for real when
`graylog-stack` is the target stack.

**Implementation tasks**

1. In `scripts/provision.sh`, change:
   ```bash
   if [[ "$stack" == "graylog-stack" && "${PVE_ENV:-}" == "pve-test-vm" ]]; then
     cmd=(env GRAYLOG_DEPLOY_RUNTIME=true "${cmd[@]}")
   fi
   ```
   to:
   ```bash
   if [[ "$stack" == "graylog-stack" ]]; then
     cmd=(env GRAYLOG_DEPLOY_RUNTIME=true "${cmd[@]}")
   fi
   ```
   and update the stale comment above it (it currently says "Keep production
   behavior unchanged until the test-domain path is fully validated" — that
   milestone has now been reached).
2. Run the required syntax check per `CLAUDE.md`'s Ansible-change rule:
   ```bash
   ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles \
     ansible-playbook --syntax-check \
     terraform/lxc/ansible/playbooks/deploy-graylog-stack.yml
   ```
3. Leave the now-permanently-dead scaffold branch in
   `deploy-graylog-stack.yml` (the `when: not (graylog_deploy_runtime | bool)`
   tasks) in place for this sprint — don't delete it mid-rollout. Removing it
   is a Sprint P6 cleanup item once production is proven stable.
4. Same fix, same reason, in `terraform/lxc/stacks/graylog-stack/smoke-test.sh`:
   it unconditionally `exit 0`'d ("skipping") unless `PVE_ENV=pve-test-vm`,
   which would have silently reported the smoke test as passed on `pve`
   without checking Graylog actually came up. Removed the environment check
   entirely — the smoke test now always runs. **Done.**

**Validation**

- `--syntax-check` passes.
- Code review of the diff — this is a one-line behavioral change with
  repo-wide effect (any future `graylog-stack` provision anywhere now always
  deploys for real), so review it as such.

**Minimum gate**

- Change committed on the working branch. No live `pve` mutation yet.

---

## Sprint P2 — Deploy `graylog-stack` to `pve`

**Goal:** Create the LXC and bring up the real Graylog runtime on `pve`, in
isolation — not yet publicly reachable, not yet receiving logs from other
stacks.

**This is the first actual production mutation in this plan.** Follow the
full Preflight Summary → operator "Proceed" → `TASK_APPROVAL` flow from
`CLAUDE.md` before running anything below.

**Implementation tasks**

1. Create the LXC:
   ```bash
   export TASK_APPROVAL="graylog-pve-p2-deploy"
   PVE_ENV=pve ./with-secrets-prod terragrunt apply \
     --working-dir terraform/lxc/environments/pve/graylog-stack \
     -auto-approve -no-color
   ```
2. Provision the real runtime (now unconditional after P1):
   ```bash
   PVE_ENV=pve ./with-secrets-prod scripts/provision.sh \
     --stack graylog-stack --target-env pve
   ```
3. Confirm ALIVE from a host with `mgmt_seg` reachability:
   ```bash
   curl -fsS "http://${LAB_IP_GRAYLOG}:9000/api/system/lbstatus"
   ```

**Validation**

- Terraform creates `graylog-stack` at VMID `20014` on `pve`.
- Ansible provision completes; `/opt/graylog-stack/graylog.env` and
  `docker-compose.yml` exist on the guest.
- Graylog reports `ALIVE` (may need several retries on first boot, same as
  the pve-test-vm experience).
- rsyslog on the `graylog-stack` LXC listens on TCP/UDP `:514`.

**Minimum gate**

- `graylog-stack` fully running on `pve`, containers healthy and
  auto-restarting. No DNS/Traefik route, no LDAP auth, no external log
  sources yet — those are P3–P5.

### P2 execution log (2026-07-06)

**Attempt 1** — `terragrunt apply` succeeded (LXC `20014` created). The
`deploy-graylog-stack.yml` provision run then failed at the "Pre-pull Graylog
runtime images from Harbor sequentially" task:

```
changed: [graylog-stack] => (item=harbor.lab.gibbsgreatly.xyz/dockerhub/mongo:7)
changed: [graylog-stack] => (item=harbor.lab.gibbsgreatly.xyz/dockerhub/graylog/graylog-datanode:7.1.3)
changed: [graylog-stack] => (item=harbor.lab.gibbsgreatly.xyz/dockerhub/graylog/graylog:7.1.3)
failed: [graylog-stack] (item=harbor.lab.gibbsgreatly.xyz/gcr/cadvisor/cadvisor:v0.49.1)
  => stderr: "Error response from daemon: unauthorized: project gcr not found: project gcr not found"
```

Root cause and fix identified above (Harbor `gcr` proxy-cache project missing
on production Harbor — see findings table). Since the LXC itself was created
successfully and only the image pull failed, **do not re-run `terragrunt
apply`** — go straight to the remediation + retry below.

**Remediation — add task 1a to this sprint:**

```bash
export TASK_APPROVAL="graylog-pve-p2-harbor-gcr-project"
PVE_ENV=pve ./with-secrets-prod scripts/provision.sh \
  --stack harbor-stack --target-env pve
```
This re-runs `harbor_postconfigure`, which is additive/idempotent: it creates
the missing `gcr` proxy-cache project and endpoint. It does not modify or
remove the existing `dockerhub`/`ghcr`/`quay`/`lscr` projects, robot accounts,
or any other Harbor config already in production use by other stacks.

**Then retry step 2** (`scripts/provision.sh --stack graylog-stack
--target-env pve`) — Ansible tasks are idempotent, so this resumes cleanly
from the beginning rather than needing a `--start-at-task`.

**Second bug found post-deploy (2026-07-06): malformed `GRAYLOG_HTTP_EXTERNAL_URI`.**

`deploy-graylog-stack.yml` has three separate plays, each with its own
variable scope. Plays 1 (`Configure Graylog pilot host`) and 3 (the
`graylog_deploy_runtime: false` scaffold play) both define
`graylog_lab_fqdn_graylog` with a safe fallback
(`default('graylog.' ~ domain, true)`). Play 2 (`Deploy Graylog runtime
(optional)`) — the one that actually writes the real `graylog.env` used by
the running containers — did not define that variable at all, and instead
used a bare `lookup('env', 'LAB_FQDN_GRAYLOG')` with no fallback. Since
`LAB_FQDN_GRAYLOG` was never set in `.env` or `.env.pve` (see the findings
table above), this rendered as `GRAYLOG_HTTP_EXTERNAL_URI=https:///` on the
first production deploy — invisible to the ALIVE/HTTPS/LDAP checks that all
passed, since Traefik proxies through regardless and the browser mostly uses
relative URLs, but a real defect (would surface in email notification links,
redirect flows, etc).

**Fix:**
- `deploy-graylog-stack.yml`: added `graylog_lab_fqdn_graylog` (with the same
  fallback pattern) to play 2's `vars:`, and changed the env-file line to use
  it instead of the bare lookup.
- `.env.pve`: added `export LAB_FQDN_GRAYLOG="graylog.${LAB_DOMAIN}"`
  explicitly (belt-and-suspenders — the playbook fallback alone would now
  compute the right value, but explicit is better than implicit here).
- `.env.pve.template`: added the same line, next to `LAB_IP_GRAYLOG`.
- Redeployed `graylog-stack` (`scripts/provision.sh --stack graylog-stack
  --target-env pve`) to pick up the corrected `graylog.env` — this recreated
  the Graylog container (triggered by the `graylog_env_file.changed` handler,
  as designed). Smoke test passed (first time it actually *ran* on `pve`,
  since the pve-test-vm-only skip was removed in P1). Re-verified after
  recreate: `ALIVE`, HTTPS 200 via `graylog.lab.gibbsgreatly.xyz`, same
  `x-graylog-node-id` (confirms clean recreate, no data loss — node identity
  persists in the Mongo volume, not the container).
- `--syntax-check` passed before redeploying.

---

## Sprint P3 — Publish DNS, Traefik Route, and Authentik LDAP SSO

**Goal:** `https://graylog.lab.gibbsgreatly.xyz` resolves, loads over HTTPS,
and Authentik-credentialed login works — the production equivalent of the
pve-test-vm G2 gate.

**Implementation tasks**

1. Reprovision `technitium-stack` so it regenerates and republishes zone
   records, picking up the new `graylog-edge` manifest:
   ```bash
   PVE_ENV=pve ./with-secrets-prod scripts/provision.sh \
     --stack technitium-stack --target-env pve
   ```
2. Reconcile edge routing (Traefik + Authentik intents) and apply:
   ```bash
   PVE_ENV=pve ./with-secrets-prod python3 terraform/lxc/reconcile-edge.py \
     --authentik-url https://authentik-int.lab.gibbsgreatly.xyz:9443 \
     --apply --json
   ```
3. Reprovision `authentik-stack` so the LDAP provider/outpost/app are created
   against production Authentik (idempotent, no test-only gating):
   ```bash
   PVE_ENV=pve ./with-secrets-prod scripts/provision.sh \
     --stack authentik-stack --target-env pve
   ```
4. Verify end-to-end, same proof pattern as pve-test-vm G2:
   - `reconcile-edge.py --json` → `issue_count: 0`
   - DNS resolves via Technitium → HTTPS 200 through Traefik
   - Graylog LDAP auth backend active
   - **Manual action #6**: log in as yourself via Authentik credentials and
     confirm you land in the Graylog UI.

**Validation**

- Same checklist as "Minimum gate (G2 done)" earlier in this document, run
  against `pve` identities (`graylog.lab.gibbsgreatly.xyz`,
  `authentik-int.lab.gibbsgreatly.xyz`) instead of `test.gibbsgreatly.xyz`.

**Minimum gate**

- Browser login works end-to-end on `pve`. `reconcile-edge.py --json` shows
  `issue_count: 0` across all manifests, including `graylog-edge`.

### P3 status: complete (verified 2026-07-06)

The operator ran the tasks above directly from this doc ahead of the
step-by-step preflight walkthrough. Verified independently rather than taken
on trust:

- `dig graylog.lab.gibbsgreatly.xyz @192.168.20.15` (production Technitium) →
  `192.168.30.10` (`LAB_IP_PROXY`)
- `curl -D- https://graylog.lab.gibbsgreatly.xyz` → `HTTP/2 200`, body and
  `x-graylog-node-id` response header confirm it's genuinely Graylog, not a
  Traefik default/catch-all response
- `reconcile-edge.py --json` (dry-run) → `issue_count: 0` across all 8
  manifests, including `graylog-edge`; `terraform_state_mutation: false`
- Operator confirmed logging in via Authentik credentials and landing in the
  Graylog UI

**Minimum gate met.** Moving straight to Sprint P4.

---

## Sprint P4 — Cut Over Log Ingestion (Managed LXCs + Docker Stacks)

**Goal:** Repoint every existing production stack's `rsyslog_forward` at
Graylog, and remove VictoriaLogs from production `monitoring-stack` — the
production equivalent of pve-test-vm G3 + G5 combined.

**This is the highest blast-radius sprint in this plan** — it touches the
logging path on every managed LXC in production. The change-set itself was
already proven end-to-end via a full teardown-cycle validation on
`pve-test-vm` (G5), so per `CLAUDE.md`'s Validation Tiers this does not need
another full teardown on `pve` — the required gate is a clean incremental
deploy plus smoke test. Reprovision in dependency order (mirrors the existing
`stable` ordering used for `pve-test-vm`):

**Implementation tasks**

1. Reprovision every *other* production stack first, one at a time,
   confirming each is healthy before moving on — **`monitoring-stack` must be
   last, not first or in the middle.** `rsyslog_forward`'s defaults are
   already unconditionally Graylog-only in the current code
   (`rsyslog_forward_target_host` = `LAB_IP_GRAYLOG`, no VictoriaLogs branch
   left at all — confirmed 2026-07-06). That means the moment
   `monitoring-stack` is reprovisioned and its VictoriaLogs container is
   removed, any stack *not yet* reprovisioned would still be pointed at the
   old `monitoring-stack:5140` target and would just retry against a dead
   host until its own turn comes — no data loss (rsyslog's disk-backed queue
   retries indefinitely), but pointless connection-refused churn for however
   long the rollout takes. Order:
   `step-ca-stack`, `portainer-stack`, `authentik-stack`, `proxy-stack`,
   `harbor-stack`, `apt-cacher-stack`, `netbox-stack`, `ci-runner-01`, then
   **`monitoring-stack` last**:
   ```bash
   PVE_ENV=pve ./with-secrets-prod scripts/provision.sh --stack <name> --target-env pve
   ```
2. `monitoring-stack`'s reprovision (last) is expected to remove the
   VictoriaLogs container/volume, the Grafana VictoriaLogs datasource, and
   the `auth-logs.json` / `lab-logs.json` dashboards (the G5 diff, confirmed
   already absent from `deploy-monitoring-stack.yml` in the current code —
   applying it to `pve` for the first time). By the time this runs, every
   other stack is already forwarding to Graylog, so nothing is left depending
   on the VictoriaLogs sink being removed.
3. After each stack, confirm rsyslog restarted cleanly (handler fired) and
   send one smoke log line, confirming it lands in Graylog with correct
   `source` / `application_name`:
   ```bash
   logger -t p4-<stack>-smoke-test "P4_${STACK}_SYSLOG_PROOF"
   ```
   then search Graylog for it.

**Validation**

- Every reprovisioned stack's smoke-test / health check still passes.
- No stack shows a broken rsyslog forward (check for queue/connection errors).
- Grafana shows no orphaned VictoriaLogs datasource panels.
- Graylog shows fresh log lines from every reprovisioned stack.

**Minimum gate**

- All production stacks dual-sourced to Graylog only (no VictoriaLogs
  remaining anywhere on `pve`).

### P4 execution log (2026-07-06)

All 9 stacks reprovisioned in the corrected order (`monitoring-stack` last),
all succeeded, no failures. API-level validation (not just browser/"looked
fine" checks):

- Graylog search API (`POST /api/views/search/messages`, `range=900`) queried
  for `source:<hostname>` across all 9 stacks — all 9 returned real, recent,
  correctly-attributed log lines (e.g. `apt-cacher-stack` →
  `source=apt-cacher-stack`, `application_name=systemd`/`systemd-logind`).
  Note: this Graylog version rejects bare `*`/`*:*` match-all query strings
  (`400: not allowed as first character in WildcardQuery` / `Unrecognized
  query type: MatchAllDocsQuery`) — query by a specific `source:` value
  instead.
- VictoriaMetrics `/api/v1/targets?state=active` — every job 100% up
  (`node_exporter` 11/11 including the new `graylog-stack`), and the
  `victorialogs` scrape job is confirmed absent from the live target list.

**Found and fixed: two latent stale-provisioning bugs**, both pre-existing
(not introduced by this rollout) and only surfaced now because this was the
first time the G5 diff was ever applied to `pve`:

1. **Grafana datasources** — `/api/datasources` showed a `VictoriaLogs`
   datasource *and* an even older `Loki` datasource (dead since Phase 7)
   still registered. Cause: Grafana's file-based datasource provisioning is
   additive-only — removing a block from `datasources.yml` doesn't delete it
   from Grafana's persisted DB. Fixed by direct API deletion (`DELETE
   /api/datasources/uid/<uid>` for both `P8E80F9AEF21F6940` (Loki) and
   `VictoriaLogs`) since nothing references either anymore. Confirmed clean
   afterward: only `Harbor Findings` and `VictoriaMetrics` remain.
2. **Grafana dashboards** — `Auth Logs` and `Lab Logs` were still registered
   despite their JSON files having been deleted from the repo back in G5.
   Root cause: `deploy-monitoring-stack.yml`'s dashboard-copy task
   (`with_fileglob` over the repo's `dashboards/*.json`) only ever adds/updates
   files — it never removes destination files whose source was deleted, so
   the stale JSON files were still sitting on the LXC's disk. Grafana's own
   dashboard provider (`disableDeletion: false`) would have pruned them
   correctly if the files were actually gone, but only reconciles deletions
   at Grafana process start, not on its periodic re-scan — so simply fixing
   the file sync wasn't enough without also restarting Grafana.
   Direct API deletion doesn't work either: Grafana refuses
   (`"provisioned dashboard cannot be deleted"`, 400) for any
   provisioner-managed dashboard.
   **Fix, applied to `deploy-monitoring-stack.yml`:**
   - Added a "Clear stale Grafana dashboard JSON files" task
     (`state: absent` then `state: directory`) immediately before the copy
     task, so the destination directory is always wiped and rebuilt from
     the current repo contents on every deploy, instead of only ever
     growing.
   - Registered the copy task's result and added a "Restart Grafana after
     dashboard set changed" task (`docker compose restart grafana`, mirroring
     the existing Harbor-findings-exporter restart-on-change pattern) gated
     on that registration's `.changed`. Because the directory is wiped
     unconditionally first, the copy task's changed-status reliably reflects
     whether the current dashboard set differs from Grafana's last load —
     this fires on every future dashboard addition, edit, or removal, not
     just this one-time cleanup.
   - Required two reprovisions of `monitoring-stack` to land this: the first
     applied the file-sync fix (directory correctly cleared on disk) but
     Grafana still showed the stale dashboards since nothing had restarted
     it yet; the second (after adding the restart task) confirmed both
     dashboards gone via `/api/search`, leaving exactly the 8 dashboards
     `design.md` documents (CoreDNS, Docker Containers, 3× Harbor, Lab
     Overview, Node Detail, Traefik Ingress).
   - `--syntax-check` passed both times before each reprovision.

**Both fixes verified via live API queries, not visual inspection alone.**
Final state: `/api/datasources` → 2 entries (Harbor Findings,
VictoriaMetrics); `/api/search` → 8 dashboards, none referencing a removed
datasource.

---

## Sprint P5 — Remote Syslog Cutover: Proxmox Host, MikroTik, NAS

**Status:** handed off to the operator (2026-07-06) — the operator is running
this sprint directly (Proxmox host playbook fix/run, MikroTik RouterOS CLI,
NAS UI) rather than through the agent session. Steps below are left as the
reference checklist; not yet re-verified after hand-off.

**Goal:** Repoint the three non-Ansible-managed / host-level syslog sources
at production Graylog — the production equivalent of pve-test-vm G4.

**Implementation tasks**

1. ✅ **Done (2026-07-06).** Fixed the hardcoded host in
   `ansible/00-initial-setup/configure-proxmox-syslog.yml`:
   `hosts: pve-test-vm.gibbsgreatly.xyz` →
   `hosts: "{{ target_host | default('pve-test-vm.gibbsgreatly.xyz') }}"`.
   Verified with `--list-hosts` against both inventories: default (no
   `target_host`) still resolves `pve-test-vm.gibbsgreatly.xyz` against
   `ansible/inventory/dev.yml`; `-e target_host=pve.gibbsgreatly.xyz` resolves
   `pve.gibbsgreatly.xyz` against `ansible/inventory/production.yml`.
   `--syntax-check` passed against both inventories.
2. Run it against production:
   ```bash
   PVE_ENV=pve ./with-secrets-prod ansible-playbook \
     -i ansible/inventory/production.yml \
     ansible/00-initial-setup/configure-proxmox-syslog.yml \
     -e target_host=pve.gibbsgreatly.xyz \
     --limit pve.gibbsgreatly.xyz
   ```
3. **Manual action #4**: on the physical MikroTik, repoint
   `/system logging action set [find name=remote] remote=<production LAB_IP_GRAYLOG>`
   and confirm `remote-log-format=bsd-syslog` with ISO 8601 timestamps (same
   fix as pve-test-vm G4 — without it, MikroTik logs arrive fragmented across
   two source identities instead of a single `hAP`-style source).
4. **Manual action #5**: on the NAS's syslog settings UI, repoint its remote
   syslog target to the production Graylog IP, port 514.
5. Validate:
   ```bash
   # On the Proxmox host
   logger -t ansible-proxmox-syslog-test 'P5_PVE_SYSLOG_PROOF'
   ```
   Then in Graylog: `source:pve AND application_name:ansible-proxmox-syslog-test`
   should return the probe. Confirm real MikroTik and NAS traffic is also
   arriving and searchable by `source`.

**Validation**

- Same checklist as pve-test-vm G4, run against production identities/IPs.

**Minimum gate**

- Proxmox host, MikroTik, and NAS logs are all visible and attributable in
  production Graylog.

---

## Sprint P6 — Decommission Old Path, Cleanup, Promote to `main`

**Goal:** Close out the cutover.

**Implementation tasks**

1. Confirm no operator workflow still depends on Grafana log panels or
   VictoriaLogs anywhere in production.
2. Delete the now-permanently-dead scaffold branch in
   `deploy-graylog-stack.yml` (the `when: not (graylog_deploy_runtime | bool)`
   tasks deferred from P1), since every environment now always runs the real
   runtime.
3. Update `terraform/lxc/stacks/graylog-stack/STACK_CONTRACT.md` — it still
   describes the stack as an unpublished "scaffold," which has been stale
   since G2. Bring it in line with the real, running contract (published
   route, LDAP auth, syslog inputs).
4. Update `docs/monitoring-stack/design.md` "Current State" and "Remaining
   Work" to reflect `pve` completion.
5. Run the standard smoke test (Grafana + VictoriaMetrics + Graylog `ALIVE`).
6. PR `stable` → `main` per the branch model, once the incremental deploy and
   smoke test have passed. Note: this merge will also finally carry forward
   the already-live Technitium DNS cutover documentation that has been
   sitting on `stable` unmerged since 2026-07-04 — call this out in the PR
   description since the *infrastructure* change predates the *merge*.

**Validation**

- Full smoke test passes; no VictoriaLogs references remain in any compose
  or health check on `pve`.

**Minimum gate**

- `main` reflects the deployed, validated production state: Graylog is the
  only log workflow, metrics are unaffected, and the branch history matches
  reality.
