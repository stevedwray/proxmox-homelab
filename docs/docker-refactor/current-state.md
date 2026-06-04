# Docker Socket Proxy Current State

## Purpose

This note captures the current state of the Docker socket proxy refactor so the
work can pause cleanly and resume later without re-reading every handback.

## Goal Status

The core goal is functionally achieved:

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

The last monitoring NetBox proof required a narrow augmentation in
`populate.py` because the standard `pve-test` Proxmox discovery did not return
the monitoring VM. The current patch maps declared stack IPs to existing NetBox
VMs when `DOCKER_SOCKET_PROXY_URL_TEMPLATE` is set, allowing the standard
populate flow to probe those hosts and attach runtime services.

This works, but it is the main remaining design question in the work:

- keep the current augmentation
- replace it with a cleaner explicit target-selection mechanism
- or fix Proxmox/discovery coverage so the augmentation is unnecessary

So the work is functionally complete enough to move on, but there is still one
architectural decision to make before treating the implementation as fully
polished.

## Recommended Pause Point

This is a good place to pause and move to other work.

If this refactor is resumed later, the next decision should be:

1. accept the current `populate.py` augmentation as the intended design, or
2. replace it with a cleaner discovery/targeting model before broader rollout

After that, the next operational step would be choosing whether to enable the
proxy on the next real stack in the prepared set.
