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

Foreverworld uses the shared Grafana/VictoriaMetrics and Graylog services:

| Signal | Producer | Endpoint / destination |
| --- | --- | --- |
| LXC host health | `node_exporter` from `lxc_base` | HTTPS `:9100` |
| Per-container CPU, memory, disk and network | cAdvisor sidecar | HTTP `:8080` |
| Minecraft availability, status latency and player count | `itzg/mc-monitor` sidecar | HTTP `:8081` |
| JVM heap, GC, threads and process metrics | Prometheus JMX Java agent | HTTP `:9404` |
| System and Docker logs | rsyslog forwarding from `lxc_base` | Graylog TCP `:514` |

Only the monitoring stack may reach the four metrics endpoints through
`game_seg`. The provisioned Grafana dashboard is named **Foreverworld**.
These signals deliberately cover infrastructure and Minecraft protocol status;
JVM internals and mod/game tick timings require separately approved server or
modpack instrumentation.
