# terraform/README.md

# Terraform Modules for Proxmox Infrastructure

This directory contains reusable Terraform modules for deploying containerized infrastructure on Proxmox. The modules are designed to be composable and configurable, enabling rapid deployment of different application stacks.

## Module Architecture

```
terraform/
├── modules/                          # Reusable infrastructure modules
│   └── lxc-docker-host/             # LXC container with Docker support
├── management-stack/                 # Portainer deployment stack
├── media-stack/                     # Media services stack (future)
└── security-stack/                  # Security services stack (future)
```

## Available Modules

### lxc-docker-host

Creates a Proxmox LXC container optimized for running Docker containers.

**Purpose**: Provides a standardized, lightweight foundation for containerized applications with consistent networking, storage, and security configurations.

**Use Cases**:
- Application hosting containers
- Development environments
- Microservice deployments
- Container orchestration nodes

#### Module Inputs

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `target_node` | string | - | **Required** - Proxmox node for deployment |
| `hostname` | string | - | **Required** - Container hostname |
| `ip_address` | string | - | **Required** - Static IP with CIDR (e.g., "192.168.1.100/24") |
| `lxc_password` | string | - | **Required** - Root password (sensitive) |
| `ssh_public_keys` | string | - | **Required** - SSH public keys for access |
| `vmid` | number | `null` | Container ID (auto-assigned if null) |
| `ostemplate` | string | `"local:vztmpl/debian-docker-template.tar.gz"` | LXC OS template |
| `ostype` | string | `"debian"` | Operating system type |
| `unprivileged` | bool | `true` | Run as unprivileged container |
| `onboot` | bool | `true` | Start container on boot |
| `start` | bool | `true` | Start container after creation |
| `cores` | number | `2` | CPU core allocation |
| `memory` | number | `2048` | Memory allocation (MB) |
| `swap` | number | `512` | Swap allocation (MB) |
| `nesting` | bool | `true` | Enable container nesting for Docker |
| `rootfs_storage` | string | `"local-zfs"` | Storage backend |
| `rootfs_size` | string | `"8G"` | Root filesystem size |
| `network_bridge` | string | `"vmbr0"` | Network bridge |
| `gateway` | string | `"192.168.1.1"` | Network gateway |
| `tags` | string | `""` | Proxmox container tags |

#### Module Outputs

| Output | Description |
|--------|-------------|
| `ip_address` | IP address of created container |
| `hostname` | Container hostname |
| `container_id` | Proxmox container ID (VMID) |
| `target_node` | Deployment node |

#### Usage Example

```hcl
module "app_server" {
  source = "./modules/lxc-docker-host"
  
  # Required parameters
  target_node     = "pve-node-1"
  hostname        = "my-app-server"
  ip_address      = "192.168.1.100/24"
  lxc_password    = var.lxc_password
  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  
  # Optional customization
  vmid         = 200
  cores        = 4
  memory       = 4096
  rootfs_size  = "20G"
  tags         = "application,production"
}
```

#### Prerequisites

- Proxmox server with API access
- LXC template with Docker pre-installed
- Network bridge (`vmbr0`) configured
- Storage backend available (`local-zfs` or alternative)

#### Features

- **Docker Ready**: Pre-configured with Docker daemon and nesting support
- **Secure by Default**: Unprivileged containers with SSH key authentication
- **Network Configured**: Static IP assignment with gateway configuration
- **Flexible Storage**: Configurable storage backend and sizing
- **Auto-Start**: Containers start automatically on Proxmox boot

## Application Stacks

Application stacks use the modules to deploy complete solutions with associated services and configuration.

### management-stack

**Purpose**: Deploys Portainer Server for centralized Docker container management.

**Components**:
- LXC container (via `lxc-docker-host` module)
- Portainer Server with `--tlsskipverify`
- Dynamic Ansible inventory generation
- Automated service deployment

**Documentation**: See [management-stack/README.md](management-stack/README.md)

### Future Stacks (Planned)

#### media-stack
- Media server applications (Plex, Jellyfin, etc.)
- Download management (qBittorrent, Sonarr, Radarr)
- Reverse proxy configuration

#### security-stack
- Network monitoring (ntopng, Suricata)
- VPN services (WireGuard, OpenVPN)
- Security scanning tools

#### development-stack
- Git services (GitLab, Gitea)
- CI/CD pipelines
- Development databases

## Module Development Guidelines

### Creating New Modules

1. **Create module directory**:
   ```bash
   mkdir -p terraform/modules/my-new-module
   cd terraform/modules/my-new-module
   ```

2. **Required files**:
   ```
   main.tf          # Resource definitions
   variables.tf     # Input variables
   outputs.tf       # Output values
   README.md        # Module documentation
   ```

3. **Follow naming conventions**:
   - Use descriptive variable names
   - Include default values where sensible
   - Mark sensitive variables appropriately
   - Provide comprehensive descriptions

### Module Design Principles

- **Single Responsibility**: Each module should have one clear purpose
- **Composability**: Modules should work together seamlessly
- **Configurability**: Expose necessary parameters without over-engineering
- **Documentation**: Include usage examples and parameter descriptions
- **Validation**: Use variable validation where appropriate

### Variable Validation Example

```hcl
variable "memory" {
  description = "Memory allocation in MB"
  type        = number
  default     = 2048
  
  validation {
    condition     = var.memory >= 512 && var.memory <= 32768
    error_message = "Memory must be between 512MB and 32GB."
  }
}
```

## Stack Development Guidelines

### Creating New Stacks

1. **Create stack directory**:
   ```bash
   mkdir -p terraform/my-stack
   cd terraform/my-stack
   ```

2. **Required files**:
   ```
   main.tf          # Module usage and resources
   variables.tf     # Stack-specific variables
   terraform.tfvars # Default configuration
   README.md        # Stack documentation
   ```

3. **Optional Ansible integration**:
   ```
   ansible/
   ├── playbook.yml
   ├── inventory.tpl
   └── roles/
   ```

### Stack Design Principles

- **Self-Contained**: Each stack should be independently deployable
- **Environment Agnostic**: Support dev/staging/prod through variables
- **Service Integration**: Use Ansible or API calls for service deployment
- **Documentation**: Include deployment instructions and troubleshooting

## Common Patterns

### Multi-Container Applications

```hcl
# Database container
module "database" {
  source = "./modules/lxc-docker-host"
  
  hostname   = "app-database"
  ip_address = "192.168.1.10/24"
  memory     = 4096
  tags       = "database,backend"
  # ... other parameters
}

# Application container
module "application" {
  source = "./modules/lxc-docker-host"
  
  hostname   = "app-server"
  ip_address = "192.168.1.11/24"
  memory     = 2048
  tags       = "application,frontend"
  # ... other parameters
}

# Load balancer container
module "loadbalancer" {
  source = "./modules/lxc-docker-host"
  
  hostname   = "app-lb"
  ip_address = "192.168.1.12/24"
  memory     = 1024
  tags       = "loadbalancer,frontend"
  # ... other parameters
}
```

### Environment-Specific Configuration

```hcl
locals {
  environment_config = {
    dev = {
      cores  = 1
      memory = 1024
      size   = "10G"
    }
    prod = {
      cores  = 4
      memory = 8192
      size   = "50G"
    }
  }
  
  config = local.environment_config[var.environment]
}

module "app_server" {
  source = "./modules/lxc-docker-host"
  
  cores       = local.config.cores
  memory      = local.config.memory
  rootfs_size = local.config.size
  # ... other parameters
}
```

## Troubleshooting

### Common Module Issues

1. **Provider Version Conflicts**: Ensure all modules specify compatible provider versions
2. **Variable Type Mismatches**: Check variable types match between module calls and definitions
3. **Resource Naming Conflicts**: Use unique resource names across modules
4. **State Management**: Consider separate state files for different environments

### Debug Commands

```bash
# Validate module syntax
terraform validate

# Plan with detailed logging
TF_LOG=DEBUG terraform plan

# Show current state
terraform show

# List all resources
terraform state list
```

## Best Practices

- **Version Control**: Tag module releases for stability
- **Testing**: Test modules in isolation before stack integration  
- **Security**: Never commit sensitive values to version control
- **Documentation**: Keep README files up-to-date with changes
- **Validation**: Use `terraform validate` and `terraform plan` before applying

## Contributing

When adding new modules or stacks:

1. Follow the established directory structure
2. Include comprehensive documentation
3. Add usage examples
4. Test with multiple configurations
5. Update this README with new module information

### agent-stack

**Purpose**: Deploys Portainer Agents that connect to the management-stack server and can host application deployments.

**Components**:
- LXC container (via `lxc-docker-host` module)
- Portainer Agent with automatic server registration
- Application stack deployment via Portainer API
- Dynamic Ansible inventory generation

**Features**:
- **Automatic Registration**: Agent automatically registers with Portainer server via API
- **Application Deployment**: Deploys Docker Compose stacks through Portainer API
- **Centralized Management**: All containers managed through Portainer web interface
- **API-Driven**: Full deployment automation without manual Portainer UI interaction

**Documentation**: See [agent-stack/README.md](agent-stack/README.md)

## Shared Infrastructure Components

The architecture includes reusable Ansible roles for common functionality across all stacks:

### Shared Ansible Roles

Located in `ansible/shared-roles/`, these provide consistent functionality across different stacks:

#### docker_base
- **Purpose**: Base Docker configuration for all LXC containers
- **Functions**: Ensures Docker service is running, installs Python SDK, configures Docker group
- **Usage**: Applied to all container deployments as foundation layer

#### portainer_agent  
- **Purpose**: Deploys and configures Portainer Agent containers
- **Functions**: Creates agent compose file, manages systemd service, validates agent connectivity
- **Configuration**: Supports custom ports, domains, and FQDN settings

#### portainer_api
- **Purpose**: Registers agents with Portainer server via API calls
- **Functions**: Authenticates with server, registers new endpoints, handles TLS certificate issues
- **Features**: Automatic endpoint discovery, graceful error handling for existing agents

#### app_stack
- **Purpose**: Deploys Docker Compose applications via Portainer API
- **Functions**: Creates stacks through API, manages existing stack cleanup, supports environment variables
- **Benefits**: Centralized application management, stack versioning, rollback capabilities

### Architecture Flow

```
1. lxc-docker-host module creates container
2. docker_base role configures Docker environment  
3. portainer_agent role deploys agent container
4. portainer_api role registers agent with server
5. app_stack role deploys applications via API
```

### Shared Role Usage Pattern

Each stack follows a consistent pattern:

```yaml
---
- name: Apply base Docker configuration
  hosts: all
  roles:
    - ../../ansible/shared-roles/docker_base

- name: Configure Portainer Agent  
  hosts: target_hosts
  roles:
    - ../../ansible/shared-roles/portainer_agent

- name: Register with Portainer Server
  hosts: target_hosts  
  roles:
    - ../../ansible/shared-roles/portainer_api

- name: Deploy Application Stack
  hosts: target_hosts
  vars:
    app_stack_name: "my-application"  
    app_stack_compose_content: "{{ lookup('file', 'docker-compose.yml') }}"
  roles:
    - ../../ansible/shared-roles/app_stack
```

### Benefits of Shared Architecture

- **Consistency**: Same base configuration across all deployments
- **Maintainability**: Updates to shared roles affect all stacks  
- **Reusability**: New stacks inherit proven functionality
- **API-First**: All management through Portainer API enables full automation
- **Centralized Control**: Single Portainer interface manages entire infrastructure
