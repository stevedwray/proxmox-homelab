# Sock Shop Microservices Deployment - Project Status Summary

## Infrastructure Foundation
- **Environment**: Proxmox VE 9.0.3 running in VMware Workstation with nested virtualization
- **Templates**: Created custom LXC template with Docker pre-installed using vzdump backup method
- **Authentication**: automation@pve user with Administrator role permissions
- **Network**: 192.168.1.x range with static IP assignments

## Achievements

### Terraform Integration Resolved
- **Template Creation**: Successfully created `debian-12-docker.tar.gz` template from working container using `vzdump 100 --mode stop --compress gzip --dumpdir /var/lib/vz/template/cache/`
- **Provider Compatibility**: Downgraded from telmate/proxmox v2.9.14 to v2.9.11 to resolve permission validation bugs with Proxmox VE 9.0.3
- **Template Reference**: Correct format is `ostemplate = "local:vztmpl/debian-12-docker.tar.gz"` for file-based templates
- **Container Features**: Removed `keyctl = true` requirement (needs root@pam privileges), kept `nesting = true` for Docker functionality

### Single Container Deployment (Phase 1) - SUCCESSFUL
- **Infrastructure**: Container 101 at 192.168.1.60 deployed via Terraform
- **Application**: Sock Shop frontend and catalogue services deployed via Ansible
- **Validation**: Web interface accessible at http://192.168.1.60, Docker containers running correctly
- **Services**: front-end (port 80), catalogue (internal), portainer-agent (port 9001)

### Multi-Container Infrastructure (Phase 2) - PARTIAL SUCCESS
- **Infrastructure**: 3 containers deployed (192.168.1.60, .61, .62) via Terraform
- **Issue**: Ansible deployment failed due to inventory mismatch - playbook expects 8 containers but only 3 exist
- **Current State**: Additional containers running but only with Portainer Agent, no application services

## Key Problems and Resolutions

### Template Reference Issues
- **Problem**: Initial configuration used non-existent template references (`"901"`, `"local:vztmpl/template-901"`)
- **Resolution**: Created proper file-based template using vzdump backup of working container
- **Template Path**: `"local:vztmpl/debian-12-docker.tar.gz"`

### Terraform Provider Permissions
- **Problem**: VM.Monitor permission errors and privilege validation failures
- **Root Cause**: Newer provider version (v2.9.14) incompatible with Proxmox VE 9.0.3 permission structure
- **Resolution**: Downgraded to provider version 2.9.11

### Container Cloning vs Template Files
- **Problem**: Container templates (created with `pct template`) vs file-based templates have different reference methods
- **Resolution**: Used vzdump to create proper file-based template that works with Terraform provider

### Authentication Scope
- **Problem**: automation@pve user lacks privileges for certain container operations
- **Resolution**: For template creation operations, use root@pam; automation@pve sufficient for standard deployments

## Current File Structure
```
terraform/sock-shop/
├── single-container/     # Working deployment
│   ├── main.tf          # Uses debian-12-docker.tar.gz template
│   └── variables.tf
└── multi-container/     # Infrastructure only
    ├── main.tf          # 3 containers deployed
    └── variables.tf

ansible/
├── inventory/sock-shop.yml    # Configured for full 8-container deployment
└── sock-shop/
    ├── deploy-frontend.yml         # Works for single container
    └── deploy-multi-container.yml  # Fails due to inventory mismatch
```

## Working Configuration Parameters
- **Provider**: `telmate/proxmox` version `2.9.11`
- **Template**: `local:vztmpl/debian-12-docker.tar.gz`
- **Features**: `nesting = true` only (no keyctl)
- **Authentication**: automation@pve with Administrator role
- **Node Reference**: `pvetest` (not default `pve`)

## Next Steps Required
1. **Fix Ansible Inventory**: Update `sock-shop.yml` to match actual 3-container deployment or deploy full 8-container infrastructure
2. **Service Communication Testing**: Deploy database services to test inter-container communication
3. **Terraform-Only Approach**: Test alternative deployment method using embedded scripts
4. **Full Stack Deployment**: Deploy complete 8-container architecture for end-to-end validation

## Environment Variables
All deployments require these variables:
- `TF_VAR_proxmox_api_url=https://pvetest.gibbsgreatly.xyz:8006/api2/json`
- `TF_VAR_proxmox_user=automation@pve`
- `TF_VAR_proxmox_password=[password]`

The project has successfully demonstrated infrastructure-as-code deployment with Docker-in-LXC functionality. The main remaining challenge is aligning the Ansible application deployment with the actual container topology.
