# Docker runtime host matrix — Session 56

**Corrected diagnosis**: Proxmox discovery and NetBox contain LXC IPs; the cause
of missing runtime services is not missing Proxmox IPs. Instead, only a
small subset of hosts expose a reachable Docker runtime inspection path
(docker-socket-proxy or Portainer). Populate and discovery show that
`docker-socket-proxy-test` exposes a socket-proxy; most other Docker hosts
do not have a reachable socket-proxy endpoint.

| stack | host/LXC | IP | expected Docker host | socket proxy declared | socket proxy reachable | services discovered | next action |
|---|---:|---|---:|---|---:|---:|---|
| docker-socket-proxy-test | docker-socket-proxy-test@pve-test | 192.168.1.53 | yes | no (not declared via `docker_socket_proxy_targets`) | yes (_ping 200) | docker-socket-proxy-2375, portainer-agent (populate: containers=5) | Treat as runtime-inspectable; add `docker_socket_proxy_targets` or document as runtime-only host |
| test-docker | test-docker@pve | 192.168.1.52 | yes | no | no (/_ping failed) | none observed | If runtime inspection desired, deploy socket-proxy or enable Portainer agent on this host |
| portainer-stack | portainer-stack@pve | ${lab_ip_portainer} (env) | yes | yes (`docker_socket_proxy_targets` present) | unresolved (IP is env token) | services discovered via Portainer (populate plan shows portainer-* services) | Resolve `LAB_IP_PORTAINER` or set `PORTAINER_SERVER_IP` and ensure `PORTAINER_ADMIN_PASSWORD` for Portainer-based discovery |
| net-app-01 | net-app-01@pve | 192.168.1.71 | yes | no | no (_ping failed) | none observed | Consider deploying socket-proxy if you want runtime inspection |
| net-artifacts-01 | net-artifacts-01@pve | 10.57.0.62 | yes | no | no (_ping failed) | none observed | Consider deploying socket-proxy or use Portainer where available |
| net-build-01 | net-build-01@pve | 10.57.0.61 | yes | no | no (_ping failed) | none observed | (same) |
| net-client-01 | net-client-01@pve | 10.55.0.61 | yes | no | no (_ping failed) | none observed | (same) |
| net-client-02 | net-client-02@pve | 10.56.0.61 | yes | no | no (_ping failed) | none observed | (same) |
| net-isolated-01 | net-isolated-01@pve | 192.168.1.73 | yes | no | no (_ping failed) | none observed | (same) |
| net-service-01 | net-service-01@pve | 192.168.40.62 | yes | no | no (_ping failed) | none observed | (same) |
| net-service-02 | net-service-02@pve | 10.56.0.62 | yes | no | no (_ping failed) | none observed | (same) |
| net-svc-01 | net-svc-01@pve | 192.168.1.72 | yes | no | no (_ping failed) | none observed | (same) |
| test-storage | test-storage@pve | 192.168.10.64 | yes | no | no (_ping failed) | none observed | (same) |
| test-storage-extra | test-storage-extra@pve | 192.168.10.65 | yes | no | no (_ping failed) | none observed | (same) |

**Notes**:
- `socket proxy reachable`: result of probing `http://<ip>:2375/_ping` (5s timeout).
- `socket proxy declared`: whether the stack metadata contains `docker_socket_proxy_targets` or explicit enable flags.

**Next practical action (short)**: For runtime inspection, either (A) provision a socket-proxy on target hosts (or enable the role) and record the target IPs in `docker_socket_proxy_targets` in the corresponding `stack.yaml`; or (B) use Portainer (resolve `LAB_IP_PORTAINER`/`PORTAINER_SERVER_IP` and admin credentials) for hosts already managed by Portainer.
