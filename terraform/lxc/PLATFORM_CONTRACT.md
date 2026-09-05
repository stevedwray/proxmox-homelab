# Platform Contract — terraform/lxc

## What this module owns

The platform layer provisions and configures LXC containers on Proxmox. It is
responsible for:

- **Container lifecycle**: create, start, resize, destroy via the `bpg/proxmox`
  Terraform provider
- **Inventory handoff generation**: produces `inventory.yml` in each stack directory
  from `templates/inventory.tpl`, pre-populated with the host vars that the
  explicit Ansible phase consumes
- **Network attachment**: connects each container to the correct SDN VNet or bridge,
  as declared in `network/<env>.yaml`
- **Firewall intent**: generates per-VNet firewall rules from `network/<env>.yaml`
  policies (note: firewall is currently disabled for dev passes; see `pve-test.yaml`)
- **Host-level automation tied to provisioning**: applies Proxmox-side actions
  such as `configure_keyctl`, SDN attachment, and firewall updates that cannot
  be performed from inside the guest
- **Shared Ansible roles**: `lxc_base`, `docker_base`, `direct_stack`,
  `portainer_agent`, `portainer_api`, `app_stack`, `harbor_installer`,
  `harbor_postconfigure`, `lxc_tun_device` — logic that applies to 2+ stacks
  lives here
- **Platform validation**: shared validators such as `validate-network.sh`,
  `validate-network-matrix.sh`, and `validate-zone-dns.sh` that prove network and
  DNS contracts from generated stack inventories

Terraform does not perform a hidden second pass for LXC stack configuration.
The generated inventory is the handoff artifact to the explicit Ansible phase
run via `scripts/provision.sh`.

## What it may read from elsewhere

- `stacks/<stack>/stack.yaml` — stack identity, resource sizing,
  `deployment_tier`, network zone, playbook name, and feature flags
  (`portainer_agent`, `keyctl`)
- `network/<env>.yaml` — zone topology, attachment config, cross-zone policies
- Environment variables and `TF_VAR_*` set by sourcing `.env` or `.env.pve-test`

## What may depend on this module

All stacks. Each stack's `terragrunt.hcl` sources this module via
`terraform { source = "${get_repo_root()}/terraform/lxc//" }`.

## Authority

- Shared variable authority: `variables.tf`
- Generated host var authority: `templates/inventory.tpl`
- Stack field authority: `stacks/<stack>/stack.yaml`
- Platform behavior authority: `main.tf` plus shared Ansible roles/playbooks

## Platform-level variables

These are declared in `variables.tf` and may be overridden per environment:

| Variable                | Default        | pve-test value  | Notes |
|-------------------------|----------------|-----------------|-------|
| `registry_host`         | `192.168.1.10` | `192.168.40.10` | Harbor IP for Docker pulls |
| `apt_cacher_host`       | `192.168.1.35` | `192.168.40.11` | apt-cacher-ng proxy |
| `portainer_server_ip`   | `192.168.1.4`  | `${lab_ip_portainer}`    | Portainer server for app-tier endpoint registration |

`registry_host` and `apt_cacher_host` now flow through `variables.tf` →
`main.tf` → `templates/inventory.tpl` as generated host vars. Stacks can override
them in `stack.yaml` if a stack needs a non-default upstream.

**`registry_host` (this IP) is not what a stack's own deploy playbook
should use for `docker login`/image pulls.** Every existing playbook that
actually authenticates to Harbor (`deploy-graylog-stack.yml`,
`deploy-harbor-stack.yml`, `deploy-portainer-stack.yml`,
`deploy-netbox-stack.yml`, `deploy-greenbone-stack.yml`, and others) uses
a separate `LAB_FQDN_HARBOR` env var (`harbor.${LAB_DOMAIN}`) instead —
confirmed live 2026-08-17: `docker login` against the bare IP fails
(Harbor's token service redirects to HTTPS:443, which the raw IP has no
valid cert for and refuses), while the FQDN succeeds because it routes
through Traefik's real TLS termination. When writing a new playbook,
copy an existing one's `*_registry_host`/`LAB_FQDN_HARBOR` pattern
directly rather than reusing `registry_host`/`LAB_IP_HARBOR` for this
purpose, even though the naming makes them look interchangeable.

The pve-test values are set via `TF_VAR_*` in `.env.pve-test`. They flow through
`templates/inventory.tpl` as host vars so playbooks pick them up automatically.

`portainer_server_ip` follows the same generated-inventory pattern in active
paths. Tier 2 roles such as `portainer_api` and `app_stack` prefer the
generated `portainer_server_ip` host var and only fall back to the current
pve-test address when that host var is absent.

`dns_server` also flows through generated inventory. It is derived from the zone
gateway contract in `network/<env>.yaml`, injected into Proxmox container
initialization, and emitted alongside `network_zone` and `contract_dns_server` host
vars. `validate-zone-dns.sh` / `validate-zone-dns.yml` use those fields to verify
that SDN-attached LXCs have not drifted from their declared zone-local resolver.

## Platform API — `stack.yaml` fields

These are the fields the platform reads from each stack's `stack.yaml`. Treat any
change to field names or semantics as a platform API change affecting all stacks.

### Required now

| Field              | Type   | Notes |
|--------------------|--------|-------|
| `hostname`         | string | LXC hostname |
| `ip_address`       | string | CIDR notation (e.g. `192.168.40.10/24`) |
| `deployment_tier`  | string | Explicit orchestration tier: `platform` or `apps` |
| `dns_server`       | string | Guest resolver written into `/etc/resolv.conf`; set explicitly in every stack |

### Optional with platform defaults

| Field                 | Type    | Default behavior |
|-----------------------|---------|------------------|
| `gateway`             | string  | Falls back to `default_gateway` from `variables.tf` |
| `dns_server`          | string  | Explicit guest resolver; use the zone gateway for SDN-attached stacks |
| `vmid`                | int     | Passed through if set; omitted otherwise |
| `cores`               | int     | Defaults to `2` |
| `memory`              | int     | Defaults to `2048` MiB |
| `swap`                | int     | Defaults to `512` MiB |
| `rootfs_size`         | int     | Defaults to `8` GiB |
| `storage_profile`     | string  | Falls back to `storage/<env>.yaml` defaults and maps to concrete runtime backends |
| `docker_storage_size` | string  | Defaults to `"20G"` |
| `template_name`       | string  | Defaults to manifest template name and resolves into `<storage>:vztmpl/<name>` |
| `template_profile`    | string  | Falls back to `storage/<env>.yaml` defaults and maps to template storage |
| `tags`                | list    | Defaults to `[stack_name]` |
| `network.zone`        | string  | Optional; when omitted, the stack uses bridge defaults rather than network intent |
| `network.access_path` | string  | Optional; allowed values are `direct` and `proxyjump_compat`; defaults to `direct` for `sdn_vnet` attachments and `proxyjump_compat` for bridge/default path |
| `ansible_playbook`    | string  | Playbook name consumed by `scripts/provision.sh` during the explicit Ansible phase |
| `portainer_agent`     | bool    | Defaults to `false`; relevant for app-tier/legacy Portainer cleanup behavior only |
| `keyctl`              | bool    | Defaults to `false` |
| `app_stack_name`      | string  | Defaults to stack directory name |
| `extra_mount_path`    | string  | No extra mount when omitted |
| `extra_mount_size`    | string  | No extra mount when omitted |
| `extra_mount_profile` | string  | Falls back to `storage/<env>.yaml` defaults and maps to concrete extra mount storage |
| `depends_on`          | list    | Orchestration metadata used to document and order stack application in the explicit provisioning path |
| `provides`            | list    | Contract/validation metadata used by stack-boundary documentation tooling |

Storage policy authority lives in `terraform/lxc/storage/<proxmox-node>.yaml`.
The root module resolves storage/template intent from stack fields before
invoking `modules/lxc-docker-host`.

## Orchestration boundary

The active model is explicitly two-phase:

1. Terraform provisions the LXC and generates `stacks/<stack>/inventory.yml`.
2. `scripts/provision.sh` reads the generated inventory and runs the stack's
   `ansible_playbook` as a separate operator action.

The generated inventory is the Terraform-to-Ansible handoff artifact.

- Tier 1 `deployment_tier: platform` stacks do not use Portainer agents.
- Tier 1 playbooks deploy directly on-host, typically via the `direct_stack`
  role or stack-specific logic.
- Tier 2 `deployment_tier: apps` stacks continue to use `portainer_agent`,
  `portainer_api`, and `app_stack`.
- Docker Compose networking: bridge networking + explicit port publishing
  is the default for every stack. `network_mode: host` is a narrow,
  per-stack exception requiring its own documented decision (currently only
  `technitium-stack`, for its DHCP server-identifier requirement — see
  `docs/dhcp-refactor/decisions.md` Decision 5) — not a pattern to adopt
  elsewhere without the same level of justification.
- Tier 1 playbooks must actively mask `portainer-agent.service`.

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

## Implemented boundary wiring

### 1. Extend shared host vars through the platform layer

**Implemented in:**

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
export TF_VAR_registry_host=192.168.40.10
export TF_VAR_apt_cacher_host=192.168.40.11
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

Implemented by reading `registry_host` from generated inventory and writing
`REGISTRY_HOST` into the stack `.env` file for Docker Compose expansion.

## Implementation cross-links

For quick navigation between the contract and its implementation, reference the
following files in this repository:

- `terraform/lxc/main.tf` — the module entrypoint that binds `variables.tf` into
  the template rendering call (see the `templatefile()` invocation where
  inventory variables are composed).
- `terraform/lxc/templates/inventory.tpl` — the rendered inventory template; any
  field added/removed here is a breaking contract change for playbooks.
- `terraform/lxc/modules/lxc-docker-host/` — module implementing the LXC host
  provisioning primitives used by the platform layer.
- `terraform/lxc/PLATFORM_CONTRACT.md` — this document (contract source).
- `terraform/lxc/stacks/*/STACK_CONTRACT.md` — per-stack contracts the platform
  consumes (examples: `stacks/portainer-stack/STACK_CONTRACT.md`).
- `terraform/lxc/STACK_CONTRACT.template.md` — copy this when authoring a new
  stack's contract; it has every required section heading pre-filled with
  placeholders so `validate-stack-metadata.sh --check-contract-sections`
  passes by construction instead of by remembering which headings are
  required.

If you edit the contract semantics here, add or update the cross-link above to
point readers at the representative implementation example(s).

## Stage 4 Exemplar Scaffolding Hooks

### Exemplar Pair

- apt-cacher-stack
- harbor-stack

### Scaffolding Intent

- define a shared, minimal hook surface for day-1/day-2 contract handoff
- keep existing behavior stable while introducing explicit exemplar-owned hook points

### Required Stage 4 Outputs

- stack-level hook declarations for apt-cacher and harbor contracts
- clear contract language for generated handoff artifacts used by Terraform and Ansible
- a bounded checklist for Stage 5 validation evidence
