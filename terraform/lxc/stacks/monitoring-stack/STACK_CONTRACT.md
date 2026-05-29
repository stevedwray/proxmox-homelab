# monitoring-stack — Stack Contract

## Purpose

Monitoring and observability stack for the pve-test environment.
VictoriaMetrics, Grafana, Loki, and Promtail provide metrics, dashboards,
logs, and the operator-facing observability entry point for the homelab.

## Network

| Field | Value |
|---|---|
| Zone | `mgmt_seg` |
| IP | `${lab_ip_monitoring}/24` |
| Gateway | `${lab_gw_mgmt}` |
| VMID | 20012 |

## Inputs

| Input | Source | Notes |
|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` | env var | Grafana admin password |
| `GRAFANA_ADMIN_USER` | env var | Grafana admin username; defaults to `admin` |
| `GRAFANA_BREAKGLASS_USERNAME` | env var | Optional local Grafana breakglass user; defaults to `breakglass` |
| `BREAKGLASS_PASSWORD` | env var | Optional Grafana breakglass password; defaults to the admin password if unset |
| `GRAFANA_OAUTH_CLIENT_SECRET` | env var | Authentik OIDC client secret for Grafana |
| `AUTHENTIK_SUPERUSER_API_TOKEN` | env var | Required for the OIDC client reconcile pre-task |
| `MONITORING_REGISTRY_HOST` | env var | Optional registry override; defaults to Harbor FQDN |
| `LAB_DOMAIN` | env var | Used to derive default FQDNs for Harbor, Grafana, and Authentik |
| `LAB_FQDN_HARBOR` | env var | Optional Harbor FQDN override |
| `LAB_FQDN_GRAFANA` | env var | Optional Grafana FQDN override |
| `LAB_FQDN_AUTHENTIK` | env var | Optional Authentik FQDN override |
| `LAB_ADMIN_USERNAME` | env var | Used in Grafana OIDC role mapping defaults |
| `LAB_IP_AUTHENTIK` | env var | Used for token and API backchannel defaults |
| `LAB_IP_HARBOR` | env var | Used when deriving temporary DNS/registry fallback behavior |
| `portainer_server_ip` | stack.yaml / env | Shared platform IP metadata |
| `registry_host` | stack.yaml / env | Harbor registry host used by the compose stack |
| `apt_cacher_host` | stack.yaml / env | Apt cache host passed through the stack metadata |

No secret values are committed here. All sensitive values must come from the environment.

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| Grafana HTTP | 3000 | TCP / HTTP | Operator dashboard and OIDC entry point |
| VictoriaMetrics HTTP | 8428 | TCP / HTTP | Metrics ingestion/query endpoint |
| Loki HTTP | 3100 | TCP / HTTP | Log storage/query endpoint |

`stack.yaml` service identifiers: `grafana-http`, `victoriametrics-http`, `loki-http`.

## Dependencies

- `harbor-stack` for registry access and image pulls.
- `apt-cacher-stack` for package cache availability during host provisioning.
- `authentik-stack` for Grafana OIDC client reconciliation and OAuth settings.
- `proxy-stack` for published Grafana edge access.
- `step-ca-stack` for the trust/certificate path used by the broader platform.

## Persistent State

| Path | Storage | Contents |
|---|---|---|
| `/opt/monitoring-stack` | LXC host filesystem / Docker compose project | Compose file, `.env`, and per-service config |
| `/opt/monitoring-stack/grafana/provisioning` | LXC host filesystem | Grafana datasource provisioning |
| `/opt/monitoring-stack/loki` | LXC host filesystem | Loki configuration |
| Docker volumes from compose | Docker storage | VictoriaMetrics, Grafana, and Loki runtime state |

## What May Depend on This Stack

- Any operator workflow that needs Grafana for observability or dashboards.
- Any service or stack that depends on monitoring data being queryable through VictoriaMetrics or Loki.
- Any future stack that relies on the monitoring OIDC integration or Grafana breakglass admin behavior.

## What Must Not Be Edited Casually

- The Authentik OIDC pre-task in `deploy-monitoring-stack.yml` is part of the contract and must remain aligned with the current edge manifest and Grafana OAuth settings.
- Temporary DNS fallback logic is intentionally part of the provisioning flow to tolerate host lookup failures during image pulls and compose deployment.
- The Grafana breakglass user bootstrap is intentionally idempotent and should remain safe to rerun.
- The monitoring compose layout under `/opt/monitoring-stack` is shared by host prep, compose deployment, and Grafana provisioning.
- `portainer_agent: false` in this stack is intentional; Monitoring does not publish a Portainer agent.

## Playbook

`deploy-monitoring-stack` (roles: `lxc_base`, `docker_base`, `direct_stack`)

## Notes

- This is a special-case integration stack because it coordinates observability, Grafana OAuth, and Authentik reconciliation.
- The current operator flow is: Terraform provisions the container and inventory, then Ansible prepares the host, deploys compose, reconciles OIDC, and bootstraps Grafana admin/breakglass state.
