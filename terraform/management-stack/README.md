# Management Stack

This stack deploys the core management services for the homelab infrastructure:

## Services

### Currently Implemented
- **Portainer Server** - Container orchestration and management UI

### Planned (Placeholder)
- **Harbor Registry** - Container registry with vulnerability scanning
- **Nginx Proxy Manager** - Reverse proxy with SSL termination

## Quick Start

1. Copy the example variables file:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```

2. Edit `terraform.tfvars` with your environment details

3. Deploy the stack:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

4. Access Portainer:
   - HTTP: http://YOUR_IP:9000
   - HTTPS: https://YOUR_IP:9443

## Development Phases

### Phase 1: Portainer Server ✅
- Working Portainer deployment
- Placeholder framework for Harbor and NPM

### Phase 2: Harbor Integration (Planned)
- Harbor registry deployment
- Robot account creation
- Registry authentication setup

### Phase 3: Nginx Proxy Manager (Planned)
- NPM deployment
- SSL certificate automation
- Domain routing configuration

## Infrastructure Details

- **Container**: Proxmox LXC with Docker
- **Resources**: 2 cores, 4GB RAM, 25GB storage
- **Network**: Static IP with bridge networking
- **Storage**: ZFS-backed persistent volumes

## Service URLs (When Complete)

- Portainer: https://portainer.gibbsgreatly.xyz
- Harbor: https://harbor.gibbsgreatly.xyz
- NPM Admin: https://npm.gibbsgreatly.xyz
- Registry API: https://registry.gibbsgreatly.xyz