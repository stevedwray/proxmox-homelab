# 00b-pve-test-02 — Create portainer-stack Terraform and Ansible files

## Status

PENDING

## Phase

Phase 00b — pve-test Management Bootstrap

## Prerequisites

- Task 00b-01 complete: pve-test is wiped and empty
- Read `terraform/lxc/stacks/harbor-stack/stack.yaml` as a reference for the stack.yaml format
- Read `terraform/lxc/stacks/harbor-stack/terragrunt.hcl` as a reference for the terragrunt.hcl pattern
- Read `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml` as a reference for playbook structure
- Read `terraform/lxc/ansible/roles/docker_base/` to understand the base Docker role

## Objective

Three files exist — `terraform/lxc/stacks/portainer-stack/stack.yaml`, `terraform/lxc/stacks/portainer-stack/terragrunt.hcl`, and `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml` — that define a Portainer CE server LXC on pve-test at `192.168.1.20` (VMID 120).

## Scope

- `terraform/lxc/stacks/portainer-stack/stack.yaml` — LXC spec
- `terraform/lxc/stacks/portainer-stack/terragrunt.hcl` — standard Terragrunt include
- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml` — four plays: Docker base, compose deploy, Portainer init, env registation

## Out of Scope

- Running Terraform or Ansible (that is task 00b-03)
- Modifying `.env` or `.env.pve-test` (that is task 00b-04)
- Any changes to existing stacks
- Harbor image references (this stack bootstraps before Harbor exists — Docker Hub pull is the permitted exception)

## Inputs

- `terraform/lxc/stacks/harbor-stack/stack.yaml` — reference for field names and format
- `terraform/lxc/stacks/harbor-stack/terragrunt.hcl` — reference (copy verbatim, no changes)
- `docs/plan/phase-00b-pve-test-management.md` — authoritative spec (Parts A and B)
- `terraform/lxc/ansible/roles/docker_base/` — role applied in play 1 of the playbook

## Expected Outputs

- `terraform/lxc/stacks/portainer-stack/stack.yaml` (new)
- `terraform/lxc/stacks/portainer-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml` (new)
- `.env.template` — add `PORTAINER_ADMIN_PASSWORD` placeholder if not already present

## Constraints and Conventions

- `portainer_agent: false` — this IS the Portainer server, not a client
- Image must be `portainer/portainer-ce:2.27.3` from Docker Hub (not Harbor — Harbor doesn't exist yet). This is one of two permitted pre-Harbor bootstrap exceptions.
- Pin Portainer version explicitly. Never use `latest`.
- `hostname: portainer-stack`, `vmid: 120`, `ip_address: "192.168.1.20/24"`, `gateway: "192.168.1.1"`
- `rootfs_storage: infrastructure-containers` (matches pve-test storage pool in use)
- `memory: 512`, `cores: 1`, `docker_storage_size: "10G"`
- `terragrunt.hcl` is identical to every other stack — copy it, do not invent new fields
- Admin password for Portainer must come from `PORTAINER_ADMIN_PASSWORD` environment variable — never hardcoded
- Ansible `no_log: true` on any task that handles the admin password or tokens
- The playbook must be idempotent: re-running it must not fail if Portainer is already initialised (409 on init endpoint is acceptable)
- **LAN ingress**: Portainer UI (port 9000) and HTTPS (port 9443) must be reachable from workstations on the LAN, not just from within pve-test. The Docker port bindings in compose must publish to `0.0.0.0` (the Docker default), not `127.0.0.1`. Verify accessibility from a LAN client after deployment (task 00b-03).

## Acceptance Criteria

- [ ] `terraform/lxc/stacks/portainer-stack/stack.yaml` exists with correct VMID, IP, memory, hostname, and `portainer_agent: false`
- [ ] `terraform/lxc/stacks/portainer-stack/terragrunt.hcl` exists and matches the standard pattern
- [ ] `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml` exists with docker_base role, compose deploy tasks, and admin init task
- [ ] Portainer version is pinned (not `latest`) in the playbook
- [ ] `PORTAINER_ADMIN_PASSWORD` sourced from env (not hardcoded)
- [ ] `no_log: true` on password-handling tasks
- [ ] `ansible-lint terraform/lxc/ansible/` passes at 0 violations
- [ ] `.env.template` has `PORTAINER_ADMIN_PASSWORD` placeholder

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Create three new files defining a Portainer CE management server LXC for pve-test.
This is a file-creation task only — do not run Terraform or Ansible yet.

BEFORE WRITING ANY FILES, READ THESE for context:
- terraform/lxc/stacks/harbor-stack/stack.yaml       (stack.yaml format reference)
- terraform/lxc/stacks/harbor-stack/terragrunt.hcl   (copy this file verbatim for portainer-stack)
- docs/plan/phase-00b-pve-test-management.md          (authoritative spec for this task — Parts A and B)
- terraform/lxc/ansible/roles/docker_base/tasks/main.yml  (to understand what docker_base does)

SPEC SUMMARY (from phase-00b doc):
- Stack: portainer-stack
- VMID: 120, IP: 192.168.1.20/24, Gateway: 192.168.1.1
- Cores: 1, Memory: 512 MB, Swap: 256 MB, rootfs: 8 GB
- rootfs_storage: infrastructure-containers, docker_storage_size: "10G"
- ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
- tags: [portainer, management, infrastructure, docker]
- portainer_agent: false  ← this IS the server, NOT an agent
- ansible_playbook: "deploy-portainer-stack"

FILES TO CREATE:
1. terraform/lxc/stacks/portainer-stack/stack.yaml
2. terraform/lxc/stacks/portainer-stack/terragrunt.hcl  (identical pattern to harbor-stack/terragrunt.hcl)
3. terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

PLAYBOOK REQUIREMENTS:
- Play 1: Apply role docker_base (installs Docker engine)
- Play 2: Deploy Portainer CE via docker-compose.yml at /opt/portainer/
  - Pin version: portainer/portainer-ce:2.27.3 (Docker Hub — Harbor does not exist yet;
    this is the permitted pre-Harbor bootstrap exception)
  - Ports: 9000 (HTTP API/UI), 9443 (HTTPS), 8000 (edge tunnel)
  - Volume: /var/lib/portainer:/data
  - Volume: /var/run/docker.sock:/var/run/docker.sock
- Play 3: Initialise Portainer admin account
  - Wait for API at http://{{ ansible_host }}:9000/api/system/status
  - POST to /api/users/admin/init with Username: admin, Password from PORTAINER_ADMIN_PASSWORD env var
  - Accept both 200 (created) and 409 (already exists) as success — makes it idempotent
  - no_log: true on the POST task

SECURITY RULES:
- Never hardcode the admin password — read it with: lookup('env', 'PORTAINER_ADMIN_PASSWORD')
- Use mandatory('PORTAINER_ADMIN_PASSWORD env var is not set') to fail fast if missing
- no_log: true on any task handling the password

ENV TEMPLATE:
- Add PORTAINER_ADMIN_PASSWORD to .env.template if not already present:
  PORTAINER_ADMIN_PASSWORD=   # __FROM_BITWARDEN__

DONE WHEN: All three files exist, ansible-lint passes at 0 violations (run:
  ansible-lint terraform/lxc/ansible/), and .env.template has PORTAINER_ADMIN_PASSWORD.

Then commit to a branch feat/pve-test-portainer off dev/pve-test.
```
