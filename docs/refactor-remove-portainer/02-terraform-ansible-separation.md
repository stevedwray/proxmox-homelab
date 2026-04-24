# Terraform / Ansible Separation Model

> Status note
>
> This document is background design context only. The active execution package
> for the refactor is `docs/refactor-remove-portainer/`.
>
> In particular, `README.md`, `decisions.md`, `task-sequence.md`, task docs,
> and `runbook.md` override this document when there is any conflict.
>
> Draft examples here that imply implicit `deployment_tier` defaults,
> Terraform-owned LXC configuration, or multiple LXC templates are superseded
> by the control docs and current implementation.

**Status:** Draft — not yet merged into proxmox-homelab

---

## Summary

Terraform and Ansible are run as two sequential, independent phases. Terraform owns
infrastructure (LXC exists, network attached, storage allocated). Ansible owns configuration
(everything inside the container). Neither phase invokes the other.

---

## Phase 1 — Infrastructure (Terraform / Terragrunt)

**Command:** `./with-secrets terragrunt run --all apply`
**Scope:** `terraform/lxc/stacks/<stack>/`
**Runs from:** operator workstation

### What Terraform is responsible for

- Creating and starting the LXC container on Proxmox
- Attaching the container to the correct SDN VNet / bridge
- Applying storage volumes (rootfs, Docker volume)
- Setting the container's IP address, gateway, DNS server
- Applying Proxmox-level firewall intent (where enabled)
- Generating `stacks/<stack>/inventory.yml` from `templates/inventory.tpl`
- Applying any Proxmox-host-level config that cannot be done inside the container
  (e.g. `keyctl` configuration via SSH to the Proxmox node)

### What Terraform is not responsible for

- Running Ansible
- Installing Docker
- Deploying any Docker stack or compose file
- Registering with Portainer
- Any configuration that happens inside the LXC

### Handoff artefact

After `terragrunt run --all apply`, each stack directory contains a generated
`inventory.yml` that Ansible consumes in Phase 2. This file is the only handoff
between the two phases. It contains:

- `ansible_host` — the container's IP address
- `ansible_user` — SSH user (typically `root`)
- Host vars: `registry_host`, `apt_cacher_host`, `portainer_server_ip`,
  `network_zone`, `dns_server`, and any stack-specific vars

### Removed from Terraform

The following are **removed** from `main.tf`:

- All `null_resource` blocks with `local-exec` provisioners that call `ansible-playbook`
- The `wait-for-ssh` null_resource (SSH readiness check moves to Ansible)
- The `portainer-register` null_resource
- The `keyctl` null_resource provisioner (replaced by a dedicated Ansible task)

The `local_file.ansible_inventory` resource remains — Terraform still generates inventories,
it just no longer runs Ansible.

---

## Phase 2 — Configuration (Ansible)

**Command:** `./with-secrets ./scripts/provision.sh [--tier platform|apps|all] [--stack <name>]`
**Scope:** All stacks, or a filtered subset
**Runs from:** operator workstation

### What Ansible is responsible for

- Waiting for SSH to become available on each container
- Applying the `lxc_base` role (package mirrors, apt proxy, base packages)
- Applying the `docker_base` role (Docker engine, compose plugin, daemon config)
- Deploying the Docker stack for the container's service
  - **Tier 1:** via `direct_stack` role (SSH + `docker compose up -d`)
  - **Tier 2:** via `app_stack` role (Portainer API)
- Applying the `portainer_agent` role (Tier 2 only)
- Any post-deployment validation (health checks, DNS resolution tests)

### What Ansible is not responsible for

- Creating or destroying LXC containers
- Network attachment or IP assignment
- Proxmox API calls of any kind

### Playbook invocation

Each stack has an `ansible_playbook` field in `stack.yaml`. `provision.sh` reads the
generated inventories and runs the named playbook against each stack in dependency order.

```
provision.sh
├── reads stacks/<stack>/inventory.yml for each stack
├── resolves deployment order from stack.yaml `depends_on` fields
└── runs: ansible-playbook -i stacks/<stack>/inventory.yml \
           playbooks/<ansible_playbook>.yml
```

Stacks with no `ansible_playbook` set are skipped (provisioning is Terraform-only for
that container).

### Idempotency

Ansible is expected to be fully idempotent. Running `provision.sh` against a stack that is
already correctly configured must produce no changes. Both deployment paths enforce this:

- `direct_stack` role: checks running stack state via `docker compose ps` before applying;
  compares compose file SHA256 to detect content changes
- `app_stack` role: existing SHA256 comparison logic is unchanged

---

## Orchestration script — `scripts/provision.sh`

A new script at `scripts/provision.sh` orchestrates the Ansible phase. It replaces the
Terraform `local-exec` provisioners as the mechanism that triggers Ansible.

### Interface

```bash
# Provision all stacks (platform then apps)
./with-secrets ./scripts/provision.sh

# Provision only Tier 1 platform stacks
./with-secrets ./scripts/provision.sh --tier platform

# Provision only Tier 2 application stacks
./with-secrets ./scripts/provision.sh --tier apps

# Provision a single named stack
./with-secrets ./scripts/provision.sh --stack harbor-stack

# Dry run (ansible-playbook --check)
./with-secrets ./scripts/provision.sh --check
```

### Ordering

Platform stacks are always provisioned before application stacks. Within each tier, stacks
are provisioned in the order declared by their `depends_on` field in `stack.yaml`. Stacks
with no `depends_on` are provisioned in parallel.

### Full rebuild sequence

```bash
# 1. Provision infrastructure
./with-secrets terragrunt run --all apply

# 2. Configure platform tier
./with-secrets ./scripts/provision.sh --tier platform

# 3. Configure application tier (Phase 06 only)
./with-secrets ./scripts/provision.sh --tier apps
```

---

## Stack classification in `stack.yaml`

A new field `deployment_tier` is added to `stack.yaml`:

```yaml
deployment_tier: platform   # or: apps
```

| Value | Deployment method | Portainer agent |
|---|---|---|
| `platform` | `direct_stack` role (SSH + docker compose) | Not installed |
| `apps` | `app_stack` role (Portainer API) | Installed |

If `deployment_tier` is absent, `platform` is assumed. This is a safe default: it ensures
that any stack without an explicit classification does not accidentally receive a Portainer
agent.

---

## Template selection

The LXC OS template (`ostemplate` field in `stack.yaml`) does not change. The single
Debian 13 Docker template is used for both tiers. The difference is in how the template is
built:

- `install_portainer_agent: false` is passed at template build time for the Tier 1 template
- The existing default (`install_portainer_agent: true`) produces the Tier 2 template

Two pre-built templates are maintained on the Proxmox storage:

| Template name | Portainer agent | Used by |
|---|---|---|
| `debian-13-docker-platform.tar.gz` | No | Tier 1 stacks |
| `debian-13-docker-apps.tar.gz` | Yes | Tier 2 stacks |

The `ostemplate` field in each `stack.yaml` references the appropriate template explicitly.

---

## Migration from the current model

The current model (`local-exec` Ansible via Terraform) continues to work during the
transition. Stacks are migrated from the old model to the new model individually:

1. Remove `ansible_playbook` from `stack.yaml` (stops Terraform from running Ansible)
2. Add `deployment_tier` to `stack.yaml`
3. Add the stack to `provision.sh`'s inventory
4. Verify the playbook runs cleanly via `provision.sh --stack <name>`
5. Update the `ostemplate` reference to the correct tier template

All platform stacks are migrated before any application stack. The Portainer API path
(`app_stack` role) is unchanged for Tier 2 and is migrated only in terms of invocation
(from Terraform `local-exec` to `provision.sh`), not in the underlying Ansible logic.
