### agent-stack

**Purpose**: Deploys Portainer Agents that connect to the management-stack server and can host application deployments.

**Components**:
- LXC container (via `lxc-docker-host` module)
- Portainer Agent with automatic server registration
- Application stack deployment via Portainer API
- Dynamic Ansible inventory generation
- Automatic cleanup on destroy

**Features**:
- **Automatic Registration**: Agent automatically registers with Portainer server via API
- **Application Deployment**: Deploys Docker Compose stacks through Portainer API
- **Centralized Management**: All containers managed through Portainer web interface
- **API-Driven**: Full deployment automation without manual Portainer UI interaction
- **Clean Destruction**: Automatically unregisters agent and removes stacks on `terraform destroy`

**Configuration Variables**:

| Variable | Default | Description |
|----------|---------|-------------|
| `agent_hostname` | `"portainer-agent-1"` | Hostname for the agent container |
| `agent_ip_address` | `"192.168.1.71/24"` | Static IP for the agent |
| `agent_memory` | `1536` | Memory allocation (MB) |
| `agent_cores` | `1` | CPU core allocation |
| `agent_rootfs_size` | `"10G"` | Root filesystem size |
| `portainer_server_ip` | `"192.168.1.70"` | IP of Portainer server for registration |

**Usage Example**:
```bash
# Set required environment variables
export PORTAINER_ADMIN_PASSWORD="your-admin-password"

# Deploy agent with application
cd terraform/agent-stack
terraform init
terraform apply --auto-approve

# Access deployed nginx at http://192.168.1.71:80
# Manage via Portainer UI at http://192.168.1.70:9000
```

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
- **Template Variables**: `portainer_agent_image`, `portainer_agent_port`, `portainer_compose_dir`

#### portainer_api
- **Purpose**: Registers agents with Portainer server via API calls
- **Functions**: Authenticates with server, registers new endpoints, handles TLS certificate issues
- **Features**: Automatic endpoint discovery, graceful error handling for existing agents
- **API Requirements**: Uses form-data format for registration, handles certificate validation

#### app_stack
- **Purpose**: Deploys Docker Compose applications via Portainer API
- **Functions**: Creates stacks through API, manages existing stack cleanup, supports environment variables
- **Benefits**: Centralized application management, stack versioning, rollback capabilities
- **API Endpoint**: Uses `/api/stacks/create/standalone/string` for deployment

### Architecture Flow

```
1. lxc-docker-host module creates container
2. docker_base role configures Docker environment  
3. portainer_agent role deploys agent container
4. portainer_api role registers agent with server
5. app_stack role deploys applications via API
6. [On destroy] cleanup provisioner unregisters agent
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
    app_stack_compose_content: |
      version: '3.8'
      services:
        nginx:
          image: nginx:alpine
          ports:
            - "80:80"
  roles:
    - ../../ansible/shared-roles/app_stack
```

### API Integration Details

The architecture leverages Portainer's REST API for complete automation:

#### Authentication Flow
```bash
# Get JWT token
POST /api/auth
{"Username": "admin", "Password": "password"}
→ {"jwt": "eyJ0eXAiOiJ..."}
```

#### Agent Registration
```bash
# Register new agent (form-data required)
POST /api/endpoints
-F "Name=agent-name"
-F "URL=tcp://agent-ip:9001" 
-F "EndpointCreationType=2"
-F "TLS=true"
-F "TLSSkipVerify=true"
```

#### Stack Deployment
```bash
# Deploy Docker Compose stack
POST /api/stacks/create/standalone/string?endpointId=X
{
  "method": "string",
  "type": "standalone", 
  "Name": "stack-name",
  "StackFileContent": "version: '3.8'\n...",
  "Env": []
}
```

#### Cleanup on Destroy
```bash
# Remove stacks and unregister endpoint
DELETE /api/stacks/{stackId}?endpointId=X
DELETE /api/endpoints/{endpointId}
```

### Benefits of Shared Architecture

- **Consistency**: Same base configuration across all deployments
- **Maintainability**: Updates to shared roles affect all stacks  
- **Reusability**: New stacks inherit proven functionality
- **API-First**: All management through Portainer API enables full automation
- **Centralized Control**: Single Portainer interface manages entire infrastructure
- **Clean Lifecycle**: Automatic registration and cleanup prevents orphaned resources
- **Error Resilience**: Comprehensive error handling for network issues and timing problems
- **Scalability**: Easy to deploy multiple agents with different applications

### Environment Requirements

For full functionality, ensure these environment variables are set:

```bash
# Terraform variables (can also use terraform.tfvars)
export TF_VAR_proxmox_api_url="https://your-proxmox:8006/api2/json"
export TF_VAR_pm_api_token_id="automation@pve!terraform"  
export TF_VAR_pm_api_token_secret="your-secret"
export TF_VAR_lxc_password="your-container-password"

# Portainer API access
export PORTAINER_ADMIN_PASSWORD="your-portainer-admin-password"
```

### Troubleshooting Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Agent registration fails | API format/timing | Check form-data format, add delays |
| Stack deployment 405 error | Wrong API endpoint | Use `/api/stacks/create/standalone/string` |
| TLS verification errors | Certificate IP mismatch | Use `TLSSkipVerify=true` in registration |
| Destroy-time cleanup fails | Missing environment variables | Set `PORTAINER_ADMIN_PASSWORD` before destroy |
| Orphaned stacks in UI | Incomplete cleanup | Manual cleanup via Portainer UI or API |