# node_exporter TLS + Basic Auth — Design and Implementation Plan

## Overview

node_exporter runs on all 10 managed LXCs and serves OS metrics over plain HTTP
on `:9100`. There is no transport security and no authentication. VictoriaMetrics
scrapes it from the monitoring-stack LXC across mgmt_seg (and other VLANs), with
no firewall rules restricting who can reach `:9100`.

This document designs and plans the addition of TLS server certificates and HTTP
basic authentication to close that exposure.

---

## Security Design

### Threat being addressed

Any host on any VLAN can scrape `/metrics` from any managed LXC. A compromised
container or LXC can enumerate memory, CPU, disk, network, open file descriptors,
and process counts for every other host in the lab. The traffic is also plaintext
on the SDN.

### Chosen controls

**TLS (server certificate) + HTTP basic authentication.**

- TLS provides confidentiality in transit and verifies server identity (VictoriaMetrics
  confirms it is talking to the node_exporter it expects, not a rogue listener).
- Basic auth provides scraper authentication: node_exporter rejects requests
  without the correct credential, so a compromised LXC cannot scrape other LXCs
  even if it can reach port 9100.

### Why not mTLS?

mTLS would add client certificate verification on node_exporter. This requires the
VictoriaMetrics Docker container to present a client cert on each scrape, which
means issuing a client cert for the VM container and mounting it. That is a
meaningful operational addition relative to the threat: any compromised host in
the lab can still request a client cert from step-ca if it can reach the CA with
a stolen provisioner password. Basic auth provides equivalent scraper gating with
much lower implementation complexity. mTLS remains an option for a future hardening
pass after this baseline is operational.

### Why not TLS only?

TLS alone (no auth) encrypts the channel but does not prevent an authorized
network peer from scraping metrics. All managed LXCs already trust the homelab CA
(distributed by `lxc_base`), so any compromised LXC could reach `:9100` over
verified TLS and scrape freely. Basic auth adds a second independent control.

### Credential model

A single shared username/password is used across all managed LXCs. The password is:

- Stored as a bcrypt hash in each LXC's `/etc/node_exporter/web.config.yaml`
  (not reversible from the hash)
- Stored in plaintext in `secrets.enc.yaml` under key `NODE_EXPORTER_SCRAPE_PASSWORD`
  (SOPS-encrypted at rest; loaded by `./with-secrets` at deploy time)
- Written inline into the VictoriaMetrics `scrape.yml` at deploy time by Ansible
  (file is `root:root 0640` on the monitoring-stack LXC)

A per-host credential would require a SOPS entry per LXC and added role complexity.
The shared credential is acceptable for this threat model: the goal is to prevent
any network-reachable host from freely scraping, not to isolate node_exporters
from each other.

---

## Architecture

### Certificate issuance

Each managed LXC gets a TLS server certificate issued from step-ca using the
`homelab-admin` JWK provisioner (same pattern as Authentik direct TLS).

| Field | Value |
|-------|-------|
| CN | `<stack-name>` (e.g., `authentik-stack`) |
| IP SAN | `<ansible_host>` (the LXC's mgmt IP) |
| DNS SAN | `<inventory_hostname>` (e.g., `authentik-stack`) |
| Validity | 90 days (`--not-after 2160h`) |
| Renewal trigger | <30 days remaining |
| Renewal mechanism | systemd timer (daily), SIGHUP on node_exporter after renewal |

VictoriaMetrics connects to LXCs by IP. The IP SAN is required for TLS
verification to succeed when the scrape target is an IP address.

### File layout on each managed LXC

```
/etc/node_exporter/
├── certs/
│   ├── tls.crt          (step-ca issued, 0644 root:root)
│   └── tls.key          (private key, 0600 root:root)
├── web.config.yaml      (TLS + basic auth config, 0640 root:root)
└── provisioner-password.txt  (step-ca provisioner password, 0600 root:root)

/etc/systemd/system/prometheus-node-exporter.service.d/
└── web-config.conf      (drop-in adding --web.config.file flag)
```

### web.config.yaml format

```yaml
tls_server_config:
  cert_file: /etc/node_exporter/certs/tls.crt
  key_file: /etc/node_exporter/certs/tls.key

basic_auth_users:
  prometheus: <bcrypt-hash-of-NODE_EXPORTER_SCRAPE_PASSWORD>
```

The bcrypt hash is generated at Ansible deploy time using the `password_hash`
filter: `{{ node_exporter_scrape_password | password_hash('bcrypt') }}`.

### Renewal timer

```
/etc/systemd/system/node-exporter-cert-renew.service
/etc/systemd/system/node-exporter-cert-renew.timer  (daily, OnCalendar=*-*-* 03:00:00)
```

The service script:
1. Checks if the cert expires within 30 days (`openssl x509 -checkend 2592000`)
2. If so, runs `step ca renew --force` against step-ca
3. Sends SIGHUP to `prometheus-node-exporter` to reload TLS config without restart

node_exporter has supported TLS config reload via SIGHUP since v1.0.0. Debian 13
ships 1.8.x.

### VictoriaMetrics scrape config changes

The `node_exporter` job in `victoria-metrics/scrape.yml` changes from:

```yaml
- job_name: node_exporter
  static_configs:
    - targets: ["192.168.20.10:9100"]
      labels: {stack: authentik-stack}
    ...
```

to:

```yaml
- job_name: node_exporter
  scheme: https
  tls_config:
    ca_file: /etc/ssl/certs/homelab-root.crt
  basic_auth:
    username: prometheus
    password: "<NODE_EXPORTER_SCRAPE_PASSWORD>"
  static_configs:
    - targets: ["192.168.20.10:9100"]
      labels: {stack: authentik-stack}
    ...
```

The homelab root CA is already mounted into the VictoriaMetrics container at
`/etc/ssl/certs/homelab-root.crt` (confirmed in `deploy-monitoring-stack.yml`
line 374). No compose change is needed for CA trust.

---

## Out of Scope

The following scrape jobs are **not** changed by this plan:

| Job | Reason |
|-----|--------|
| cadvisor | Separate hardening concern; Docker container metrics, not OS metrics |
| coredns | CoreDNS metrics endpoint; separate effort |
| traefik | Traefik metrics; separate effort |
| authentik | Already on verified internal TLS via nginx direct-TLS |
| harbor-* | Harbor metrics stack; separate effort |
| step-ca | Native HTTP metrics on :9443; different lifecycle |
| victoriametrics, victorialogs, grafana | monitoring-stack-internal; localhost equivalent |
| netbox | Application metrics; separate effort |

VictoriaMetrics itself (`:8428`) remains unauthenticated and mgmt_seg-internal.
That is a separate hardening concern.

---

## Implementation Plan

### Phase 1 — Prerequisites audit (no deploy)

**Goal**: Confirm every prerequisite before writing any Ansible code.

**Tasks**:

1. Verify step-ca health: `step ca health --ca-url https://<LAB_IP_STEP_CA> --root certs/homelab-root.crt`
2. Verify homelab root CA is present on all 10 managed LXCs:
   `ansible all -m stat -a "path=/usr/local/share/ca-certificates/homelab-root.crt"`
3. Verify step CLI status on managed LXCs:
   `ansible all -m stat -a "path=/usr/local/bin/step"`
   (Expected: absent — only step-ca-stack has it today. Authentik installs it
   as part of its own deploy; other stacks do not.)
4. Verify node_exporter version on a live LXC:
   `prometheus-node-exporter --version` (expect 1.8.x on Debian 13)
5. Confirm VictoriaMetrics container already has root CA mounted (already
   verified in design: `deploy-monitoring-stack.yml` line 374).
6. Confirm `STEP_CA_PROVISIONER_PASSWORD` is present in `secrets.enc.yaml`.
7. Add `NODE_EXPORTER_SCRAPE_PASSWORD` to `secrets.enc.yaml` (generate a strong
   random password; add to both `secrets.enc.yaml` and `secrets.pve.enc.yaml`).
8. Add `NODE_EXPORTER_SCRAPE_PASSWORD` to `.env.example` documentation comment
   (not the value — the key name, so operators know it is expected).

**Validation gate**:
- [ ] step-ca health check returns `ok`
- [ ] Root CA file present on all 10 hosts
- [ ] node_exporter version ≥ 1.0.0 confirmed on at least one host
- [ ] `NODE_EXPORTER_SCRAPE_PASSWORD` added to SOPS secrets, `sops -d` round-trip succeeds

**No deployment. No service changes. Stop here if any check fails.**

---

### Phase 2 — Extend node_exporter Ansible role

**Goal**: Make the role idempotent for TLS + basic auth. Role changes must not
break the existing plain-HTTP path on hosts where `monitoring_enabled` is false
or where step-ca is not yet reachable.

**Files to change**:

- `terraform/lxc/ansible/roles/node_exporter/tasks/main.yml` — extend with cert
  issuance, web.config write, systemd drop-in, renewal timer
- `terraform/lxc/ansible/roles/node_exporter/defaults/main.yml` — new (add
  variables with safe defaults)

**New variables** (in `defaults/main.yml`):

```yaml
node_exporter_tls_enabled: true
node_exporter_step_cli_version: "0.30.2"
node_exporter_cert_dir: /etc/node_exporter/certs
node_exporter_config_dir: /etc/node_exporter
node_exporter_scrape_username: prometheus
# These must be set by the caller when node_exporter_tls_enabled is true:
# node_exporter_step_ca_url
# node_exporter_step_ca_provisioner
# node_exporter_step_ca_provisioner_password
# node_exporter_scrape_password
```

**New tasks** (added to `main.yml`, all gated on `node_exporter_tls_enabled`):

```
1. Create /etc/node_exporter/{certs,} directories (0750 root:root)
2. Install step CLI (same download+install pattern as deploy-authentik-stack.yml)
3. Write provisioner password file (0600 root:root, no_log: true)
4. Issue or renew cert (same shell script pattern as authentik:
   - check if cert exists and has >30 days remaining
   - if not: step ca certificate <hostname> cert key --san <ip> --san <hostname>
     --ca-url ... --root ... --provisioner ... --password-file ... --force
   - changed_when: 'issued' in stdout)
5. Enforce key file permissions (0600 root:root)
6. Write /etc/node_exporter/web.config.yaml (0640 root:root):
   - tls_server_config.cert_file / key_file
   - basic_auth_users: { prometheus: <bcrypt-hash> }
7. Write systemd drop-in /etc/systemd/system/prometheus-node-exporter.service.d/web-config.conf:
   [Service]
   ExecStart=
   ExecStart=/usr/bin/prometheus-node-exporter --web.config.file=/etc/node_exporter/web.config.yaml
8. Reload systemd daemon
9. Restart prometheus-node-exporter (notify handler, fires once at end of play)
10. Write node-exporter-cert-renew.service + .timer
11. Enable and start node-exporter-cert-renew.timer
```

**Callers to update** — each deploy playbook that runs `lxc_base` (which calls
the `node_exporter` role) must pass the new variables. These are set in the play
`vars:` block, sourced from env vars:

```yaml
node_exporter_step_ca_url: "https://{{ lookup('env', 'LAB_IP_STEP_CA') | mandatory }}"
node_exporter_step_ca_provisioner: "{{ lookup('env', 'STEP_CA_PROVISIONER_NAME') | default('homelab-admin') }}"
node_exporter_step_ca_provisioner_password: "{{ lookup('env', 'STEP_CA_PROVISIONER_PASSWORD') | mandatory }}"
node_exporter_scrape_password: "{{ lookup('env', 'NODE_EXPORTER_SCRAPE_PASSWORD') | mandatory }}"
```

These go into the `vars:` block of the play that calls `lxc_base`. All 10 stack
deploy playbooks must be updated.

**Validation gate (syntax only — no live deploy)**:
- [ ] `ansible-playbook --syntax-check` passes on all 10 affected stack playbooks
- [ ] Role `defaults/main.yml` present and parseable
- [ ] All new tasks have `when: node_exporter_tls_enabled | default(true) | bool`
  guard so setting `node_exporter_tls_enabled: false` skips TLS tasks cleanly

---

### Phase 3 — Update VictoriaMetrics scrape config

**Goal**: Switch the `node_exporter` scrape job in `deploy-monitoring-stack.yml`
from plain HTTP to HTTPS with basic auth. Do not change any other job.

**File to change**:
- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`

**Change**:

Add `NODE_EXPORTER_SCRAPE_PASSWORD` to the play vars:

```yaml
node_exporter_scrape_password: "{{ lookup('env', 'NODE_EXPORTER_SCRAPE_PASSWORD') | mandatory('NODE_EXPORTER_SCRAPE_PASSWORD env var is not set') }}"
```

Change the `node_exporter` job in the scrape config `content:` block:

```yaml
- job_name: node_exporter
  scheme: https
  tls_config:
    ca_file: /etc/ssl/certs/homelab-root.crt
  basic_auth:
    username: prometheus
    password: "{{ node_exporter_scrape_password }}"
  static_configs:
    - targets: ["{{ lookup('env', 'LAB_IP_AUTHENTIK') }}:9100"]
      labels: {stack: authentik-stack}
    ...  (all existing targets unchanged)
```

No other jobs change. No compose file change (CA is already mounted).

**STACK_CONTRACT.md update**: add `NODE_EXPORTER_SCRAPE_PASSWORD` to the
monitoring-stack inputs table.

**Validation gate (syntax only)**:
- [ ] `ansible-playbook --syntax-check deploy-monitoring-stack.yml` passes
- [ ] Rendered scrape config (dry-run) contains `scheme: https`, `ca_file:`,
  `basic_auth:`, and all 10 existing target IPs

---

### Phase 4 — pve-test deploy and validation

**Goal**: Deploy the full change on pve-test and verify every scrape target
returns to green within one scrape interval.

**Deploy sequence**:

1. Provision monitoring-stack on pve-test to confirm baseline is green first.
   Confirm all 10 node_exporter targets are `up` in VictoriaMetrics before
   making any changes.
2. Deploy one stack (e.g., dns-stack) with the updated role to verify the role
   works end-to-end on a single host before rolling out all 10.
3. Manually verify on that LXC:
   - `/etc/node_exporter/certs/tls.crt` exists and has a valid cert from the homelab CA
   - `openssl x509 -text -noout -in /etc/node_exporter/certs/tls.crt` shows the correct IP SAN
   - `curl -k -u prometheus:<password> https://<ip>:9100/metrics` returns metrics
   - `curl -k https://<ip>:9100/metrics` returns `401 Unauthorized`
   - `curl -k -u wrong:wrong https://<ip>:9100/metrics` returns `401 Unauthorized`
   - `systemctl status node-exporter-cert-renew.timer` shows timer active
4. Deploy updated monitoring-stack (with new scrape config).
5. Wait one scrape interval (30s). Check VictoriaMetrics targets at
   `http://<monitoring-ip>:8428/targets`. All `node_exporter` targets must be `up`.
6. Deploy all remaining stacks with the updated role.
7. Confirm all 10 targets still `up`.

**Validation checklist**:
- [ ] All 10 node_exporter targets show `up` in VictoriaMetrics after deploy
- [ ] Grafana **Lab Overview** dashboard shows all hosts with data (no blank panels)
- [ ] Grafana **Node Detail** dashboard shows metrics for a spot-checked host
- [ ] `curl -k https://<ip>:9100/metrics` (no auth) returns `401` on each LXC
- [ ] `curl https://<ip>:9100/metrics -u prometheus:<password>` (with auth, no `-k`)
  returns metrics AND TLS validates against `certs/homelab-root.crt` without errors
- [ ] VictoriaLogs still receiving syslog from all hosts (unaffected by this change
  but verify no regressions: check `{hostname=~".*-stack"}` returns recent entries)
- [ ] All non-node_exporter scrape targets still `up` (cadvisor, coredns, traefik, etc.)
- [ ] Renewal timer fires correctly:
  - Manually run `systemctl start node-exporter-cert-renew` on one host
  - Confirm it exits 0 and node_exporter continues serving after SIGHUP

**Regression matrix**:

| Component | Check | Pass criteria |
|-----------|-------|---------------|
| node_exporter targets | VictoriaMetrics `/targets` | All 10 `up`, no `401` errors |
| Grafana Lab Overview | Visual check | All host rows populated, no "No data" |
| Grafana Node Detail | Visual check | CPU/mem/disk panels populated |
| cAdvisor targets | VictoriaMetrics `/targets` | All unchanged, still `up` |
| Other scrape jobs | VictoriaMetrics `/targets` | No new `down` targets |
| VictoriaLogs syslog | `{hostname=~".*"}` in last 5m | Entries present from all hosts |
| Grafana auth | Log in via Authentik | OAuth flow unaffected |
| node_exporter service | `systemctl status` on each LXC | `active (running)` |
| Cert validity | `openssl x509 -checkend 0` | Valid on all hosts |
| 401 on unauthenticated scrape | `curl` without credentials | `401 Unauthorized` |

**Stop here if any check fails. Do not proceed to Phase 5.**

---

### Phase 5 — Production (pve) deploy

After Phase 4 passes completely on pve-test:

1. Re-confirm `NODE_EXPORTER_SCRAPE_PASSWORD` is in `secrets.pve.enc.yaml`.
2. Run the deploy sequence from Phase 4 against pve targets (via `./with-secrets-prod`
   with `TASK_APPROVAL` set per production credential controls).
3. Apply the same validation checklist as Phase 4 against pve.
4. Update the monitoring-stack design.md "Current State" section to reflect that
   node_exporter scrapes are now TLS + basic auth authenticated.

---

## Rollback Plan

If validation fails at any phase, rollback is mechanical and safe:

**On managed LXCs (restore plain HTTP)**:
```bash
rm -f /etc/systemd/system/prometheus-node-exporter.service.d/web-config.conf
systemctl daemon-reload
systemctl restart prometheus-node-exporter
```
node_exporter reverts to plain HTTP on `:9100`. The cert and web.config files
can remain in place; they are inert without the drop-in.

**In VictoriaMetrics scrape config** (restore plain HTTP scraping):
- Redeploy monitoring-stack with the previous scrape config (revert the `scheme:`,
  `tls_config:`, and `basic_auth:` additions from the `node_exporter` job).
- VictoriaMetrics reloads config on restart.

Both rollbacks are idempotent and leave all other services untouched.

---

## Security Analysis

### What this adds

| Control | Effect |
|---------|--------|
| TLS server cert | Metrics traffic encrypted in transit; VictoriaMetrics verifies server identity |
| IP SAN on cert | Prevents cert from being reused on a different IP (cert pinned to LXC) |
| Basic auth | Unauthenticated requests (including from other LXCs) get `401`; only VictoriaMetrics with the credential can scrape |
| bcrypt hash in web.config | Password is not stored reversibly on the LXC itself |
| SOPS for plaintext password | Password at rest on control node is encrypted; not in git history |

### What this does not add

- **Firewall rules restricting :9100**: network-level access control remains VLAN
  segmentation only. A host on any VLAN can still connect to `:9100`; it will
  receive `401`. MikroTik ACL rules per-LXC IP to restrict `:9100` to the
  monitoring-stack IP only would be a complementary control, but are out of scope.
- **Per-LXC credentials**: a credential compromise exposes all LXCs. Acceptable
  for this threat model.
- **mTLS**: VictoriaMetrics does not present a client cert. Any process with the
  shared credential can scrape. This is acceptable; mTLS is a future option.
- **Encryption of VictoriaMetrics storage**: stored metric data is not encrypted.
  Separate concern.

### Introduced risk

- **Step-ca dependency for cert issuance**: if step-ca is down during a full
  teardown + redeploy, cert issuance for all LXCs will fail. Mitigation: Phase 1
  prerequisite check confirms step-ca is healthy before any deployment. If step-ca
  is down, the teardown cycle must restore step-ca-stack before deploying other stacks.
- **Cert expiry**: if the renewal timer fails silently for 90 days, all scrapes
  break. Mitigation: add a VictoriaMetrics alert rule for `node_exporter` targets
  going `down` (existing alerting gap, not introduced by this change). Track as
  follow-on work.
- **bcrypt compute cost at deploy time**: `password_hash('bcrypt')` is called 10
  times (once per host) during an Ansible run. On the control node this is
  negligible.
- **Scrape config contains plaintext password**: the rendered `scrape.yml` on the
  monitoring-stack LXC contains the plaintext password. File is `0640 root:root`
  and accessible only to root on that LXC. Acceptable within the existing threat model.

---

## Follow-on Work (not in this plan)

| Item | Notes |
|------|-------|
| Alert rule: node_exporter target down | Catch cert expiry or service failure before it affects observability |
| MikroTik ACL: restrict :9100 to monitoring-stack IP | Network-layer complement to basic auth |
| Extend TLS to other unauthenticated scrape endpoints | cadvisor, CoreDNS, Traefik — separate plans per service |
| Cert expiry Grafana panel | Show days-until-expiry per managed host using `x509_cert` exporter or custom metric |
