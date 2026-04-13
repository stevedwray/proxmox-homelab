# 00b-pve-test-03 — Pivot Portainer from vmbr0 to mgmt_seg

## Status

PENDING

## Phase

Phase 00b — pve-test Management Bootstrap

## GitHub Issue

Not assigned yet.

## Greenfield assumption

This task runs before any platform stacks (Harbor, apt-cacher, CI runner) are deployed
through Portainer. Because no containers are yet registered with the vmbr0 Portainer, the
old instance can be destroyed and rebuilt cleanly with no migration of registrations.

## Prerequisites

- Task 00b-01 complete — Portainer running on `192.168.1.20` (VMID 120) on `vmbr0`
- Task 00b-02 complete — `TF_VAR_portainer_server_ip=192.168.1.20` set in `.env.pve-test`
- Phase 00a-02 complete — `mgmt_seg` SDN VLAN zone active on pve-test (`tvmgmt`, VLAN 20,
  `10.57.1.0/24`)
- MikroTik route for `10.57.1.0/24 → 192.168.1.40` is active
- `PORTAINER_ADMIN_PASSWORD` in `.env`

## Network placement

| Field | Value |
|---|---|
| Zone | `mgmt_seg` |
| VLAN | 20 |
| VNet | `tvmgmt` |
| IP | `10.57.1.20` |
| Gateway | `10.57.1.1` |
| VMID | 120 |

## Objective

Portainer moves off the flat LAN (`vmbr0`) and onto `mgmt_seg` (`10.57.1.20`).
All subsequent stack deploys (Phase 03b onwards) register with the `mgmt_seg` Portainer.
The `192.168.1.20` address is decommissioned.

## Why this matters

Portainer has root-equivalent access to the Docker socket on every LXC it manages. Leaving
it permanently on the flat LAN exposes that access to any device on `192.168.1.0/24`.
`mgmt_seg` is routed only through MikroTik, which applies access control — the management
plane belongs there.

## Scope

- Update `terraform/lxc/stacks/portainer-stack/stack.yaml` to target `mgmt_seg`
  (`tvmgmt`, VLAN 20, IP `10.57.1.20`, gateway `10.57.1.1`)
- Destroy the current vmbr0 Portainer (`terragrunt destroy`)
- Redeploy Portainer on `mgmt_seg` (`terragrunt apply` + Ansible playbook)
- Update `TF_VAR_portainer_server_ip=10.57.1.20` in `.env.pve-test`
- Verify Portainer is reachable and the local Docker endpoint is registered

## Out of Scope

- Registering any containers with the new Portainer (that happens in later phase tasks)
- Traefik / TLS for the Portainer UI (Phase 04)

## Expected Outputs

- `portainer-stack/stack.yaml` targets `mgmt_seg` / `10.57.1.20`
- VMID 120 running at `10.57.1.20`
- `.env.pve-test` exports `TF_VAR_portainer_server_ip=10.57.1.20`
- `192.168.1.20` returns no reply to ping

## Acceptance Criteria

- [ ] `portainer-stack/stack.yaml` network placement updated to `mgmt_seg` / `10.57.1.20`
- [ ] `terragrunt destroy` for the old portainer-stack exits 0
- [ ] `terragrunt apply` for the rebuilt portainer-stack exits 0
- [ ] Ansible playbook run exits 0
- [ ] `curl -s http://10.57.1.20:9000/api/system/status` returns HTTP 200
- [ ] Portainer admin login works with `PORTAINER_ADMIN_PASSWORD`
- [ ] Portainer shows the local Docker environment as an endpoint
- [ ] `ping -c 3 192.168.1.20` returns no reply
- [ ] `echo "$TF_VAR_portainer_server_ip"` prints `10.57.1.20` after sourcing env files

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Rebuild Portainer on mgmt_seg (10.57.1.20) and decommission the vmbr0 instance.

STEP 0 — Verify prerequisites:
  source .env && source .env.pve-test
  echo "$TF_VAR_proxmox_node"   # must print pve-test
  curl -s http://192.168.1.20:9000/api/system/status   # old Portainer must be up
  ping -c 1 10.57.1.1   # mgmt_seg gateway must be reachable

STEP 1 — Update stack.yaml network placement:
  Read terraform/lxc/stacks/portainer-stack/stack.yaml
  Change the network section to use:
    zone: mgmt_seg
    vnet: tvmgmt
    vlan: 20
    ip: 10.57.1.20
    gateway: 10.57.1.1

STEP 2 — Destroy the old Portainer:
  cd terraform/lxc/stacks/portainer-stack
  terragrunt destroy
  ping -c 3 192.168.1.20   # expect no reply

STEP 3 — Deploy the new Portainer on mgmt_seg:
  terragrunt apply

STEP 4 — Run the Ansible playbook:
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.1.20," \
    terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

STEP 5 — Verify the new Portainer:
  curl -s http://10.57.1.20:9000/api/system/status
  # Expect HTTP 200 / JSON payload

STEP 6 — Update the env var:
  In .env.pve-test, change:
    TF_VAR_portainer_server_ip=192.168.1.20
  to:
    TF_VAR_portainer_server_ip=10.57.1.20

STEP 7 — Commit the stack.yaml change:
  git add terraform/lxc/stacks/portainer-stack/stack.yaml .env.pve-test
  git commit -m "feat(portainer): pivot portainer-stack from vmbr0 to mgmt_seg (10.57.1.20)"

DONE WHEN: Portainer is healthy at 10.57.1.20:9000, the local Docker endpoint is
registered, and 192.168.1.20 is unreachable.
```
