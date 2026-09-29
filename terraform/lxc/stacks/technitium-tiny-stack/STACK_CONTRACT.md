# technitium-tiny-stack — Stack Contract

## Purpose

Second LAN DNS resolver, on `pve-tiny`, so LAN DNS survives `pve` being
down. Technitium cluster **secondary** of `technitium-stack` (the
primary, on `pve`). See `docs/lan-dns-technitium/plan.md`.

## Network

| Field | Value |
|---|---|
| Node | `pve-tiny` |
| Zone | `mgmt_seg` |
| IP | `${lab_ip_technitium_tiny}/24` (`192.168.20.17`) |
| Gateway | `${lab_gw_mgmt}` |
| VMID | 20017 |

## Inputs

| Input | Source | Notes |
|---|---|---|
| `LAB_IP_TECHNITIUM_TINY` | env var | **Mandatory.** This node's IP |
| `LAB_IP_TECHNITIUM` | env var | Informational: the cluster primary's IP (cluster join is an operator step, not automated) |
| `TECHNITIUM_ADMIN_PASSWORD` | env var (secret) | **Mandatory.** Same admin password as the primary; clustering syncs users from the primary after join |
| `LAB_DOMAIN` | env var | Defaults to `lab.gibbsgreatly.xyz` |

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| DNS resolver | 53 | UDP + TCP | LAN clients' second resolver (MikroTik DHCP `dns-server`). Serves cluster-synced copies of every zone on the primary |
| Web console / REST API | 5380 | TCP | Direct by IP only; no Traefik route |
| Cluster HTTPS | 53443 | TCP | Technitium cluster sync with the primary (self-signed, enabled automatically on cluster join) |

`stack.yaml` service identifiers: `dns-resolver` (tcp/53), `dns-resolver-udp` (udp/53), `technitium-cluster-https` (tcp/53443).

## Dependencies

- `technitium-stack` (pve) — cluster primary; source of all config and zones.
  Cross-node, so not in `stack.yaml`'s `depends_on`.
- Harbor (`registry_host`) for the Technitium image pull.
- `apt-cacher-stack` for package cache during host provisioning.

## Persistent State

| Path | Storage | Contents |
|---|---|---|
| Docker named volume `technitium-config` | Docker volume | Not a source of truth: settings, blocklists, apps and zones all come from the cluster primary. A rebuild re-joins the cluster (operator step) and re-syncs. |

## Observability and Security

Same as `technitium-stack`: node_exporter (:9100, TLS + basic auth, from
`lxc_base`), cAdvisor (:8080, `/opt/cadvisor`), Technitium metrics
(`/api/dashboard/metrics/text` on :5380, cluster-synced `metrics` token),
syslog + Docker logs + Technitium server log to Graylog, every DNS query
via the cluster-synced Log Exporter app to Graylog's "DNS Queries" index
set, Wazuh agent (FIM on `/opt/technitium-stack`, Docker monitoring),
unattended upgrades, GVM scanning (mgmt_seg), and LAN access limited to
DNS by `mikrotik-firewall-technitium-lan.yml`. Dashboard: Grafana
"Technitium DNS".

## What Must Not Be Edited Casually

- Settings, Allowed, Blocked and Apps are read-only here — change them on
  the primary (`configure-technitium-lan-resolver.yml`).
- `network_mode: host` is deliberate (see the plan's design decisions);
  do not copy it to other stacks.
- The image tag must equal `deploy-technitium-stack.yml`'s
  `technitium_image_tag` — cluster nodes must run the same version.
