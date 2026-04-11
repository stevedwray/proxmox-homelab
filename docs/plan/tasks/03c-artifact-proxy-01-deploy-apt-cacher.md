# 03c-artifact-proxy-01 — Deploy apt-cacher-ng LXC stack

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/100

## Phase

Phase 03c — Artifact Proxy (apt-cacher-ng + Terraform provider mirror)

## Prerequisites

- Phase 00 complete — repo is clean
- At least one LXC already provisioned by the base pattern (e.g., `harbor-stack`) as a reference
- Terraform/Terragrunt installed on workstation
- `192.168.1.35` unallocated (verify in NetBox before assigning)

## Objective

The `apt-cacher-ng` LXC (VMID 142) is running at `192.168.1.35:3142`, `curl http://192.168.1.35:3142/acng-report.html` returns the stats page, and the service is registered in NetBox.

## Scope

- Create `terraform/lxc/stacks/apt-cacher-stack/stack.yaml`
- Create `terraform/lxc/stacks/apt-cacher-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml`
- Add `01proxy` apt config task (`Acquire::http::Proxy`) to the base LXC Ansible role or common tasks
- Apply via Terragrunt and run the playbook

## Out of Scope

- Configuring the Terraform provider mirror (task 03c-02)
- Updating Python pip caching in CI (task 03c-03)
- Re-running playbooks against existing LXCs (task 03c-03)

## Inputs

- `terraform/lxc/stacks/harbor-stack/stack.yaml` — reference for field format
- `terraform/lxc/stacks/harbor-stack/terragrunt.hcl` — copy verbatim
- `docs/plan/phase-03c-artifact-proxy.md` — Part A for stack spec and playbook content
- `.env` and `.env.pve-test`

## Expected Outputs

- `terraform/lxc/stacks/apt-cacher-stack/stack.yaml` (new)
- `terraform/lxc/stacks/apt-cacher-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml` (new)
- Base LXC role updated with `01proxy` apt config task

## Constraints and Conventions

- `portainer_agent: false` — apt-cacher-ng has no Docker
- `vmid: 142`, `ip_address: "192.168.1.35/24"`, `memory: 256`, `cores: 1`
- `docker_storage_size: "20G"` — reused as cache volume (or add dedicated data volume if module requires Docker storage)
- `rootfs_storage: infrastructure-containers`
- Apt proxy config line: `Acquire::http::Proxy "http://192.168.1.35:3142";` in `/etc/apt/apt.conf.d/01proxy`
- The `01proxy` task goes in the base LXC role so ALL new LXCs get it automatically
- `PassThroughPattern: .*` must be set in `acng.conf` to allow HTTPS passthrough (not all apt repos support HTTP)
- `ansible-lint` must pass at 0 violations after adding the playbook

## Acceptance Criteria

- [ ] `terraform/lxc/stacks/apt-cacher-stack/stack.yaml` exists with correct VMID, IP, hostname
- [ ] `terraform/lxc/stacks/apt-cacher-stack/terragrunt.hcl` exists
- [ ] `terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml` exists and passes ansible-lint
- [ ] VMID 142 running on pve-test at `192.168.1.35`
- [ ] `curl http://192.168.1.35:3142/acng-report.html` returns stats page (HTTP 200)
- [ ] `apt-cacher-ng` systemd service is active inside the LXC
- [ ] `/etc/apt/apt.conf.d/01proxy` present in newly built LXCs

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Create and deploy an apt-cacher-ng transparent apt proxy as an LXC on pve-test,
and add the apt proxy configuration to the base LXC Ansible role.

BEFORE WRITING FILES, READ:
  terraform/lxc/stacks/harbor-stack/stack.yaml         (format reference)
  terraform/lxc/stacks/harbor-stack/terragrunt.hcl     (copy for apt-cacher-stack)
  terraform/lxc/ansible/roles/                         (find the base LXC role)
  docs/plan/phase-03c-artifact-proxy.md                (Parts A1, A2, A3 — full spec)

BRANCH:
  git checkout -b feat/apt-cacher-terraform-mirror dev/pve-test

FILES TO CREATE:

1. terraform/lxc/stacks/apt-cacher-stack/stack.yaml:
   hostname: apt-cacher-stack
   ip_address: "192.168.1.35/24"
   gateway: "192.168.1.1"
   vmid: 142
   cores: 1
   memory: 256
   swap: 128
   rootfs_size: 8
   rootfs_storage: infrastructure-containers
   docker_storage_size: "20G"    # cache storage
   ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
   tags: [apt-cache, infrastructure, build]
   ansible_playbook: "deploy-apt-cacher-stack"
   portainer_agent: false

2. terraform/lxc/stacks/apt-cacher-stack/terragrunt.hcl:
   Copy harbor-stack/terragrunt.hcl verbatim.

3. terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml:
   - Install apt-cacher-ng via apt
   - Ensure service enabled and started
   - Set PassThroughPattern: .* in /etc/apt-cacher-ng/acng.conf (lineinfile)
   - Handler: Restart apt-cacher-ng on config change
   - Task to open port 3142 if UFW is active

4. Base LXC role (find the correct file in terraform/lxc/ansible/roles/):
   Add a task to write /etc/apt/apt.conf.d/01proxy:
     content: 'Acquire::http::Proxy "http://192.168.1.35:3142";\n'
   Use ansible.builtin.copy with owner root, group root, mode "0644"

DEPLOY:
  source .env && source .env.pve-test
  echo "Node: $TF_VAR_proxmox_node"   # must print: pve-test

  cd terraform/lxc/stacks/apt-cacher-stack
  terragrunt apply

  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "192.168.1.35," \
    terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml

VERIFY:
  curl http://192.168.1.35:3142/acng-report.html
  # Expected: HTML stats page

COMMIT:
  git add terraform/lxc/stacks/apt-cacher-stack/ \
          terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml \
          terraform/lxc/ansible/roles/
  git commit -m "feat(infra): deploy apt-cacher-ng proxy and add apt proxy config to base role"
  git push origin feat/apt-cacher-terraform-mirror

SECURITY SCAN (run after pushing feature branch — stop and present options if new issues are found):
  /home/steve/.local/bin/snyk iac test terraform/
  cd /home/steve/git/proxmox-homelab && source .env && sonar-scanner

DONE WHEN: Stats page accessible, ansible-lint passes, and security scan is clean.
Proceed to task 03c-02. The branch is merged to dev/pve-test in task 03c-03.
```
