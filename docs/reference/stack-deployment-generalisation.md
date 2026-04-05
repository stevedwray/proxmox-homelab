# Stack Deployment Generalisation Guide

This document describes the process of generalizing an application stack deployment pattern so new stacks can be created consistently.

## Overview

The repository uses a modular approach with reusable Terraform and Ansible components. The goal is to make new application stacks easy to create by reusing standard infrastructure patterns.

### Architecture Foundation

Shared components include:

- Terraform modules for Proxmox LXC containers
- Ansible roles for Docker, Portainer, and application deployment
- API-driven deployment through Portainer
- Modular variable passing and environment configuration
- Automatic cleanup on infrastructure destruction

## agent-stack: The Foundation Pattern

The `agent-stack` pattern is the proven baseline.

### Core Components

**Terraform definition**

- Creates a Proxmox LXC optimized for Docker workloads
- Uses a reusable module for networking, storage, and container settings
- Generates inventory and triggers Ansible configuration where needed

**Ansible automation**

- Deploys Docker base configuration
- Installs Portainer Agent
- Registers the agent with Portainer server via API
- Deploys an application stack through Portainer

### Key Characteristics

- Deploys a minimal test stack
- Uses consistent Docker container configuration
- Relies on reusable roles and environment variables
- Supports easy extension to other app-specific stacks

## Generalization Process: Creating a New Stack

### Step 1: Copy the Proven Structure

Start from the existing stack directory and copy it into a new stack name:

```bash
cp -r terraform/agent-stack terraform/torrent-stack
cd terraform/torrent-stack
```

### Step 2: Customize Configuration

Update `terraform.tfvars` and variables to reflect the new stack purpose.

Example updates:

- `agent_hostname` → `torrent-stack`
- `agent_ip_address` → `192.168.1.72/24`
- `agent_memory` → `4096`
- `agent_rootfs_size` → `50G`

### Step 3: Adjust Ansible Deployment

Update the playbook to deploy the new application stack.

Example tasks:

- Create required directories for app data
- Deploy a new Compose stack instead of a simple nginx test app
- Add app-specific configuration and secrets

### Step 4: Handle Specialized System Requirements

Some stacks require extra host or container configuration.

Example: VPN-enabled torrent stacks need `/dev/net/tun` access.

Create a specialized role such as `lxc_tun_device` to modify the LXC configuration and enable the device.

## Example: Torrent Stack Adaptation

### Specialized role for VPN access

The `lxc_tun_device` role can:

- discover the target container VMID
- write LXC configuration entries for device access
- reload or restart the container if needed

### Integration into the playbook

Add the role to the stack playbook so VPN-specific host configuration is applied before the application starts.

## Data Migration Pattern

### Migration Challenge

Moving existing production configuration to a new deployment without losing:

- application settings and API keys
- database configuration
- SSL certificates
- media library organization

### Migration Solution

Use Ansible to archive and transfer configuration data safely.

Example approach:

- create archive files on the source host
- fetch archives to the control machine
- extract archives to the new target environment
- verify service behavior after migration

## Best Practices

- Keep each stack directory small and focused
- Reuse common Terraform modules wherever possible
- Avoid hardcoding application secrets in Terraform
- Use Portainer API and compose variables for runtime configuration
- Document stack-specific requirements in the stack folder

## Future Stack Ideas

- `torrent-stack` for media and VPN workloads
- `agent-stack` for generic Portainer agent deployments
- `monitoring-stack` for observability services

## Benefits of Generalization

- faster stack creation
- fewer duplicate configuration patterns
- more predictable deployments
- easier maintenance and drift detection
