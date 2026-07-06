# graylog-stack — Stack Contract

## Purpose

Production log platform for the homelab. Graylog 7.1.3 (Data Node +
MongoDB 7 + Graylog Server) is the sole browser-facing log workflow,
replacing the retired Promtail/VictoriaLogs path. Live on both
`pve-test-vm` and production `pve`. `monitoring-stack` remains focused on
`VictoriaMetrics` and Grafana metrics only.

Log volume is segmented into three index sets/streams (Security, Docker
Chatter, General) via Graylog Pipeline rules — see
[graylog-migration-plan.md](../../../../docs/monitoring-stack/graylog-migration-plan.md)
for the full migration record and query conventions.

## Network

| Field | Value |
|---|---|
| Zone | `mgmt_seg` |
| IP | `${lab_ip_graylog}/24` |
| Gateway | `${lab_gw_mgmt}` |
| VMID | 20014 |

## Inputs

| Input | Source | Notes |
|---|---|---|
| `LAB_IP_HARBOR` | env var | Docker registry host used for image pull config |
| `LAB_IP_APT_CACHER` | stack.yaml / env | Apt cache path for host bootstrap |
| `LAB_IP_DNS` | env var | Docker daemon DNS setting |
| `LAB_IP_AUTHENTIK` | env var | LDAP outpost host for Graylog's LDAP auth backend |
| `LAB_FQDN_GRAYLOG` | env var | Public FQDN for the published Graylog route |
| `LAB_FQDN_HARBOR` | env var | Registry FQDN used for image pull auth |
| `HARBOR_ADMIN` / `HARBOR_ADMIN_PASSWORD` | secrets | Registry pull credentials |
| `GRAYLOG_PASSWORD_SECRET` | secrets | Graylog/Data Node password-encryption secret |
| `GRAYLOG_ROOT_PASSWORD` | secrets | Graylog `admin` password (also used for REST API auth by this playbook) |
| `GRAYLOG_ROOT_PASSWORD_SHA2` | secrets | SHA-256 of the admin password, written to the runtime env file |
| `AUTHENTIK_SUPERUSER_PASSWORD` / `AUTHENTIK_STEVE_PASSWORD` / `AUTHENTIK_LDAP_SERVICE_PASSWORD` | secrets | Used by the LDAP SSO configuration tasks in this playbook |
| `GRAYLOG_DEPLOY_RUNTIME` | env var (set by `scripts/provision.sh`) | Always `true`; historical gate from the initial pilot rollout, kept for explicitness |

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| Graylog web UI / REST API | 9000 | TCP / HTTP | Published via Traefik at `https://graylog.${LAB_DOMAIN}`; native login backed by Authentik LDAP |
| Syslog input | 514 | UDP | Appliance / host syslog input (MikroTik, NAS) |
| Syslog input | 514 | TCP | Managed-host and Proxmox host syslog input (via local rsyslog relay to Graylog `:5140`) |

`stack.yaml` service identifiers: `graylog-http`, `graylog-syslog-udp`,
`graylog-syslog-tcp`.

## Dependencies

- `harbor-stack` for image pulls
- `apt-cacher-stack` for host package bootstrap
- `step-ca-stack` for certificate / trust alignment
- `authentik-stack` for LDAP-backed login
- `proxy-stack` (Traefik) for the published browser route

## Persistent State

| Path | Storage | Contents |
|---|---|---|
| `/opt/graylog-stack` | LXC host filesystem | Compose project and runtime env file |
| Docker volume `mongodb_data` | Docker storage | MongoDB metadata (streams, users, pipelines, index set config) |
| Docker volume(s) for Data Node | Docker storage | OpenSearch indices — `graylog_*`, `security_*`, `docker_chatter_*` index sets |

## What May Depend on This Stack

- Managed-LXC and Docker Compose stacks forwarding syslog/container logs (all stacks now forward here by default)
- Remote syslog sources: Proxmox host, MikroTik, Omada Controller, NAS
- Authentik's LDAP outpost, used as Graylog's authentication backend

## What Must Not Be Edited Casually

- The reserved IP, VMID, and mgmt-segment placement should stay stable unless the operator explicitly reassigns them.
- Index set rotation/retention settings (`Security` P90D/120D, `Docker Chatter` P7D/10D, default `General` P30D/40D) reflect a deliberate content-type/retention split — don't change `use_legacy_rotation` or `data_tiering` without re-reading Sprint P7 in the migration plan.
- The Pipeline rules that route messages to streams (`route-docker-chatter`, `route-security-auth`, `rewrite-omada-source`) are Ansible-tracked; make changes there, not via ad hoc API calls.

## Playbook

`deploy-graylog-stack` — two plays: host bootstrap (Docker daemon config,
registry auth) and full runtime deploy (compose up, index sets, streams,
pipelines, LDAP SSO configuration). The runtime always deploys
(`GRAYLOG_DEPLOY_RUNTIME` is unconditionally `true`); the historical
scaffold-only play has been removed now that every environment runs the
real deployment.

## Notes

- See [graylog-migration-plan.md](../../../../docs/monitoring-stack/graylog-migration-plan.md) for the full sprint-by-sprint migration record (G0–G5 on `pve-test-vm`, P0–P7 on `pve`).
