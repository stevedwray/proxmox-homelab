# graylog-stack — Stack Contract

## Purpose

Dedicated Graylog pilot stack for the `pve-test-vm` logging migration. This
stack is intended to become the candidate browser-facing log platform while
`monitoring-stack` remains focused on `VictoriaMetrics` and Grafana metrics.

This scaffold reserves the stack identity, addressing, and host layout. It does
not yet publish a live Traefik/Auth route or declare the Graylog runtime fully
complete.

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
| `LAB_FQDN_GRAYLOG` | env var | Planned public FQDN for the Graylog route |
| `GRAYLOG_PASSWORD_SECRET` | env var / future secret | Planned Graylog password secret |
| `GRAYLOG_ROOT_PASSWORD_SHA2` | env var / future secret | Planned Graylog admin password hash |

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| Graylog web UI | 9000 | TCP / HTTP | Planned internal UI bind |
| Syslog input | 514 | UDP | Planned appliance / host syslog input |
| Syslog input | 514 | TCP | Planned managed-host syslog input |

`stack.yaml` service identifiers: `graylog-http`, `graylog-syslog-udp`,
`graylog-syslog-tcp`.

## Dependencies

- `harbor-stack` for image pulls
- `apt-cacher-stack` for host package bootstrap
- `step-ca-stack` for future certificate / trust alignment

## Persistent State

| Path | Storage | Contents |
|---|---|---|
| `/opt/graylog-stack` | LXC host filesystem | Compose and env scaffold |
| `/opt/graylog-stack/scaffold` | LXC host filesystem | Bootstrap notes and placeholders |
| Docker volumes from compose | Docker storage | Reserved for future runtime state |

## What May Depend on This Stack

- Future Graylog browser ingress and Authentik OIDC integration
- Remote syslog from Proxmox host and MikroTik during the later migration sprints
- Managed-LXC and Docker log forwarding once the central sink cutover begins

## What Must Not Be Edited Casually

- The reserved IP, VMID, and mgmt-segment placement are now part of the
  migration plan and should stay stable unless the operator explicitly reassigns
  them.
- Do not publish `edge.yaml` or DNS/Traefik routes until Graylog itself is
  deployed and validated.
- Keep `monitoring-stack` separate from this pilot unless the plan is revised.

## Playbook

`deploy-graylog-stack` (current scaffold: `lxc_base`, `docker_base`, host
bootstrap only)

## Notes

- This stack intentionally starts as a host/bootstrap scaffold before the final
  Graylog runtime shape is pinned.
- The next implementation step is to replace the scaffold compose placeholder
  with the chosen Graylog single-node deployment.
