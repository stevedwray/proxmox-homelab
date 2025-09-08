# Proxmox Ansible Playbooks

This repository contains Ansible playbooks for automating Proxmox VE 9 setup and LXC template creation.

## Overview

The playbooks provide:
1. **Base Proxmox Configuration** - Post-installation setup for Proxmox VE 9
2. **Storage Setup** - Automated storage configuration with ZFS pools and hot storage
3. **Debian LXC Template Builder** - Creates customized Debian-based LXC templates
4. **Alpine LXC Template Builder** - Creates lightweight Alpine-based LXC templates

## Quick Start

### Prerequisites

- Proxmox VE 9 (Debian 13/Trixie) freshly installed
- Ansible control machine with SSH key pair generated
- Network connectivity between Ansible control machine and Proxmox host

### Basic Usage

1. **Configure Proxmox base system:**
   ```bash
   ansible-playbook -i inventory/test-lab.yml 01-base-system/proxmox-initial-setup.yml
   ```

2. **Configure storage layout:**
   ```bash
   ansible-playbook -i inventory/storage-test.yml 01-base-system/storage-setup.yml
   ```

3. **Build Debian template:**
   ```bash
   ansible-playbook -i inventory/test-lab.yml 01-base-system/build-debian-template.yml
   ```

4. **Build Alpine template:**
   ```bash
   ansible-playbook -i inventory/test-lab.yml 01-base-system/build-alpine-template.yml
   ```

## Inventory Configuration

Create an Ansible inventory file with your Proxmox hosts:

```ini
[proxmox]
proxmox-host ansible_host=192.168.1.100 ansible_user=root

[proxmox_testbed]
pvetest02.gibbsgreatly.xyz ansible_host=192.168.1.102 ansible_user=root

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

### 2. Storage Setup (`playbooks/base-system/storage-setup.yml`)

Configures ZFS pools, hot storage partitions, and temporary storage for Proxmox testbed environments.

#### Features
- Creates multiple ZFS pools for different workloads (security, gaming, monitoring)
- Sets up hot storage partition on boot device for fast access
- Configures temporary storage for backups and transfers
- Validates system state before making changes
- Automatically configures Proxmox storage entries
- Fully idempotent with comprehensive safety checks

#### Usage
```bash
ansible-playbook -i inventory playbooks/base-system/storage-setup.yml
```

#### Configuration
The playbook uses variables from:
- `group_vars/proxmox.yml` - General Proxmox configuration
- `group_vars/proxmox_testbed.yml` - Testbed-specific storage layout

#### Example Storage Configuration
```yaml
# Example storage device mapping
storage_devices:
  boot_device: "/dev/nvme0n1"      # 100GB+ boot device
  security_device: "/dev/sdb"     # ZFS pool for security apps
  gaming_device: "/dev/sdc"       # ZFS pool for game servers
  monitoring_device: "/dev/sdd"   # ZFS pool for monitoring stack
  temporary_device: "/dev/sde"    # Fast temporary storage

# Hot storage on boot device
hot_storage:
  enabled: true
  partition_number: 4
  mount_point: "/mnt/hot-storage"
  filesystem_label: "hot-storage"
  mount_options: "defaults,noatime"

# ZFS pool configuration
zfs_pools:
  security:
    device: "/dev/sdb"
    properties:
      ashift: "12"
      autotrim: "on"
      compression: "lz4"
      atime: "off"
  gaming:
    device: "/dev/sdc"
    properties:
      ashift: "12"
      autotrim: "on"
      compression: "lz4"
      atime: "off"
  monitoring:
    device: "/dev/sdd"
    properties:
      ashift: "12"
      autotrim: "on"
      compression: "lz4"
      atime: "off"
```

### 3. Debian Template Builder (`build-debian-template.yml`)

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

### 4. Alpine Template Builder (`build-alpine-template.yml`)

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

## Storage Setup Details

### How the Storage Playbook Works

The storage setup playbook (`playbooks/base-system/storage-setup.yml`) provides automated configuration of storage for Proxmox testbed environments. It's designed to be completely idempotent and safe to run multiple times.

#### Pre-flight Safety Checks

Before making any changes, the playbook performs comprehensive validation:

1. **Hardware Verification**: Confirms the boot device exists and meets size requirements (90GB minimum)
2. **ZFS Pool Status**: Checks if pools already exist to avoid destructive operations
3. **Device State**: Verifies storage devices are clean and available for use
4. **Running Workloads**: Warns if containers or VMs are running that might be affected
5. **System Validation**: Confirms the target is actually a Proxmox system

#### Storage Layout Created

The playbook creates a sophisticated storage layout optimized for different workloads:

**Hot Storage Partition**
- Located on the boot device (typically NVMe for speed)
- Uses remaining space after OS installation (typically 43GB+)
- Formatted as ext4 with optimized mount options
- Used for ISOs, templates, and frequently accessed data
- Handles both traditional (`/dev/sda`) and NVMe (`/dev/nvme0n1p`) device naming

**ZFS Pools**
- **Security Pool** (`/dev/sdb`): Optimized for security applications like Wazuh, Graylog
- **Gaming Pool** (`/dev/sdc`): Configured for game servers (Minecraft, AzerothCore, ARK)
- **Monitoring Pool** (`/dev/sdd`): Tuned for time-series data (Grafana, Prometheus, TimescaleDB)

Each ZFS pool includes:
- Optimal `ashift` settings for device alignment
- LZ4 compression for space efficiency
- Disabled `atime` for performance
- Automatic TRIM support for SSDs

**Temporary Storage**
- Dedicated fast storage device for backups and transfers
- Separate from main pools to avoid I/O contention
- Formatted as ext4 for maximum compatibility

#### ZFS Dataset Organization

The playbook creates specialized datasets for different application types:

**Security Datasets**
```
security/wazuh-data     - WAZUH SIEM data with high compression
security/graylog-data   - Graylog logs with recordsize optimization
security/elasticsearch  - Elasticsearch indices with custom tuning
```

**Gaming Datasets**
```
gaming/minecraft-worlds - Minecraft world data with sync=disabled
gaming/azerothcore-db   - Database files with recordsize=16K
gaming/ark-saves        - ARK server saves with compression
```

**Monitoring Datasets**
```
monitoring/grafana-data    - Grafana configuration and dashboards
monitoring/timescaledb     - TimescaleDB hypertables (recordsize=32K)
monitoring/prometheus      - Prometheus TSDB with custom tuning
```

#### Proxmox Integration

The playbook automatically configures Proxmox storage entries:

- **ZFS Storage**: Each pool gets VM image and container storage entries
- **Directory Storage**: Hot storage and temporary storage are configured as directory stores
- **Node-Specific**: All storage is properly tagged for the specific Proxmox node
- **Content Types**: Appropriate content types assigned (images, containers, ISOs, backups)

#### Safety Features

**Idempotent Operations**
- Safe to run multiple times without causing damage
- Checks existing state before making changes
- Only creates resources that don't already exist

**Device Protection**
- Refuses to operate on devices that already contain data
- Validates device paths before attempting operations
- Provides clear error messages for common issues

**State Reporting**
- Comprehensive summary of what was created vs. what already existed
- Clear indication of system readiness status
- Detailed logging for troubleshooting

#### Performance Optimizations

**ZFS Tuning**
- `ashift=12`: Optimal for 4K sector devices
- `compression=lz4`: Fast compression with good ratios
- `atime=off`: Eliminates access time updates for better performance
- `autotrim=on`: Automatic SSD optimization

**Application-Specific Settings**
- Database workloads get optimized recordsize settings
- Log storage uses appropriate compression levels
- Game servers get tuning for frequent small writes

**Mount Options**
- `noatime`: Prevents access time updates on traditional filesystems
- `defaults`: Standard reliability options
- Optimized for the specific use case of each mount point

#### Error Handling

The playbook includes robust error handling:

- **Pre-validation**: Stops before making changes if requirements aren't met
- **Graceful Failures**: Clear error messages for common configuration issues
- **Cleanup**: Automatic cleanup of partial configurations on failure
- **Recovery**: Provides guidance for manual intervention when needed

This storage configuration creates a production-ready foundation for running diverse workloads on Proxmox while maintaining optimal performance and data safety.

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

### Storage Setup
- **Hot storage partition start**: `43GiB` (should be `hot_storage_partition_start`)
- **Package requirements**: Hardcoded package list (should be `required_packages`)
- **Mount point permissions**: Hardcoded to `0755` (should be configurable)

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
5. **ZFS Pool Creation**: Ensure devices are clean and not already part of other pools

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

### Storage Verification

Verify storage configuration after setup:
```bash
# Check ZFS pools
zpool status
zfs list

# Check mount points
df -h

# Check Proxmox storage
pvesm status
```

## Security Considerations

- The automation user has NOPASSWD sudo access - restrict as needed for your environment
- SSH keys are used for authentication - ensure proper key management
- Terraform API tokens have Administrator privileges - consider role-based restrictions
- Docker daemon access grants significant system privileges
- ZFS pools are created with default permissions - review for security requirements

## Contributing

When modifying these playbooks:
1. Test on non-production Proxmox instances
2. Ensure idempotency is maintained
3. Add appropriate error handling
4. Update documentation for new variables
5. Consider backward compatibility
6. Test storage operations thoroughly before deploying