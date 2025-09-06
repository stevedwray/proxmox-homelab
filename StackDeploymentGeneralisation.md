# Stack Generalization Guide: From agent-stack to torrent-stack

## Overview

This document describes the systematic process of generalizing the proven `agent-stack` pattern to create new application stacks. The `torrent-stack` serves as the primary example, demonstrating both standard generalization techniques and specialized handling for applications requiring additional system-level configuration.

## Architecture Foundation

### Shared Infrastructure Components

The infrastructure uses a modular approach with reusable components:

**Terraform Modules:**
- `lxc-docker-host`: Creates Proxmox LXC containers optimized for Docker workloads
- Provides consistent networking, storage, and security configurations

**Shared Ansible Roles:**
- `docker_base`: Base Docker configuration with registry mirror support
- `portainer_agent`: Deploys and configures Portainer Agent containers
- `portainer_api`: Registers agents with Portainer server via API
- `app_stack`: Deploys Docker Compose stacks via Portainer API
- `lxc_tun_device`: Configures LXC containers for VPN device access (specialized role)

**Key Design Principles:**
- API-driven deployment through Portainer for centralized management
- Consistent variable passing and environment configuration
- Automatic cleanup on infrastructure destruction
- Modular, reusable components that can be extended

## agent-stack: The Foundation Pattern

### Core Components

**Infrastructure Definition:**
```hcl
# terraform/agent-stack/main.tf
module "portainer_agent" {
  source = "../modules/lxc-docker-host"
  # Standard LXC configuration
}

resource "local_file" "ansible_inventory" {
  # Dynamic inventory generation
}

resource "null_resource" "run_ansible" {
  # Ansible execution with environment variables
}
```

**Ansible Automation:**
```yaml
# terraform/agent-stack/ansible/playbook.yml
- hosts: portainer_agents
  roles:
    - ../../ansible/shared-roles/docker_base
    - ../../ansible/shared-roles/portainer_agent
    - ../../ansible/shared-roles/portainer_api
    - ../../ansible/shared-roles/app_stack
```

**Key Characteristics:**
- Deploys basic Portainer agent
- Simple nginx test application
- Standard Docker configuration
- No special system requirements

## Generalization Process: Creating torrent-stack

### Step 1: Directory Structure Replication

```bash
# Copy the proven foundation
cp -r terraform/agent-stack terraform/torrent-stack
cd terraform/torrent-stack
```

### Step 2: Configuration Customization

**File: `terraform.tfvars`**
```hcl
# Application-specific configuration
agent_hostname = "torrent-stack"
agent_ip_address = "192.168.1.72/24"  # Different IP from agent-stack
agent_memory = 4096                    # Increased for media services
agent_cores = 2
agent_rootfs_size = "50G"             # Larger storage for configurations
```

**File: `variables.tf`**
```hcl
# Update default values to reflect stack purpose
variable "agent_hostname" {
  description = "Hostname for the torrent stack container"
  default     = "torrent-stack"
}

variable "agent_memory" {
  description = "Memory allocation in MB for torrent stack"
  default     = 4096  # Increased default
}
```

### Step 3: Application-Specific Ansible Configuration

**File: `ansible/playbook.yml`**
```yaml
# Add directory creation for application data
- name: Create required directories for torrent stack
  hosts: portainer_agents
  tasks:
    - name: Create torrent application directories
      file:
        path: "{{ item }}"
        state: directory
        mode: '0755'
        owner: '1000'
        group: '1000'
      loop:
        - /config/torrents/gluetun
        - /config/torrents/qbittorrent
        # ... additional directories

# Replace simple nginx with complex compose stack
- name: Deploy Torrent Stack
  vars:
    app_stack_compose_content: |
      version: '3.8'
      services:
        gluetun:
          image: qmcgaw/gluetun
          cap_add:
            - NET_ADMIN
          devices:
            - /dev/net/tun
          # ... complete torrent stack definition
```

### Step 4: Specialized System Requirements

**Challenge Identified:** The gluetun VPN client requires `/dev/net/tun` device access, which standard LXC containers don't provide.

**Solution Implemented:** Created specialized shared role `lxc_tun_device`:

```yaml
# terraform/ansible/shared-roles/lxc_tun_device/tasks/main.yml
- name: Get container VMID via SSH command
  command: pct list
  delegate_to: "{{ proxmox_host }}"

- name: Configure /dev/net/tun in LXC config
  lineinfile:
    path: "/etc/pve/lxc/{{ container_vmid }}.conf"
    line: "{{ item }}"
  loop:
    - "lxc.cgroup2.devices.allow: c 10:200 rwm"
    - "lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file"
  delegate_to: "{{ proxmox_host }}"
```

**Integration into torrent-stack playbook:**
```yaml
- name: Configure LXC container for VPN access
  hosts: portainer_agents
  roles:
    - ../../ansible/shared-roles/lxc_tun_device
```

## Data Migration Pattern

### Migration Challenge

Existing production configurations needed to be transferred from legacy infrastructure to the new deployment without losing:
- Application settings and API keys
- Database configurations
- SSL certificates and authentication data
- Media library organization

### Migration Solution

**File: `ansible/migrate-torrent-data.yml`**

```yaml
# Systematic migration approach
vars_prompt:
  - name: source_host
  - name: source_base_path
  - name: confirm_migration

# Safety measures
pre_tasks:
  - name: Abort if not confirmed
  - name: Verify target deployment

# Migration process
tasks:
  - name: Stop applications (prevent corruption)
  - name: Create backup (rollback capability)
  - name: Transfer configurations
  - name: Restart applications
  - name: Verify functionality
```

**Key Migration Techniques:**

1. **Archive and Transfer:**
```yaml
- name: Create archive of each app config on source
  shell: |
    tar --exclude='*.lock' --exclude='logs/' -czf /tmp/{{ item }}-config.tar.gz {{ item }}/
  delegate_to: "{{ source_host }}"

- name: Fetch config archives from source to control machine
  fetch:
    src: "/tmp/{{ item }}-config.tar.gz"
    dest: "/tmp/torrent-migration-{{ item }}.tar.gz"
    flat: yes
  delegate_to: "{{ source_host }}"
```

2. **Safety and Verification:**
```yaml
- name: Create backup of current config data
  archive:
    path: "{{ target_base_path }}"
    dest: "/tmp/torrent-backup-{{ ansible_date_time.epoch }}.tar.gz"

- name: Verify services are accessible
  uri:
    url: "http://{{ ansible_host }}:{{ item.port }}"
    status_code: [200, 302, 401]
```

## Generalization Framework

### Standard Generalization Steps

1. **Copy Foundation:** Start with agent-stack as proven template
2. **Update Configuration:** Modify hostnames, IPs, resource allocations
3. **Customize Application:** Replace compose content with target applications
4. **Add Directories:** Create necessary data and configuration directories
5. **Test Deployment:** Verify infrastructure and basic functionality

### Specialized Requirement Handling

**When to Create New Shared Roles:**
- System-level configuration requirements (like `/dev/net/tun`)
- Hardware device access needs
- Special kernel modules or capabilities
- Network configuration requirements

**Shared Role Design Pattern:**
```yaml
# Role Structure
terraform/ansible/shared-roles/specialized_role/
├── defaults/main.yml     # Default variable values
├── tasks/main.yml        # Main execution logic
└── README.md            # Usage documentation

# Integration Pattern
- name: Apply specialized configuration
  hosts: target_hosts
  roles:
    - ../../ansible/shared-roles/specialized_role
```

### Variable Management Strategy

**Environment Variables (via Terraform):**
```hcl
environment = {
  PORTAINER_ADMIN_PASSWORD = var.lxc_password
  REGISTRY_MIRROR_IP       = var.registry_mirror_ip
  CONTAINER_VMID          = module.stack_host.container_id
  PROXMOX_HOST            = "pvetest.gibbsgreatly.xyz"
}
```

**Ansible Variable Passing:**
```yaml
vars:
  docker_registry_mirror: "{{ lookup('env', 'REGISTRY_MIRROR_IP') }}"
  app_stack_name: "{{ inventory_hostname }}"
  app_stack_compose_content: |
    # Application-specific compose content
```

## Registry Mirror Configuration

### Challenge
Ensuring all Docker images are cached in local registry for vulnerability scanning with Trivy.

### Solution
```json
{
  "registry-mirrors": ["http://{{ docker_registry_mirror }}:5000"],
  "insecure-registries": ["{{ docker_registry_mirror }}:5000"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
```

**Note:** Current registry setup only caches Docker Hub images. Multiple registries (lscr.io, ghcr.io) require either multiple registry containers or a more sophisticated registry solution like Harbor.

## Troubleshooting Common Issues

### LXC Container Missing Required Devices
**Symptom:** Docker containers fail with device access errors
**Solution:** Create specialized shared role for device configuration
**Pattern:** Use Proxmox host SSH access to modify LXC configuration

### Portainer Endpoint Conflicts
**Symptom:** "Name is not unique" errors during registration
**Solution:** Delete existing endpoints before re-registration
**Prevention:** Use unique stack names and proper cleanup procedures

### Ansible Variable Scope Issues
**Symptom:** Variables undefined in certain contexts
**Solution:** Use environment variables for cross-context data passing
**Pattern:** Terraform → environment → Ansible variable chain

### Docker Daemon Configuration Issues
**Symptom:** Registry mirror not working or Docker failing to start
**Solution:** Verify JSON syntax and port configuration
**Debug:** Check `docker info` output and daemon logs

## Best Practices for New Stacks

### Infrastructure Layer
1. **Always start with agent-stack copy** - don't build from scratch
2. **Use descriptive, unique hostnames** - avoid conflicts
3. **Allocate appropriate resources** - memory, CPU, storage based on application needs
4. **Plan IP address allocation** - avoid network conflicts

### Application Layer
1. **Use inventory_hostname for dynamic naming** - enables multiple deployments
2. **Include health checks** - verify deployment success
3. **Plan data persistence** - identify what needs to survive container restarts
4. **Document service URLs** - provide clear access information

### System Requirements
1. **Identify special needs early** - device access, capabilities, kernel modules
2. **Create reusable shared roles** - avoid duplicating specialized configuration
3. **Test with minimal examples** - verify system requirements before full deployment
4. **Document dependencies** - clear prerequisites and assumptions

### Migration Strategy
1. **Plan migration before deployment** - understand what data needs preservation
2. **Create migration playbooks** - systematic, repeatable process
3. **Include rollback procedures** - backup and recovery capabilities
4. **Test migration process** - verify in development environment first

## Future Stack Considerations

### Potential Application Stacks
- **Media Stack:** Plex, Jellyfin, media management
- **Security Stack:** Wazuh, Greenbone, network monitoring
- **Development Stack:** Gitea, CI/CD, development tools
- **Database Stack:** PostgreSQL, MySQL clusters with replication

### Common Requirements Likely to Need Shared Roles
- **SSL Certificate Management:** Let's Encrypt automation
- **Backup Integration:** Automated backup scheduling
- **Monitoring Agents:** Prometheus exporters, log shipping
- **Network Segmentation:** VLAN configuration, firewall rules

### Evolution Path
1. **Standardize successful patterns** - extract common elements into shared roles
2. **Improve automation** - reduce manual steps where possible
3. **Enhance monitoring** - better health checking and alerting
4. **Optimize resource usage** - right-size deployments based on actual usage

This generalization framework provides a systematic approach to creating new application stacks while leveraging proven infrastructure patterns and handling specialized requirements through modular, reusable components.
