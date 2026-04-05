# Proxmox LXC Template Automation Project Summary

## Environment
- **Test Setup**: Proxmox VE 9.0.3 running in VMware Workstation (nested virtualization)
- **Storage**: ZFS (`local-zfs` pool) with `local` for templates
- **Domain**: `pvetest.gibbsgreatly.xyz` with Cloudflare DNS management
- **Tools**: Ansible for automation, WSL2 development environment

## Completed Achievements

### Base LXC Template Creation
**File**: `01-base-system/build-lxc-template.yml`
- Automated creation of LXC container (ID 900) from Debian 12 template
- Configured with nesting support (`--features nesting=1,keyctl=1`) for Docker compatibility
- Standard package installation: curl, wget, vim, emacs-nox, htop, git, network tools (tcpdump, netstat, nmap, traceroute)
- Docker CE with standalone docker-compose installation
- Automation user with SSH key access and sudo privileges
- Portainer Agent pre-configured (systemd service ready)
- Console auto-login attempted (partial success)

### Enhanced Security Template
**File**: `01-base-system/enhance-lxc-template.yml`
- Security tools: Trivy vulnerability scanner, Docker Bench Security, UFW firewall, fail2ban
- Monitoring: Prometheus Node Exporter (port 9100)
- Standardized directory structure: `/data`, `/config`, `/logs`, `/backups`, `/opt/docker`
- Enhanced logging: journald + rsyslog configuration for remote forwarding
- Management scripts: `security-scan`, `mount-helper`, `container-info`
- Basic CIS hardening: automatic security updates, firewall rules

## Key Problems and Resolutions

### 1. Proxmox API Authentication
**Problem**: Initial confusion about authentication method (expected tokens, actual ticket-based)
**Resolution**: Confirmed Proxmox VE 9.0.3 uses ticket authentication with 2-hour expiration

### 2. Storage Configuration
**Problem**: Playbook initially used `local-lvm` (non-existent), causing container creation failure
**Resolution**: Discovered actual storage pools (`local-zfs`) using storage discovery playbook, made storage configurable via host_vars

### 3. Docker Container Permissions
**Problem**: Docker containers failed to start in LXC with "permission denied" errors
**Resolution**: Added `--features nesting=1,keyctl=1` to LXC container creation for proper nested containerization support

### 4. Let's Encrypt Certificate Installation
**Problem**: Python package management conflicts with Debian's externally-managed environment
**Resolution**: Deferred certificate automation (manual installation via Proxmox console deemed acceptable for lab)

### 5. Console Auto-login Configuration
**Problem**: LXC containers use different console devices than expected, auto-login not working
**Resolution**: Partial fix attempted, but manual password setting used as workaround

### 6. Ansible Template Processing
**Problem**: Docker format strings `{{.Repository}}` in shell scripts conflicted with Jinja2 templating
**Resolution**: Escaped Docker format strings using `{{'{{'}}.Repository{{'}}'}}` syntax

### 7. SSH Host Key Regeneration
**Problem**: Cloned containers missing SSH host keys after template cleanup
**Resolution**: Manual `ssh-keygen -A` required after cloning

## Inventory Structure
```yaml
proxmox: (pvetest.gibbsgreatly.xyz)
template_builder: (192.168.1.50) - base template
template_enhanced: (192.168.1.51) - enhanced template
```

## Final Template States
- **Template 900**: Base template with Docker, standard tools, Portainer Agent
- **Template 901**: Enhanced template with security tools, monitoring, standardized structure

## Environment Flexibility
- Host-specific variables in `host_vars/pvetest.yml` for test environment
- Configurable storage pools, network settings, and container specifications
- Discovery playbook available for new environments

## Workflow
1. Base template creation with Docker support
2. Optional enhancement with security/monitoring tools
3. Manual template conversion via `pct template <id>`
4. Container cloning with `pct clone <template_id> <new_id>`

The system provides reusable, Docker-ready LXC templates with optional security hardening for development and testing environments.
