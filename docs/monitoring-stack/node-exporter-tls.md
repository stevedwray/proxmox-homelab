# node_exporter TLS + Basic Auth

**Status:** Implemented 2026-06-22. All 10 managed LXCs secured.

---

## Overview

node_exporter runs on all 10 managed LXCs and serves OS metrics on `:9100`. TLS
server certificates (issued from step-ca) and HTTP basic authentication are now
required for all scrapes. VictoriaMetrics scrapes over HTTPS and verifies the
homelab root CA; unauthenticated or unencrypted requests receive `401`.

---

## Security Design

### Threat addressed

Any host on any VLAN could scrape `/metrics` from any managed LXC. A compromised
container or LXC can enumerate memory, CPU, disk, network, open file descriptors,
and process counts for every other host in the lab. Traffic was also plaintext on
the SDN.

### Controls added

**TLS (server certificate) + HTTP basic authentication.**

- TLS: encrypted in transit; VictoriaMetrics verifies server identity.
- Basic auth: node_exporter rejects requests without the correct credential. A
  compromised LXC cannot scrape other LXCs even if it can reach port 9100.

### Why not mTLS?

mTLS would require the VictoriaMetrics Docker container to present a client cert
on each scrape. Any compromised host in the lab can request a client cert from
step-ca with a stolen provisioner password, so mTLS does not materially strengthen
the threat model beyond basic auth. Basic auth is equivalent gating with lower
operational complexity. mTLS is an option for a future hardening pass.

### Credential model

A single shared username (`prometheus`) and password across all managed LXCs:

- **On each LXC**: bcrypt hash stored in `/etc/node_exporter/web.config.yaml`
  (not reversible from the hash). File is `root:prometheus 0640`.
- **In SOPS** (`secrets.enc.yaml`, `secrets.pve.enc.yaml`): plaintext under
  `NODE_EXPORTER_SCRAPE_PASSWORD`, pre-generated bcrypt hash under
  `NODE_EXPORTER_SCRAPE_PASSWORD_HASH`. The hash is pre-generated to avoid
  `password_hash('bcrypt')` producing a new random salt on every Ansible run,
  which would cause always-changed behaviour.
- **On monitoring-stack**: VictoriaMetrics `scrape.yml` contains the plaintext
  password written by Ansible at deploy time. File is `root:root 0640`.

---

## Architecture

### Certificate issuance

Each managed LXC gets a TLS server certificate from the `homelab-admin` JWK
provisioner on step-ca.

| Field | Value |
|-------|-------|
| CN | `<inventory_hostname>` (e.g., `authentik-stack`) |
| IP SAN | `<ansible_host>` (LXC mgmt IP) |
| DNS SAN | `<inventory_hostname>` |
| Validity | 90 days (`--not-after 2160h`) |
| Renewal trigger | <30 days remaining |
| Renewal mechanism | systemd timer (daily, 03:00 ± 10m), SIGHUP on node_exporter after renewal |

The IP SAN is required because VictoriaMetrics connects to LXCs by IP address.

The `homelab-admin` provisioner was updated from its default 24h maximum to
`maxTLSCertDuration: 2160h` / `defaultTLSCertDuration: 720h` in `deploy-step-ca.yml`.

### File layout on each managed LXC

```
/etc/node_exporter/
├── certs/
│   ├── tls.crt          (step-ca issued, root:prometheus 0640)
│   └── tls.key          (private key, root:prometheus 0640)
├── web.config.yaml      (TLS + basic auth config, root:prometheus 0640)
├── renew-cert.sh        (renewal script, root:root 0750)
└── provisioner-password.txt  (step-ca provisioner password, root:root 0600)

/etc/systemd/system/
├── prometheus-node-exporter.service.d/
│   └── web-config.conf  (drop-in: adds --web.config.file flag)
├── node-exporter-cert-renew.service
└── node-exporter-cert-renew.timer
```

**Ownership note**: The config dir, cert dir, web.config.yaml, and both cert
files are group-owned by `prometheus` (the service user) to allow reading. The
provisioner password and renewal script are `root:root` — the renewal timer
service runs as root and does not need group access for those files. After each
renewal, the script runs `chown root:prometheus` and `chmod 0640` on the new cert
and key so the service can still read them after recreation.

### web.config.yaml format

```yaml
tls_server_config:
  cert_file: /etc/node_exporter/certs/tls.crt
  key_file: /etc/node_exporter/certs/tls.key

basic_auth_users:
  prometheus: <bcrypt-hash-of-NODE_EXPORTER_SCRAPE_PASSWORD>
```

### Renewal

The renewal service (`node-exporter-cert-renew.service`) runs daily via timer:

1. Checks if the cert expires within 30 days (`openssl x509 -checkend 2592000`)
2. If so, calls `step ca renew --force` against step-ca
3. Resets cert/key ownership to `root:prometheus 0640`
4. Sends `SIGHUP` to `prometheus-node-exporter` — node_exporter reloads TLS
   config without a full restart (supported since v1.0.0; Debian 13 ships 1.8.x)

### VictoriaMetrics scrape config

The `node_exporter` job in `deploy-monitoring-stack.yml` was changed from plain
HTTP to:

```yaml
- job_name: node_exporter
  scheme: https
  tls_config:
    ca_file: /etc/ssl/certs/homelab-root.crt
  basic_auth:
    username: prometheus
    password: "{{ node_exporter_scrape_password }}"
  static_configs:
    - targets: ["<ip>:9100"]
      labels: {stack: <name>}
    ...
```

The homelab root CA was already mounted into the VictoriaMetrics container at
`/etc/ssl/certs/homelab-root.crt`. No compose change was needed for CA trust.

---

## Ansible Role

The `node_exporter` role (`terraform/lxc/ansible/roles/node_exporter/`) is
self-contained. All TLS variables use `lookup('env', ...)` in `defaults/main.yml`
so no changes are needed to the 10 stack deploy playbooks — the role picks up
credentials from the environment loaded by `./with-secrets` or `./with-secrets-prod`.

The restart task fires **within the role** (not via a handler) so it executes
immediately when config changes, before any stack-specific downstream tasks. This
is important because some stack playbooks have post-role tasks that may fail for
unrelated reasons — a handler-based restart would be skipped if the play failed
before handler flushing.

---

## Rollback

To revert a single host to plain HTTP without removing the certs:

```bash
rm /etc/systemd/system/prometheus-node-exporter.service.d/web-config.conf
systemctl daemon-reload
systemctl restart prometheus-node-exporter
```

The cert files and web.config remain in place but are inert. To re-enable TLS,
restore the drop-in and restart.

To revert VictoriaMetrics scraping: redeploy monitoring-stack from a branch that
has the plain-HTTP `node_exporter` job. VictoriaMetrics reloads on restart.

---

## Out of Scope

The following scrape jobs were **not** changed:

| Job | Reason |
|-----|--------|
| cadvisor | Separate hardening concern |
| coredns | Separate effort |
| traefik | Separate effort |
| authentik | Already on verified internal TLS via nginx direct-TLS |
| harbor-* | Harbor metrics; separate effort |
| step-ca | Native HTTP metrics on :9443; different lifecycle |
| victoriametrics, grafana | monitoring-stack-internal; localhost equivalent |
| netbox | Application metrics; separate effort |

VictoriaMetrics itself (`:8428`) remains unauthenticated and mgmt_seg-internal.

---

## Security Analysis

### What this adds

| Control | Effect |
|---------|--------|
| TLS server cert | Encrypted in transit; VictoriaMetrics verifies server identity |
| IP SAN on cert | Cert is pinned to the LXC's IP; cannot be reused on a different host |
| Basic auth | Unauthenticated requests get `401`; only VictoriaMetrics with the credential can scrape |
| Bcrypt hash in web.config | Password not stored reversibly on the LXC |
| SOPS-encrypted plaintext | Password at rest on control node is encrypted; not in git history |

### What this does not add

- **Firewall rules restricting :9100**: any host on any VLAN can still reach
  the port — it will receive `401`. MikroTik ACL rules per-LXC to restrict `:9100`
  to the monitoring-stack IP only would complement this, but are out of scope.
- **Per-LXC credentials**: a credential compromise exposes all LXCs. Acceptable
  for this threat model.
- **mTLS**: VictoriaMetrics does not present a client cert.
- **Encryption of VictoriaMetrics storage**.

### Introduced risk

- **Step-ca dependency**: if step-ca is down during a full teardown + redeploy,
  cert issuance fails for all LXCs. step-ca-stack must be provisioned before any
  other stack in a full redeploy.
- **Cert expiry**: if the renewal timer fails silently for 90 days, all scrapes
  break. A VictoriaMetrics alert rule for `node_exporter` targets going `down` is
  the mitigation — tracked as follow-on work.
- **Rendered scrape.yml contains plaintext password**: `0640 root:root` on the
  monitoring-stack LXC. Acceptable within the existing threat model.

---

## Implementation Notes

Issues encountered during the June 2026 rollout:

**1. step-ca provisioner max cert duration defaulted to 24h.**
The `homelab-admin` provisioner had `"claims": {}`, which causes step-ca to
default to 24h max cert validity. The `--not-after 2160h` flag on `step ca
certificate` was rejected. Fixed in `deploy-step-ca.yml` by updating provisioner
claims via Jinja2 `selectattr`/`rejectattr` in the ca.json update task. The
original list comprehension syntax (`[expr if cond else other for x in list]`)
is not supported in Ansible's Jinja2 — use `selectattr`/`rejectattr` instead.

**2. File ownership: root:root blocked the prometheus service user.**
The `prometheus-node-exporter` service runs as `User=prometheus`. Config dirs and
TLS files owned `root:root` caused `permission denied` on startup. Fixed by
setting `group: prometheus` on the config dir, cert dir, web.config.yaml, and
both cert files. The renewal script sets the same after each renewal.

**3. Playbook task ordering on step-ca-stack.**
The `deploy-step-ca.yml` structure runs `lxc_base` (which includes the
`node_exporter` role and cert issuance) before the step-ca configuration update
tasks. On a live system where step-ca was already running, the provisioner max
duration had not yet been updated when the cert was requested. The fix was to
update ca.json directly via SSH first, then run the playbook. Longer term, the
ca.json update could be moved to `pre_tasks` for fresh deployments — tracked but
not yet addressed.

**4. Handler timing: restart did not fire when a downstream task failed.**
The original design used `notify: Restart node_exporter`. If any stack-specific
task after `lxc_base` failed (e.g., the CoreDNS zone assertion in `deploy-coredns.yml`),
the handler never fired and node_exporter ran without TLS. Fixed by converting to
an explicit in-role conditional restart task that fires immediately after config
changes, before any downstream tasks can run.

---

## Follow-on Work

| Item | Notes |
|------|-------|
| Alert rule: node_exporter target down | Catch cert expiry or service failure before it affects observability |
| MikroTik ACL: restrict :9100 to monitoring-stack IP | Network-layer complement to basic auth |
| Extend TLS to other unauthenticated scrape endpoints | cadvisor, CoreDNS, Traefik — separate plans per service |
| Move ca.json update to pre_tasks in deploy-step-ca.yml | Fixes fresh deploy ordering: step-ca must be configured before lxc_base runs cert issuance |
