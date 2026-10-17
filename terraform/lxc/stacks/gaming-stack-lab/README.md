# gaming-stack-lab

`gaming-stack-lab` is the replacement game-services LXC. It runs in `game_seg`
(VLAN 60, `192.168.60.0/24`) and is managed through the lab Portainer endpoint.
It does not replace or modify `gaming-stack-legacy` (CT 103).

## Storage contract

| Guest path | Proxmox storage | Purpose |
| --- | --- | --- |
| `/var/lib/docker` | platform Docker mount | Docker images, layers, and volumes |
| `/srv/docker` | `gaming-containers` on pve | Compose projects and persistent game-server data |

The `/srv/docker` mount is an included, grow-only ZFS backup mount. Compose
projects use service-specific directories, beginning with
`/srv/docker/minecraft/foreverworld/`. Future services are siblings, for
example `/srv/docker/azerothcore/` and `/srv/docker/dayz/`; they are not part
of this implementation.

## Minecraft intake

Do not extract an unreviewed server tarball into the running stack. Stage it
for inspection, record its expected ownership and required Java/NeoForge
version, then create a reviewed compose project below
`/srv/docker/minecraft/foreverworld/`. Copy only the UUID-based `ops.json` and
`whitelist.json` handover settings from `gaming-stack-legacy`; do not copy the
legacy world or its RCON credential by default.

## Observability

Foreverworld runs under Pterodactyl/Wings, which names its game containers by
server UUID and owns port `:8080` (its API). Monitoring therefore runs as
standalone pieces beside Wings, not inside the game server's Compose project:

| Signal | Producer | Endpoint / destination |
| --- | --- | --- |
| LXC host health | `node_exporter` from `lxc_base` | HTTPS `:9100` |
| Per-container CPU, memory, disk and network | cAdvisor sidecar (`deploy-gaming-stack-lab-monitoring.yml`) | HTTP `:8082` (8080 is Wings) |
| Minecraft availability, status latency and player count | `itzg/mc-monitor` sidecar (same playbook), queries the published `:25565` | HTTP `:8081` |
| JVM heap, GC, threads and process metrics | Prometheus JMX Java agent inside the server (`deploy-foreverworld-jmx-agent.yml`), reached through a socat proxy on `pterodactyl_nw` | HTTP `:9404` |
| System and Docker logs | rsyslog forwarding from `lxc_base` | Graylog TCP `:514` |

Only the monitoring stack may reach the four metrics endpoints through
`game_seg` (`ansible/00-initial-setup/mikrotik-game-seg.yml`). The provisioned
Grafana dashboard is named **Foreverworld**. monitoring-stack relabels the
Wings container UUID to `foreverworld-minecraft` so the dashboard's container
panels match; the UUID is `monitoring_foreverworld_server_uuid` in
`deploy-monitoring-stack.yml` and `fw_server_uuid` in the JMX playbook (Panel
-> server -> Settings). JVM internals beyond the agent's heap/GC/thread data and
mod/game tick timings still require separately approved modpack instrumentation.

History: the Pterodactyl cutover (2026-09-26) dropped the Compose-era mc-monitor,
cAdvisor and JMX pieces and the dashboard went blank; the node_exporter on this
host was additionally killed by a certificate-renewal SIGHUP on 2026-10-12 (see
`node-exporter-renew-fix.yml`).
