# terraform/management-stack/README.md

# Management Stack - Portainer Server Deployment

This stack deploys a centralized Portainer Server instance within a Proxmox LXC container using a modular Terraform and Ansible approach.

## Overview

The management stack creates:
- An LXC container with Docker pre-installed
- A Portainer Server instance with `--tlsskipverify` for easy agent connections
- Dynamic Ansible inventory generation
- Modular, reusable infrastructure components

## Architecture

```
terraform/management-stack/
├── main.tf                           # Stack definition using lxc-docker-host module
├── variables.tf                      # Stack-specific variables
├── terraform.tfvars                  # Configuration values
├── inventory.tpl                     # Ansible inventory template
└── ansible/                          # Stack-specific Ansible automation
    ├── playbook.yml                  # Main playbook
    ├── inventory.yml                 # Generated inventory (auto-created)
    └── roles/
        ├── docker_base/              # Base Docker setup for all containers
        │   └── tasks/main.yml
        └── portainer_server/         # Portainer-specific deployment
            └── tasks/main.yml
```

## Prerequisites

* **Proxmox Server**: Operational Proxmox server with API access
* **LXC Template**: Debian-based template with Docker pre-installed (`debian-docker-template.tar.gz`)
* **Tools**: `terraform` and `ansible` installed locally
* **SSH Key**: Valid SSH key pair at `~/.ssh/id_rsa` and `~/.ssh/id_rsa.pub`
* **Environment Variables**: Proxmox credentials set via `.env` file

## Configuration Variables

### Required (via environment variables)
| Variable | Description | Example |
|----------|-------------|---------|
| `TF_VAR_proxmox_api_url` | Proxmox API endpoint | `https://pve.example.com:8006/api2/json` |
| `TF_VAR_pm_api_token_id` | API token ID | `automation@pve!terraform` |
| `TF_VAR_pm_api_token_secret` | API token secret | `uuid-string` |
| `TF_VAR_lxc_password` | Container root password | `secure-password` |

### Optional (with defaults)
| Variable | Default | Description |
|----------|---------|-------------|
| `proxmox_node` | `pvetest` | Target Proxmox node |
| `portainer_vmid` | `101` | LXC container ID |
| `portainer_hostname` | `portainer-server` | Container hostname |
| `portainer_ip_address` | `192.168.1.70/24` | Static IP with CIDR |
| `portainer_memory` | `3072` | RAM allocation (MB) |
| `portainer_cores` | `2` | CPU core count |
| `portainer_rootfs_size` | `15G` | Root filesystem size |

### Customizing via terraform.tfvars

Create or edit `terraform.tfvars` to override defaults:

```hcl
# Container specifications
portainer_hostname = "mgmt-portainer"
portainer_ip_address = "192.168.1.75/24"
portainer_memory = 2048
portainer_cores = 1
portainer_rootfs_size = "10G"

# Optional: Override node
proxmox_node = "pve-node-2"
```

## Deployment

1. **Set environment variables**:
   ```bash
   # Create .env file in project root
   export TF_VAR_proxmox_api_url="https://your-proxmox:8006/api2/json"
   export TF_VAR_pm_api_token_id="automation@pve!terraform"
   export TF_VAR_pm_api_token_secret="your-secret"
   export TF_VAR_lxc_password="your-password"
   source .env
   ```

2. **Deploy the stack**:
   ```bash
   cd terraform/management-stack
   terraform init
   terraform apply --auto-approve
   ```

3. **Access Portainer**:
   - Navigate to `http://192.168.1.70:9000` (or your configured IP)
   - Complete initial setup and create admin user

## Expected Outcome

- LXC container running on specified Proxmox node
- Portainer Server accessible via web interface
- Container configured with `--tlsskipverify` for easy agent connections
- Ready to manage Docker containers across your infrastructure

## Adding New Parameters

To add new configurable parameters:

1. **Add variable to `variables.tf`**:
   ```hcl
   variable "new_parameter" {
     description = "Description of the parameter"
     type        = string
     default     = "default-value"
   }
   ```

2. **Use variable in module call in `main.tf`**:
   ```hcl
   module "portainer_server" {
     # ... existing parameters
     new_param = var.new_parameter
   }
   ```

3. **Ensure the module accepts the parameter** in `../modules/lxc-docker-host/variables.tf`

4. **Use in module's resource** in `../modules/lxc-docker-host/main.tf`

## Extending with Additional Services

### Option 1: Ansible Integration
Add new roles to deploy additional services directly on the LXC container:

```yaml
# ansible/playbook.yml
- name: Deploy Additional Service
  hosts: portainer_server
  roles:
    - docker_base
    - portainer_server
    - monitoring_agent    # New service role
```

### Option 2: Portainer API Integration

For more advanced deployments, interact with Portainer's API to deploy services:

1. **API Authentication**:
   ```bash
   # Get auth token
   curl -X POST http://192.168.1.70:9000/api/auth \
     -H "Content-Type: application/json" \
     -d '{"Username":"admin","Password":"your-password"}'
   ```

2. **Deploy via Stack API**:
   ```bash
   # Deploy Docker Compose stack via API
   curl -X POST http://192.168.1.70:9000/api/stacks \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "Name": "media-stack",
       "SwarmID": "1",
       "StackFileContent": "version: '\''3'\''\nservices:\n  plex:\n    image: plexinc/pms-docker\n    ports:\n      - 32400:32400"
     }'
   ```

3. **Terraform Integration**:
   ```hcl
   # Use HTTP provider to manage Portainer stacks
   resource "http" "deploy_stack" {
     url    = "http://${module.portainer_server.ip_address}:9000/api/stacks"
     method = "POST"
     
     request_headers = {
       "Authorization" = "Bearer ${var.portainer_token}"
       "Content-Type"  = "application/json"
     }
     
     request_body = jsonencode({
       Name = "my-application"
       StackFileContent = file("${path.module}/docker-compose.yml")
     })
   }
   ```

### Benefits of API Integration

- **Centralized Management**: All services managed through Portainer UI
- **Stack Templates**: Reusable compose file templates
- **Environment Separation**: Different stacks for dev/staging/prod
- **Health Monitoring**: Built-in container health and log monitoring
- **Access Control**: Role-based access to different stacks

### Recommended Workflow for API Integration

1. Deploy management stack (Portainer)
2. Create separate Terraform modules for each application stack
3. Each application stack:
   - Deploys LXC container with Portainer Agent
   - Registers agent with Portainer Server
   - Deploys application via Portainer API
4. Use Portainer UI for ongoing management and monitoring

## Troubleshooting

### Common Issues

1. **Ansible Template Errors**: Ensure proper escaping of Docker format strings in shell commands
2. **Container ID Conflicts**: Check `portainer_vmid` isn't already in use
3. **Network Conflicts**: Verify IP address isn't already assigned
4. **SSH Connection Issues**: Ensure SSH key is properly configured and accessible

### Debug Commands

```bash
# Check container status
terraform show | grep ip_address

# Test Ansible connectivity
cd ansible && ansible portainer_server -i inventory.yml -m ping

# View container logs
docker logs portainer

# Check Portainer API health
curl http://192.168.1.70:9000/api/status
```

## Related Documentation

- [LXC Docker Host Module](../modules/lxc-docker-host/README.md)
- [Portainer API Documentation](https://docs.portainer.io/api/docs)
- [Terraform Proxmox Provider](https://registry.terraform.io/providers/Telmate/proxmox/latest/docs)