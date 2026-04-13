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

## Live task docs

- [00b-pve-test-01 — Deploy Portainer bootstrap stack on bare-metal pve-test](tasks/00b-pve-test-01-deploy-portainer.md)

---

## IP / VMID allocation

| Service | IP | VMID | Node | Zone |
|---|---|---|---|---|
| Portainer server (pve-test) | `192.168.1.20` | 120 | pve-test | `infra` (vmbr0) |

Verify `192.168.1.20` is free before assigning:

```bash
source /home/steve/git/proxmox-homelab/.env && source .env.pve-test
curl -s -H "Authorization: Token ${NETBOX_SUPERUSER_API_TOKEN}" \
  "http://192.168.1.30:8080/api/ipam/ip-addresses/?address=192.168.1.20" | jq .count
# Expected: 0
```

Note: NetBox in this repository is accessed on port `8080`, not `80`.

---

## Part 0 — Wipe pve-test

Before deploying the new standalone stack, remove all existing containers from pve-test.
Starting clean eliminates VMID conflicts and ensures every subsequent stack registers with
the correct Portainer server from the first apply.

> **Safety guard — do not wipe pve (production)**
> `.env.pve-test` sets `TF_VAR_proxmox_node=pve-test` and `TF_WORKSPACE=pve-test`.
> Sourcing it **after** `.env` is what makes operations safe. Always verify below before
> running any destroy.

### Known containers on pve-test

| Stack | VMID | IP | Terraform state |
|---|---|---|---|
| ci-runner-01 | 141 | `10.57.0.63` | `stacks/ci-runner-01/terraform.tfstate.d/pve-test/` |
| netbox-stack-test | 142 | `192.168.1.31` | `stacks/netbox-stack-test/terraform.tfstate.d/pve-test/` |

### Safety check (mandatory — run before every destroy)

```bash
source /home/steve/git/proxmox-homelab/.env
source /home/steve/git/proxmox-homelab/.env.pve-test

# Stop immediately if either value is wrong:
echo "Node target  : $TF_VAR_proxmox_node"   # must print: pve-test
echo "TF workspace : $TF_WORKSPACE"           # must print: pve-test
```

### Destroy in reverse deploy order

```bash
cd /home/steve/git/proxmox-homelab
# env must be sourced — see safety check above

# Destroy netbox-stack-test (VMID 142):
cd terraform/lxc/stacks/netbox-stack-test
terragrunt destroy

# Destroy ci-runner-01 (VMID 141):
cd ../ci-runner-01
terragrunt destroy
```

Terragrunt runs `tofu init -reconfigure` automatically before each destroy (via the
`before_hook` in the root `terragrunt.hcl`), so no manual init step is needed.

### Verify pve-test is empty

```bash
# Should return an empty JSON array: []
ssh root@pve-test.gibbsgreatly.xyz \
  "pvesh get /nodes/pve-test/lxc --output-format json | jq '.[].vmid'"
```

If `pvesh` returns VMIDs not listed in the table above, they are not tracked in Terraform
state. Destroy them manually:

```bash
ssh root@pve-test.gibbsgreatly.xyz "pct stop <vmid> ; pct destroy <vmid>"
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

**File: `terraform/lxc/stacks/portainer-stack/terragrunt.hcl`**

Identical to every other stack's `terragrunt.hcl`:

```hcl
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "${get_repo_root()}/terraform/lxc//"
}

inputs = {
  stack_name      = basename(get_terragrunt_dir())
  stack_yaml_path = "${get_terragrunt_dir()}/stack.yaml"
}
```

---

## Part B — Ansible playbook

Create `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml` with the following
content:

> **Note on image source:** This stack is deployed before Harbor is configured (Phase 03b).
> It is one of **two permitted exceptions** to the Harbor-only pull rule (the other being
> Harbor itself). Pull `portainer-ce` directly from Docker Hub for this bootstrap. Once
> Phase 03b is complete, update the image reference to
> `10.57.3.10/dockerhub/portainer/portainer-ce:2.27.3` and redeploy.

```yaml
---
# Portainer CE server — bootstrap play for pve-test standalone management.
# Do NOT include portainer_agent or portainer_api roles — this IS the server.

- name: Install Docker base
  hosts: all
  become: true
  gather_facts: true
  roles:
    - docker_base

- name: Deploy Portainer CE server
  hosts: all
  become: true
  gather_facts: false

  vars:
    portainer_compose_dir: /opt/portainer
    portainer_version: "2.27.3"    # pin version — update deliberately, never use 'latest'

  tasks:
    - name: Create Portainer compose directory
      ansible.builtin.file:
        path: "{{ portainer_compose_dir }}"
        state: directory
        mode: "0750"

    - name: Write docker-compose.yml
      ansible.builtin.copy:
        dest: "{{ portainer_compose_dir }}/docker-compose.yml"
        mode: "0640"
        content: |
          services:
            portainer:
              image: portainer/portainer-ce:{{ portainer_version }}
              restart: unless-stopped
              ports:
                - "9000:9000"     # UI and HTTP API
                - "9443:9443"     # HTTPS UI (self-signed)
                - "8000:8000"     # Edge agent tunnel
              volumes:
                - /var/run/docker.sock:/var/run/docker.sock
                - /var/lib/portainer:/data

    - name: Pull Portainer image
      community.docker.docker_image:
        name: "portainer/portainer-ce:{{ portainer_version }}"
        source: pull

    - name: Start Portainer via compose
      community.docker.docker_compose_v2:
        project_src: "{{ portainer_compose_dir }}"
        state: present

- name: Initialise Portainer admin account
  hosts: all
  become: false
  gather_facts: false

  tasks:
    - name: Wait for Portainer API to become available
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}:9000/api/system/status"
        status_code: 200
      register: portainer_status
      until: portainer_status.status == 200
      retries: 30
      delay: 5

    - name: Initialise admin credentials (200 = created, 409 = already exists)
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}:9000/api/users/admin/init"
        method: POST
        body_format: json
        body:
          Username: "admin"
          Password: "{{ lookup('env', 'PORTAINER_ADMIN_PASSWORD') | mandatory('PORTAINER_ADMIN_PASSWORD env var is not set') }}"
        status_code: [200, 409]
      register: portainer_init_result
      no_log: true

    - name: Report init outcome
      ansible.builtin.debug:
        msg: >-
          {{ 'Portainer admin account initialised.' if portainer_init_result.status == 200
             else 'Portainer admin account already exists (idempotent).' }}
```

---

## Part C — Deploy

```bash
cd /home/steve/git/proxmox-homelab

# Source pve-test credentials (must be last to ensure pve-test wins):
source .env && source .env.pve-test

# Safety check — stop if either value is wrong:
echo "Node target  : $TF_VAR_proxmox_node"   # must print: pve-test
echo "TF workspace : $TF_WORKSPACE"           # must print: pve-test

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

## Part E — Redeploy order after wipe

Because pve-test was wiped in Part 0, there is nothing to re-register. All previously
running stacks will be deployed fresh in the following order. Each deploy will automatically
register its Portainer agent with the new server at `192.168.1.20` because
`TF_VAR_portainer_server_ip=192.168.1.20` is set in `.env.pve-test`.

| Order | Stack | Phase | VMID | Task |
|---|---|---|---|---|
| 1 | `portainer-stack` | 00b (this phase) | 120 | 00b-03 (already done above) |
| 2 | `ci-runner-01` | 00b (this phase) | 141 | 00b-05 — see below |
| 3 | `harbor-stack` | 03b | 121 | 03b-01 |
| 4 | `apt-cacher-ng` | 03c | 142 | 03c-01 |
| 5+ | Phase 04 stacks | 04 | 150+ | Authentik, Traefik, step-ca, Monitoring |

Do not skip steps or deploy out of order. Harbor (Step 3) must be running and configured
before Phase 04 stacks are deployed, since they pull images via Harbor.

### Step 2 — Redeploy ci-runner-01 (task 00b-05)

Destroying `ci-runner-01` in Part 0 also removed its `build_seg` SDN zone (`tvsegc`) and
VNet (`tvnetc`) from pve-test. This is expected — the destroy provisioner in
`null_resource.configure_network_sdn_attachment` runs `destroy-network-sdn-vnet.yml`,
which removes the zone once no containers reference it. Reapplying recreates everything
automatically via `configure-network-sdn-vnet.yml`.

The `deploy-ci-runner.yml` playbook auto-generates the runner registration token via
`gh api` — no manual token step needed, but `gh` must be authenticated on the workstation.

```bash
source /home/steve/git/proxmox-homelab/.env
source /home/steve/git/proxmox-homelab/.env.pve-test

# Three-way safety check — stop immediately if any value is wrong:
echo "Node target     : $TF_VAR_proxmox_node"       # must print: pve-test
echo "TF workspace    : $TF_WORKSPACE"               # must print: pve-test
echo "Portainer server: $TF_VAR_portainer_server_ip" # must print: 192.168.1.20

cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01
terragrunt apply

cd /home/steve/git/proxmox-homelab
ansible-playbook \
  -i terraform/lxc/stacks/ci-runner-01/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml
```

This apply is the first live proof of isolation: Terraform will register ci-runner-01 as a
Portainer agent at `192.168.1.20`, not `192.168.1.4`. No commit is needed — no files change.

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

**Wipe (Part 0)**
- [ ] `TF_VAR_proxmox_node=pve-test` and `TF_WORKSPACE=pve-test` confirmed before any destroy
- [ ] `netbox-stack-test` (VMID 142) destroyed via `terragrunt destroy`
- [ ] `ci-runner-01` (VMID 141) destroyed via `terragrunt destroy`
- [ ] `pvesh get /nodes/pve-test/lxc` returns an empty list

**Portainer deployment (Parts A–C)**
- [ ] LXC VMID 120 (`portainer-stack`) running on pve-test at `192.168.1.20`
- [ ] Portainer UI accessible at `http://192.168.1.20:9000`
- [ ] Admin login works with `PORTAINER_ADMIN_PASSWORD` from `.env.pve-test`
- [ ] Local Docker environment shows as an endpoint in Portainer

**Environment configuration (Part D)**
- [ ] `TF_VAR_portainer_server_ip=192.168.1.20` uncommented in `.env.pve-test`
- [ ] Subsequent `terragrunt apply` on pve-test registers new LXC agents at `192.168.1.20`
- [ ] Production Portainer at `192.168.1.4:9000` **not** required for any pve-test operation

**CI runner redeploy (Part E / task 00b-05)**
- [ ] `TF_VAR_portainer_server_ip` prints `192.168.1.20` before apply
- [ ] `terragrunt apply` exits 0 with VMID 141 running on pve-test at `10.57.0.63`
- [ ] `tvsegc` zone and `tvnetc` VNet visible in Proxmox SDN on pve-test
- [ ] ci-runner-01 registered as environment in Portainer at `192.168.1.20`
- [ ] GitHub Actions runner `ci-runner-pve-test` shows status `online`

---

## Commit

```bash
cd /home/steve/git/proxmox-homelab
git checkout -b feat/pve-test-portainer dev/pve-test

git add terraform/lxc/stacks/portainer-stack/stack.yaml
git add terraform/lxc/stacks/portainer-stack/terragrunt.hcl
git add terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml
git add .env.pve-test .env.template

git commit -m "feat(pve-test): deploy standalone Portainer server at 192.168.1.20

- portainer-stack LXC (VMID 120) on pve-test at 192.168.1.20
- stack.yaml and terragrunt.hcl for portainer-stack
- deploy-portainer-stack.yml: docker_base + compose deploy + admin init
- TF_VAR_portainer_server_ip=192.168.1.20 in .env.pve-test
- pve-test no longer depends on production Portainer at 192.168.1.4"

git push origin feat/pve-test-portainer
git checkout dev/pve-test
git merge feat/pve-test-portainer
git push origin dev/pve-test
```
