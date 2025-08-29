# Proxmox Ansible Playbooks

This repository contains Ansible playbooks for automating Proxmox VE 9 setup and LXC template creation.

## Overview

The playbooks provide:
1. **Base Proxmox Configuration** - Post-installation setup for Proxmox VE 9
2. **Debian LXC Template Builder** - Creates customized Debian-based LXC templates
3. **Alpine LXC Template Builder** - Creates lightweight Alpine-based LXC templates

## Quick Start

### Prerequisites

- Proxmox VE 9 (Debian 13/Trixie) freshly installed
- Ansible control machine with SSH key pair generated
- Network connectivity between Ansible control machine and Proxmox host

### Basic Usage

1. **Configure Proxmox base system:**
   ```bash
   ansible-playbook -i inventory proxmox-initial-setup.yml
   ```

2. **Build Debian template:**
   ```bash
   ansible-playbook -i inventory build-debian-template.yml
   ```

3. **Build Alpine template:**
   ```bash
   ansible-playbook -i inventory build-alpine-template.yml
   ```

## Inventory Configuration

Create an Ansible inventory file with your Proxmox hosts:

```ini
[proxmox]
proxmox-host ansible_host=192.168.1.100 ansible_user=root

[debian_template_builder]
192.168.1.50 ansible_user=automation

[alpine_template_builder]
192.168.1.52 ansible_user=automation
```

## Playbook Details

### 1. Proxmox Initial Setup (`proxmox-initial-setup.yml`)

Configures a fresh Proxmox VE 9 installation with production-ready settings.

#### Features
- Switches to no-subscription repositories (deb822 format)
- Removes/disables enterprise repositories
- Optionally configures Ceph no-subscription repository
- Disables subscription nag popup in Web UI
- Sets up IPv6 host tuning for SLAAC
- Creates Terraform automation user with API token
- Performs idempotent repository verification

#### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `pmx_enable_ceph_repo` | `true` | Enable Ceph no-subscription repository |
| `pmx_disable_subscription_nag` | `true` | Disable subscription popup |
| `pmx_ipv6_tune` | `true` | Apply IPv6 SLAAC tuning |
| `pmx_ipv6_use_tempaddr` | `0` | IPv6 temporary address preference |
| `pmx_ipv6_accept_ra` | `2` | Accept router advertisements |
| `pmx_ipv6_autoconf` | `1` | Enable SLAAC autoconfig |
| `pmx_manage_network` | `false` | Write /etc/network/interfaces |
| `pmx_setup_terraform_user` | `true` | Create Terraform automation user |
| `pmx_terraform_user` | `automation@pve` | Terraform user name |
| `pmx_terraform_token_id` | `terraform` | API token identifier |
| `pmx_terraform_rotate_token` | `true` | Always create fresh token |

#### Network Configuration (Optional)
When `pmx_manage_network: true`, configure these variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `pmx_primary_iface` | Auto-detected | Primary network interface |
| `pmx_ipv4_addr` | `192.168.1.10/24` | Static IPv4 address |
| `pmx_ipv4_gw` | `192.168.1.1` | IPv4 gateway |

### 2. Debian Template Builder (`build-debian-template.yml`)

Creates a customized Debian 12 LXC template with Docker and development tools.

#### Features
- Based on Debian 12 standard template
- Installs comprehensive development and network diagnostic tools
- Configures Docker CE with docker-compose
- Sets up Portainer Agent for container management
- Creates automation user with SSH key access
- Configures console auto-login
- Packages final template as gzipped archive

#### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `lxc_template_id` | `900` | Container ID for template building |
| `lxc_template_hostname` | `debian-template-builder` | Container hostname |
| `lxc_template_ip` | `192.168.1.50` | Container IP address |
| `lxc_template_memory` | `2048` | Memory allocation (MB) |
| `lxc_template_cores` | `2` | CPU cores |
| `lxc_template_disk` | `8` | Disk size (GB) |
| `lxc_storage_pool` | `local-zfs` | Proxmox storage pool |
| `lxc_network_bridge` | `vmbr0` | Network bridge |
| `lxc_gateway_ip` | `192.168.1.1` | Network gateway |
| `timezone` | `Pacific/Auckland` | System timezone |
| `install_docker` | `true` | Install Docker and related tools |

#### Packaging Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `lxc_clone_id` | `800` | Temporary clone ID for packaging |
| `lxc_dumpdir` | `/var/lib/vz/template/cache` | Template output directory |
| `lxc_final_template_filename` | `debian-docker-template.tar.gz` | Final template filename |
| `lxc_vzdump_mode` | `stop` | Dump mode (stop/suspend) |
| `lxc_vzdump_compress` | `gzip` | Compression method |

### 3. Alpine Template Builder (`build-alpine-template.yml`)

Creates a lightweight Alpine Linux LXC template optimized for minimal resource usage.

#### Features
- Based on Alpine 3.22 template
- Minimal package installation for reduced footprint
- Docker support with OpenRC service management
- Portainer Agent with Alpine-specific init scripts
- Uses ash shell by default (bash also available)
- Optimized for container workloads

#### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `lxc_template_id` | `901` | Container ID for template building |
| `lxc_template_hostname` | `alpine-template-builder` | Container hostname |
| `lxc_template_ip` | `192.168.1.52` | Container IP address |
| `lxc_template_memory` | `1024` | Memory allocation (MB) |
| `lxc_template_cores` | `1` | CPU cores |
| `lxc_template_disk` | `4` | Disk size (GB) |
| `lxc_storage_pool` | `local-zfs` | Proxmox storage pool |
| `lxc_network_bridge` | `vmbr0` | Network bridge |
| `lxc_gateway_ip` | `192.168.1.1` | Network gateway |
| `install_docker` | `true` | Install Docker and related tools |

#### Packaging Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `lxc_clone_id` | `801` | Temporary clone ID for packaging |
| `lxc_dumpdir` | `/var/lib/vz/template/cache` | Template output directory |
| `lxc_final_template_filename` | `alpine-docker-template.tar.gz` | Final template filename |

## Advanced Configuration

### Custom Variable Files

Create variable files for different environments:

```yaml
# vars/production.yml
pmx_ipv4_addr: "10.0.1.10/24"
pmx_ipv4_gw: "10.0.1.1"
lxc_storage_pool: "production-zfs"
lxc_network_bridge: "vmbr1"
```

Use with: `ansible-playbook -e @vars/production.yml playbook.yml`

### SSH Key Configuration

The playbooks expect your SSH public key at `~/.ssh/id_rsa.pub`. To use a different key:

```bash
# Override in command line
ansible-playbook -e "ansible_ssh_private_key_file=~/.ssh/proxmox_key" playbook.yml
```

## Using Created Templates

After successful template creation:

### Create containers from Debian template:
```bash
pct create 101 local:vztmpl/debian-docker-template.tar.gz \
  --hostname web-server-1 \
  --memory 2048 \
  --cores 2 \
  --rootfs local-zfs:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --start
```

### Create containers from Alpine template:
```bash
pct create 102 local:vztmpl/alpine-docker-template.tar.gz \
  --hostname alpine-app-1 \
  --memory 1024 \
  --cores 1 \
  --rootfs local-zfs:4 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --start
```

## Hardcoded Values That Should Be Configurable

The following hardcoded values should be made configurable through variables:

### Base Template References
- **Debian template**: `debian-12-standard_12.7-1_amd64.tar.zst` (should be `lxc_debian_base_template`)
- **Alpine template**: `alpine-3.22-default_20250617_amd64.tar.xz` (should be `lxc_alpine_base_template`)

### Network Configuration
- **SSH public key path**: `~/.ssh/id_rsa.pub` (should be `ansible_ssh_public_key_file`)
- **Known hosts cleanup**: Uses hardcoded `~/.ssh/known_hosts` path

### Service Versions
- **Portainer Agent version**: `2.21.1` (should be `portainer_agent_version`)
- **Docker Compose URL**: Uses "latest" but could specify version

### System Paths
- **Sudoers directory**: `/etc/sudoers.d/` (generally standard, but could be configurable)
- **SSH config path**: `/etc/ssh/sshd_config` (standard, but override might be useful)

### Repository Configuration
- **Debian suite**: Uses `ansible_distribution_release` but could allow override
- **Package repository URLs**: Hardcoded to official repositories

### Docker Configuration
- **Docker repository**: Uses official Docker repository, no alternative options
- **Docker Compose installation method**: Hardcoded to GitHub releases

## Error Handling

The playbooks include comprehensive error handling:
- Idempotent operations (safe to run multiple times)
- Verification steps to ensure proper configuration
- Cleanup of temporary resources
- Detailed debug output for troubleshooting

## Troubleshooting

### Common Issues

1. **SSH Connection Failures**: Ensure SSH keys are properly configured and the automation user exists
2. **Template Download Failures**: Check internet connectivity and Proxmox template availability
3. **Storage Issues**: Verify specified storage pools exist and have sufficient space
4. **Network Configuration**: Ensure IP addresses don't conflict with existing infrastructure

### Debug Mode

Run with verbose output for troubleshooting:
```bash
ansible-playbook -vvv playbook.yml
```

### Container Access

Access created containers directly:
```bash
# Via Proxmox container terminal
pct enter <container_id>

# Via SSH (after container creation)
ssh automation@<container_ip>
```

## Security Considerations

- The automation user has NOPASSWD sudo access - restrict as needed for your environment
- SSH keys are used for authentication - ensure proper key management
- Terraform API tokens have Administrator privileges - consider role-based restrictions
- Docker daemon access grants significant system privileges

## Contributing

When modifying these playbooks:
1. Test on non-production Proxmox instances
2. Ensure idempotency is maintained
3. Add appropriate error handling
4. Update documentation for new variables
5. Consider backward compatibility
