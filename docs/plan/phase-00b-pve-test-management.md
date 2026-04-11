# Phase 00b — pve-test Management Bootstrap

## Goal

Make pve-test a **fully standalone deployment target** that does not depend on any service
running on the production `pve` node. This is essential because:

1. When `pve` is eventually rebuilt, `192.168.1.4` (production Portainer) will not exist
2. All pve-test stacks with `portainer_agent: true` need a local Portainer server to
   register with — if they point at the production Portainer, a pve rebuild breaks the
   entire validation pipeline
3. Any CI workflow targeting pve-test must be verifiable without production infrastructure
   being healthy

Currently, all stacks deployed to pve-test silently depend on the production Portainer at
`192.168.1.4` via the `TF_VAR_portainer_server_ip` default. This phase fixes that by
deploying a dedicated Portainer server on pve-test and updating the `.env.pve-test`
override accordingly.

## Prerequisites

- Phase 00 (housekeeping) complete
- pve-test is reachable and SSH-accessible as `root@pve-test.gibbsgreatly.xyz`
- `.env.pve-test` sourced (sets `TF_VAR_proxmox_node=pve-test`)
- Docker Hub accessible from pve-test (required for bootstrap — see Part C)

## Related plan phases

- All pve-test deployments in Phase 01 onwards implicitly depend on this phase being complete
- Phase 03b (Harbor) — once Harbor is deployed, Portainer image updates should go through Harbor
- Phase 04 (core shared services) — all Phase 04 stacks on pve-test register here

---

## IP / VMID allocation

| Service | IP | VMID | Node | Zone |
|---|---|---|---|---|
| Portainer server (pve-test) | `192.168.1.20` | 120 | pve-test | `infra` (vmbr0) |

Verify `192.168.1.20` is free before assigning:

```bash
source /home/steve/git/proxmox-homelab/.env && source .env.pve-test
curl -s -H "Authorization: Token ${NETBOX_SUPERUSER_API_TOKEN}" \
  "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.20" | jq .count
# Expected: 0
```

---

## Part A — Stack definition

Create `terraform/lxc/stacks/portainer-stack/stack.yaml`:

```yaml
# Portainer CE management server — pve-test standalone deployment target
# Provides container management UI and endpoint registry for all pve-test stacks.
# This stack is intentionally NOT registered as a Portainer agent (it IS the server).
hostname: portainer-stack
ip_address: "192.168.1.20/24"
gateway: "192.168.1.1"
vmid: 120
cores: 1
memory: 512
swap: 256
rootfs_size: 8
rootfs_storage: infrastructure-containers
docker_storage_size: "10G"
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - portainer
  - management
  - infrastructure
  - docker

ansible_playbook: "deploy-portainer-stack"
portainer_agent: false    # this IS the Portainer server — no agent registration
```

Copy `terraform/lxc/stacks/harbor-stack/terragrunt.hcl` to
`terraform/lxc/stacks/portainer-stack/terragrunt.hcl` unchanged.

---

## Part B — Ansible playbook

Create `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml`:

The playbook has two plays:

**Play 1 — Docker base**

Use the `docker_base` role (standard, as all Docker LXCs). Do **not** use `portainer_api`
or `portainer_agent` roles — those are for clients registering with a server, not the
server itself.

**Play 2 — Deploy Portainer server**

Deploy Portainer CE in server mode via Docker Compose:

```yaml
services:
  portainer:
    image: portainer/portainer-ce:2.27.3    # pin version — do not use latest
    restart: unless-stopped
    ports:
      - "9000:9000"     # UI and HTTP API
      - "9443:9443"     # HTTPS UI (optional, self-signed)
      - "8000:8000"     # Edge agent tunnel (needed if edge agents are used later)
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/lib/portainer:/data
```

> **Note on image source:** This stack is deployed as part of the bootstrap sequence,
> before Harbor is fully configured (Phase 03b). It is one of **two permitted exceptions**
> to the Harbor-only pull rule (the other being Harbor itself). Pull `portainer-ce` directly
> from Docker Hub for this initial bootstrap. Once Harbor's `dockerhub` proxy project is
> configured in Phase 03b, update the image reference to
> `192.168.1.10/dockerhub/portainer/portainer-ce:2.27.3` and redeploy.

**Play 3 — Initialise admin account**

Bootstrap the Portainer admin user via the API (only runs if not already initialised):

```bash
curl -s -X POST http://192.168.1.20:9000/api/users/admin/init \
  -H "Content-Type: application/json" \
  -d "{\"Username\":\"admin\",\"Password\":\"${PORTAINER_ADMIN_PASSWORD}\"}"
# Returns 200 on success, 409 if already initialised (idempotent)
```

The Ansible task should use `uri` module with `status_code: [200, 409]` to be idempotent.
The admin password comes from `{{ lookup('env', 'PORTAINER_ADMIN_PASSWORD') }}`.

---

## Part C — Deploy

```bash
cd /home/steve/git/proxmox-homelab

# Source pve-test credentials (must be last to ensure pve-test wins):
source .env && source .env.pve-test
echo "Target node: $TF_VAR_proxmox_node"   # must print: pve-test

# Provision the LXC:
cd terraform/lxc/stacks/portainer-stack
terragrunt apply

# Configure Portainer:
cd /home/steve/git/proxmox-homelab
ansible-playbook \
  -i terraform/lxc/stacks/portainer-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml
```

---

## Part D — Update `.env.pve-test`

After Portainer is running at `192.168.1.20`, add the override to `.env.pve-test`:

```bash
# Portainer server for pve-test (overrides production default of 192.168.1.4)
export TF_VAR_portainer_server_ip=192.168.1.20
```

This ensures all subsequent `terragrunt apply` runs against pve-test will register
Portainer agents with the local server, not the production one.

Also add the placeholder to `.env.template`:

```bash
# pve-test overrides (set in .env.pve-test, not here)
# TF_VAR_portainer_server_ip=192.168.1.20   # pve-test Portainer
```

---

## Part E — Re-register existing pve-test stacks

Once the pve-test Portainer is running, existing pve-test stacks that registered with the
production Portainer should be re-registered. Run the Ansible playbook for each affected
stack (the `portainer_api` play is idempotent and will create the endpoint on the new
server):

```bash
source .env && source .env.pve-test

# Re-register the CI runner:
ansible-playbook \
  -i terraform/lxc/stacks/ci-runner-01/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml \
  --tags portainer

# Re-register netbox-stack-test:
ansible-playbook \
  -i terraform/lxc/stacks/netbox-stack-test/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml \
  --tags portainer
```

If the playbooks do not have a `portainer` tag, run the full playbook — the `portainer_api`
role is idempotent (it checks for an existing endpoint before creating one).

---

## Storage pool note

pve-test has **two storage pools in use** for LXC rootfs and Docker data:

| Pool name | Used by |
|---|---|
| `infrastructure-containers` | LAN-attached stacks (ci-runner-01, netbox-stack-test, harbor-stack, portainer-stack, Phase 04 stacks) |
| `storage-containers` | SDN-zone stacks (net-\* validation stacks) |

All Phase 03b, 03c, and 04 stacks should use `rootfs_storage: infrastructure-containers`
in their `stack.yaml` files. This matches what is already working on pve-test.

---

## Acceptance criteria

- [ ] LXC VMID 120 (`portainer-stack`) running on pve-test at `192.168.1.20`
- [ ] Portainer UI accessible at `http://192.168.1.20:9000`
- [ ] Admin login works with `PORTAINER_ADMIN_PASSWORD` from `.env.pve-test`
- [ ] Local Docker environment shows as an endpoint (`unix:///var/run/docker.sock`)
- [ ] `TF_VAR_portainer_server_ip=192.168.1.20` added to `.env.pve-test`
- [ ] ci-runner-01 endpoint visible in pve-test Portainer (re-registered)
- [ ] netbox-stack-test endpoint visible in pve-test Portainer (re-registered)
- [ ] Subsequent `terragrunt apply` on pve-test registers new LXC agents at `192.168.1.20`
- [ ] Production Portainer at `192.168.1.4:9000` **not** required for any pve-test operation

---

## Commit

```bash
cd /home/steve/git/proxmox-homelab
git checkout -b feat/pve-test-portainer dev/pve-test

git add terraform/lxc/stacks/portainer-stack/
git add terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml
git add .env.pve-test .env.template

git commit -m "feat(pve-test): deploy standalone Portainer server at 192.168.1.20

- portainer-stack LXC (VMID 120) on pve-test
- deploy-portainer-stack.yml playbook with idempotent admin init
- TF_VAR_portainer_server_ip=192.168.1.20 in .env.pve-test
- pve-test no longer depends on production Portainer at 192.168.1.4"

git push origin feat/pve-test-portainer
git checkout dev/pve-test
git merge feat/pve-test-portainer
git push origin dev/pve-test
```
