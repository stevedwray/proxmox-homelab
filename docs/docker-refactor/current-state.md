# Docker Socket Proxy Current State

## Purpose

This note captures the current state of the Docker socket proxy refactor so the
work can pause cleanly and resume later without re-reading every handback.

## Goal Status

The proof goal is functionally achieved, but the operational goal is not yet
complete.

Completed proof work:

- a managed, read-only `docker_socket_proxy` role exists
- the proxy was proven on a disposable Docker LXC on `pve-test`
- the proof was integrated into the teardown-test opt-in path
- NetBox was updated to ingest runtime service data from socket-proxy-backed
  Docker hosts
- a real-stack canary was completed on `monitoring-stack`
- the monitoring canary returned `/containers/json?all=1`
- mutating Docker API requests were blocked
- NetBox received runtime-derived services tagged with
  `runtime-source-socket-proxy`

If the question is "can we use docker-socket-proxy to inspect Docker-enabled
LXCs and get that runtime data into NetBox?", the answer is yes.

If the question is "can newly rebuilt managed infrastructure Docker containers
be depended on to have docker-socket-proxy ready after normal deploy?", the
answer is no. That deploy-time guarantee still needs implementation and a
`pve` teardown/rebuild validation.

## What Was Built

### Disposable proof path

- New disposable stack:
  - `terraform/lxc/stacks/docker-socket-proxy-test/`
- New playbooks:
  - `terraform/lxc/ansible/playbooks/deploy-docker-socket-proxy-test.yml`
  - `terraform/lxc/ansible/playbooks/test-docker-socket-proxy-role.yml`
- New role:
  - `terraform/lxc/ansible/roles/docker_socket_proxy/`

### Teardown-test integration

- `scripts/teardown-deploy-test.sh`
- `docs/teardown-test/variables.md`
- `docs/teardown-test/runbook.md`
- `docs/teardown-test/repeatable-test.md`
- `docs/teardown-test/operations-plan.md`

### NetBox integration

- `terraform/lxc/stacks/netbox-stack/integrations/discover.py`
- `terraform/lxc/stacks/netbox-stack/integrations/populate.py`
- `terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md`
- `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`
- `scripts/verify-netbox-service-tags.py`

## Real-Stack Rollout Prep

The socket-proxy role has been wired into the six approved managed Docker
infrastructure stacks, all still disabled by default:

- `monitoring-stack`
- `netbox-stack`
- `harbor-stack`
- `proxy-stack`
- `authentik-stack`
- `portainer-stack`

Tracked source defaults remain disabled through:

```yaml
enable_docker_socket_proxy: false
```

No broad real-stack rollout has been performed.

Also not complete:

- stack metadata currently keeps `enable_docker_socket_proxy: false`
- static inventories do not carry socket-proxy enablement or bind variables
- `scripts/provision.sh` does not propagate stack socket-proxy metadata into
  Ansible extra-vars
- normal deploys therefore do not enable socket-proxy just because an LXC has
  Docker

## Live Rollout Status

### Completed canary

- `monitoring-stack` on `pve-test`

This canary proved:

- stack health remained good after enablement
- socket-proxy responded on port `2375`
- `GET /containers/json?all=1` returned runtime container data
- mutating calls such as `POST /containers/create` were blocked with `403`

### Not yet rolled out live

- `netbox-stack`
- `harbor-stack`
- `proxy-stack`
- `authentik-stack`
- `portainer-stack`

Those stacks are source-prepared only.

## NetBox Ingestion Status

NetBox ingestion is functionally proven for:

- disposable test host `docker-socket-proxy-test@pve-test`
- real-stack canary `monitoring-stack@pve`

Service objects created by the working path carry:

- `managed-by-proxmox-homelab`
- `netbox-env-*`
- `runtime-source-socket-proxy`

Cross-node environment tagging was also corrected so VM/service env tags follow
the VM's source node rather than the current run environment.

## Important Open Caveat

Session 56 in the NetBox workstream corrected an earlier diagnosis: Proxmox and
NetBox do have LXC IPs. Missing broad Docker application services are caused by
runtime inspection not being deployed/reachable on most managed Docker hosts.

The remaining work belongs here, not in NetBox:

- define the infrastructure Docker container set that must receive
  socket-proxy on deploy
- propagate `enable_docker_socket_proxy` and bind/listen vars from stack
  metadata or inventory into Ansible consistently
- enable the proxy only for the managed infrastructure Docker containers in
  scope
- validate on `pve` by rebuilding the infrastructure container set and proving
  each expected socket-proxy endpoint is reachable after rebuild

## Revised Completion Gate

This refactor is not finished until a `pve` teardown/rebuild validation of the
managed infrastructure Docker containers passes.

The gate must prove:

- only the managed infrastructure container set is touched
- no legacy/manual/non-infrastructure Docker LXCs are changed
- rebuilt Docker-enabled infrastructure containers have socket-proxy deployed
  and listening on the expected host IP and port
- read-only Docker endpoints such as `/containers/json?all=1` work
- mutating Docker API access remains blocked
- NetBox `populate.py --plan` can see the expected `/ipam/services/` changes

Until that gate passes, NetBox should not assume broad Docker application
service ingestion is available.
