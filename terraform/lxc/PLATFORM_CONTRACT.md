# Platform Contract — terraform/lxc

## What this module owns

The platform layer provisions and configures LXC containers on Proxmox. It is
responsible for:

- **Container lifecycle**: create, start, resize, destroy via the `bpg/proxmox`
  Terraform provider
- **Ansible inventory generation**: produces `inventory.yml` in each stack directory
  from `templates/inventory.tpl`, pre-populated with host vars that playbooks consume
- **Network attachment**: connects each container to the correct SDN VNet or bridge,
  as declared in `network/<env>.yaml`
- **Firewall intent**: generates per-VNet firewall rules from `network/<env>.yaml`
  policies (note: firewall is currently disabled for dev passes; see `pve-test.yaml`)
- **Shared Ansible roles**: `lxc_base`, `docker_base`, `portainer_agent`,
  `portainer_api`, `app_stack`, `harbor_installer`, `harbor_postconfigure`,
  `lxc_tun_device` — logic that applies to 2+ stacks lives here

## What it may read from elsewhere

- `stacks/<stack>/stack.yaml` — stack identity, resource sizing, network zone,
  playbook name, feature flags (`portainer_agent`, `keyctl`)
- `network/<env>.yaml` — zone topology, attachment config, cross-zone policies
- Environment variables and `TF_VAR_*` set by sourcing `.env` or `.env.pve-test`

## What may depend on this module

All stacks. Each stack's `terragrunt.hcl` sources this module via
`terraform { source = "${get_repo_root()}/terraform/lxc//" }`.

## Platform-level variables

These are declared in `variables.tf` and may be overridden per environment:

| Variable                | Default        | pve-test value  | Notes |
|-------------------------|----------------|-----------------|-------|
| `portainer_server_ip`   | `192.168.1.4`  | `10.57.1.20`    | Portainer server for agent registration |
| `registry_host`         | `192.168.1.10` | `10.57.3.10`    | Harbor IP for Docker pulls |
| `apt_cacher_host`       | `192.168.1.35` | `10.57.3.11`    | apt-cacher-ng proxy |

**Note:** `registry_host` and `apt_cacher_host` are planned additions — see
[Code Change Plan](#pending-code-changes) below. Currently they are hardcoded in
`lxc_base/tasks/main.yml` and `deploy-authentik-stack.yml`.

The pve-test values are set via `TF_VAR_*` in `.env.pve-test`. They flow through
`templates/inventory.tpl` as host vars so playbooks pick them up automatically.

## Platform API — `stack.yaml` fields

These are the fields the platform reads from each stack's `stack.yaml`. Treat any
change to field names or semantics as a platform API change affecting all stacks.

| Field                | Type    | Required | Notes |
|----------------------|---------|----------|-------|
| `hostname`           | string  | yes      | LXC hostname |
| `ip_address`         | string  | yes      | CIDR notation (e.g. `10.57.3.10/24`) |
| `gateway`            | string  | yes      | Default gateway IP |
| `vmid`               | int     | yes      | Proxmox VMID (must be unique) |
| `cores`              | int     | yes      | vCPU count |
| `memory`             | int     | yes      | Memory in MiB |
| `swap`               | int     | no       | Swap in MiB |
| `rootfs_size`        | int     | yes      | Root disk in GiB |
| `rootfs_storage`     | string  | yes      | Proxmox storage pool |
| `docker_storage_size`| string  | no       | Additional Docker data volume |
| `ostemplate`         | string  | yes      | Proxmox template reference |
| `tags`               | list    | no       | Informational |
| `network.zone`       | string  | yes      | Zone key from `network/<env>.yaml` |
| `ansible_playbook`   | string  | no       | Playbook to run after provisioning |
| `portainer_agent`    | bool    | no       | If true, deploy and register agent |
| `keyctl`             | bool    | no       | If true, enable keyctl in container |
| `app_stack_name`     | string  | no       | Portainer stack name override |
| `extra_mount_path`   | string  | no       | Path for extra storage mount |
| `extra_mount_size`   | string  | no       | Size of extra mount |
| `extra_mount_storage`| string  | no       | Storage pool for extra mount |
| `depends_on`         | list    | planned  | Declared upstream service deps |
| `provides`           | list    | planned  | Services this stack exposes |

## What must not be edited casually

- `templates/inventory.tpl` — changes affect every stack's generated inventory.
  Adding a field is safe; renaming or removing one will break playbooks that
  reference the old name.
- `modules/lxc-docker-host/` — the LXC container module. Changes to `onboot` or
  `start` defaults will affect all stacks on next `apply`.
- Role names under `ansible/roles/` — these are referenced by string in playbooks.
  Renaming a role requires updating every playbook that uses it.
- `variables.tf` — removing a variable with an existing default is a breaking change
  for any stack that relies on that default.

## Pending code changes

### 1. Parameterize `registry_host` and `apt_cacher_host`

**Files to change:**

`terraform/lxc/variables.tf` — add:
```hcl
variable "registry_host" {
  description = "Harbor registry IP for Docker image pulls"
  type        = string
  default     = "192.168.1.10"
}

variable "apt_cacher_host" {
  description = "IP of apt-cacher-ng proxy. Empty string disables proxy config."
  type        = string
  default     = "192.168.1.35"
}
```

`terraform/lxc/templates/inventory.tpl` — add after `portainer_server_ip`:
```
          registry_host: ${registry_host}
          apt_cacher_host: ${apt_cacher_host}
```

`terraform/lxc/main.tf` — in the `templatefile()` call, add:
```hcl
registry_host   = try(local.stack.registry_host, var.registry_host)
apt_cacher_host = try(local.stack.apt_cacher_host, var.apt_cacher_host)
```

`.env.pve-test` — add (if not already present):
```
export TF_VAR_registry_host=10.57.3.10
export TF_VAR_apt_cacher_host=10.57.3.11
```

### 2. Parameterize apt proxy in `lxc_base`

`terraform/lxc/ansible/roles/lxc_base/tasks/main.yml` — replace the hardcoded task:
```yaml
# Before:
- name: Configure apt to use apt-cacher-ng proxy
  ansible.builtin.copy:
    dest: /etc/apt/apt.conf.d/01proxy
    content: |
      Acquire::http::Proxy "http://192.168.1.35:3142";

# After:
- name: Configure apt to use apt-cacher-ng proxy
  ansible.builtin.copy:
    dest: /etc/apt/apt.conf.d/01proxy
    content: |
      Acquire::http::Proxy "http://{{ apt_cacher_host }}:3142";
    owner: root
    group: root
    mode: "0644"
  when: apt_cacher_host | default('') | length > 0
```

### 3. Fix hardcoded registry host in authentik

See `stacks/authentik-stack/STACK_CONTRACT.md` — Pending Code Changes section.
