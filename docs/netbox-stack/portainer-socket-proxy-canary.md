# Portainer Socket-Proxy Canary Runbook

Purpose and scope
- Purpose: Prepare a tracked canary PR that declares the Portainer LXC as a
  `docker-socket-proxy` probe target and documents how to deploy the listener
  safely for verification without enabling broad production rollout.
- Scope: repo-side PR + operator-run deploy in `pve-test` or controlled host;
  no automatic production enablement.

Safety note
- IMPORTANT: The commands shown under "Exact deploy command shapes" are live
  deploy commands and WILL MUTATE HOSTS. Treat them as destructive unless run
  inside a separately approved canary session. Use the `populate.py --plan`
  step below for read-only NetBox validation before any live run.

Preflight (pve-test / read-only)
- Verify targeting: confirm `with-secrets` resolves to `pve-test` before any
  validation that might contact services:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'  # must print: pve-test
```

- Render inventory for review (local):

```bash
scripts/render-inventory.py terraform/lxc/stacks/portainer-stack/stack.yaml
cat terraform/lxc/stacks/portainer-stack/inventory.generated.yml
```

- Read-only NetBox mapping with the socket-proxy URL template (no live deploy):

```bash
export DOCKER_SOCKET_PROXY_URL_TEMPLATE='http://{guest_ip}:2375'
export TF_VAR_proxmox_node=pve-test
./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py --plan
```

- Ansible validation note:
  local `ansible-playbook --syntax-check` is intentionally not part of this
  runbook because this workspace has produced noisy role-resolution results
  around local roles such as `lxc_base`. Run Ansible validation only in the
  separately approved canary session, after target confirmation.

Target confirmation guard
- Confirm NetBox already contains a VM/interface record for `${lab_ip_portainer}`.
- Confirm maintenance window and reviewer approval before any host changes.

Exact deploy command shapes
- WARNING: The commands below are LIVE deploys and WILL MUTATE TARGET HOSTS.
  Do not run them outside an approved canary session with reviewer sign-off.

- Current canary strategy:
  `stack.yaml` records the declared NetBox probe target, but deploy-time
  socket-proxy vars are not automatically propagated into Portainer inventory.
  The approved live canary should therefore pass explicit extra-vars.

- Explicit extra-vars deploy:

```bash
# LIVE deploy (mutates host) with explicit canary vars:
./with-secrets ansible-playbook \
  -i <inventory> \
  terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml \
  -u root -l portainer-stack \
  -e "enable_docker_socket_proxy=true" \
  -e "docker_socket_proxy_bind_addr=${LAB_IP_PORTAINER}" \
  -e "docker_socket_proxy_listen_port=2375"
```

- Future inventory-backed option:

```bash
# LIVE deploy (mutates host) after inventory.yml is intentionally updated:
./with-secrets ansible-playbook \
  -i terraform/lxc/stacks/portainer-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml \
  -u root -l portainer-stack
```

Listener verification
- HTTP probe (expect 200). Do not probe production hosts outside maintenance windows.

```bash
curl -fsS "http://${LAB_IP_PORTAINER}:2375/containers/json?all=1" || echo 'listener failed'
```

`populate.py --plan` verification
- After listener is up, re-run read-only population to confirm mapping to existing VM:

```bash
export DOCKER_SOCKET_PROXY_URL_TEMPLATE='http://{guest_ip}:2375'
./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py --plan
```

Acceptance criteria
- Listener responds 200 for `/containers/json?all=1` and shows expected containers.
- `populate.py --plan` attaches services only to the existing `portainer-stack` VM.
- No unexpected VM creations or NetBox object changes.
- No mutating proxy methods enabled (`docker_socket_proxy_post: false`).

Rollback vs removal
- Rollback (repo intent): create PR that sets `enable_docker_socket_proxy: false`
  and update inventory.yml; this prevents future redeploys but does NOT remove an
  existing compose project.
- Removal (manual/host): host-level cleanup is required to stop and remove the
  compose project (see emergency cleanup below). After removal, follow up with
  a repo revert PR to keep intent and inventory in sync.

Emergency host-level cleanup — MANUAL
- Use only when immediate removal is required and maintenance window is active.

```bash
ssh root@${LAB_IP_PORTAINER} 'docker compose -f /opt/docker-socket-proxy/docker-compose.yml down || true; rm -rf /opt/docker-socket-proxy'
```

Notes
- `stack.yaml` records declared probe candidates via `docker_socket_proxy_targets`, but
  the current inventory generation does not automatically propagate arbitrary
  stack keys into `inventory.yml`. This prep uses explicit canary extra-vars
  for deployment while keeping the repo-side NetBox target declaration tracked.

- Remember: `ansible-playbook` without `--check` is a LIVE run and WILL change
  the target host. The runbook's earlier wording that implied a normal
  `ansible-playbook` invocation is a "dry-run" has been removed. Check-mode
  is allowed only inside a separately approved canary session because it may
  still connect to target hosts.

Check-mode evidence
- Base Portainer check-mode passed with repo-local Ansible config:
  `ok=25 changed=1 skipped=53`.
- Enabled socket-proxy canary check-mode passed with explicit canary vars:
  `ok=29 changed=3 unreachable=0 failed=0 skipped=49 rescued=0 ignored=0`.
- Interpretation: the Portainer socket-proxy canary path is ready for a
  separately approved live canary window.
