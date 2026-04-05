# terraform/management-stack/README.md

# Management Stack - Portainer Server Deployment

This stack deploys a centralized Portainer Server instance within a Proxmox LXC container using a modular Terraform and Ansible approach.

## Overview

The management stack creates:
- An LXC container with Docker pre-installed
- A Portainer Server instance with `--tlsskipverify` for easy agent connections
- Dynamic Ansible inventory generation
- Modular, reusable infrastructure components
- Nginx Proxy Manager for reverse proxy and SSL management (optional)

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

### NPM-Specific Variables (Optional)
| Variable | Default | Description |
|----------|---------|-------------|
| `enable_npm` | `false` | Deploy Nginx Proxy Manager |
| `npm_data_source` | `/srv/npm/data` | Source path for NPM data |
| `npm_letsencrypt_source` | `/srv/npm/letsencrypt` | Source path for SSL certificates |

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

# Container Registry Integration

The management stack includes an optional centralized container registry with vulnerability scanning capabilities, deployed alongside Portainer for comprehensive Docker infrastructure management. The registry operates as a **pull-through cache**, automatically caching all images pulled from Docker Hub for vulnerability scanning and centralized management.

## Registry Components

When enabled (`TF_VAR_enable_harbor="true"`), the stack deploys:

- **Docker Registry with Pull-Through Cache**: Automatically caches images from Docker Hub at `http://192.168.1.70:80`
- **Registry Web UI**: Browse all cached images at `http://192.168.1.70:8080`  
- **Trivy Scanner**: Vulnerability scanning service at `http://192.168.1.70:4954`
- **Portainer Management**: Registry stack managed via Portainer UI

## Configuration

### Environment Variables
```bash
# Required for registry deployment
export HARBOR_ADMIN_PASSWORD="your-secure-password"
export PORTAINER_ADMIN_PASSWORD="your-portainer-password"

# Enable/disable registry (default: true if HARBOR_ADMIN_PASSWORD is set)
export TF_VAR_enable_harbor="true"
```

### Deployment
```bash
source .env
cd terraform/management-stack
terraform apply
```

## Automatic Image Caching

The registry is configured as a pull-through cache for Docker Hub, which means **all Docker operations automatically populate your registry** without manual intervention.

### Configure Docker Clients for Automatic Caching

On your LXC containers or other Docker hosts, configure Docker to use the registry as a mirror:

```bash
# /etc/docker/daemon.json
{
  "registry-mirrors": ["http://192.168.1.70"],
  "insecure-registries": ["192.168.1.70"]
}

# Restart Docker
sudo systemctl restart docker
```

### How Pull-Through Caching Works

With the mirror configuration:

1. **Any Docker pull** automatically uses your registry:
   ```bash
   docker pull nginx:latest
   # → Checks 192.168.1.70 first
   # → If not found, pulls from Docker Hub and caches locally
   # → Future pulls serve from local cache
   ```

2. **Docker Compose stacks** automatically cache all images:
   ```yaml
   version: '3.8'
   services:
     nginx:
       image: nginx:latest     # Automatically cached to 192.168.1.70
     postgres:
       image: postgres:13      # Automatically cached to 192.168.1.70
   ```

3. **All cached images** are immediately available for scanning:
   ```bash
   trivy image --server http://192.168.1.70:4954 192.168.1.70/library/nginx:latest
   ```

### Manual Push Operations

You can still manually push custom images:

```bash
# Build and push custom images
docker build -t myapp:latest .
docker tag myapp:latest 192.168.1.70/myapp:latest
docker push 192.168.1.70/myapp:latest
```

## Vulnerability Scanning

The integrated Trivy scanner provides comprehensive vulnerability detection for all cached and pushed images.

### Install Trivy Client

On machines where you want to run scans:

```bash
# Ubuntu/Debian
wget https://github.com/aquasecurity/trivy/releases/download/v0.45.0/trivy_0.45.0_Linux-64bit.tar.gz
tar zxf trivy_0.45.0_Linux-64bit.tar.gz
sudo mv trivy /usr/local/bin/
```

### Scan Cached Images

```bash
# Scan individual cached images
trivy image --server http://192.168.1.70:4954 192.168.1.70/library/nginx:latest

# Get JSON output for automation
trivy image --server http://192.168.1.70:4954 --format json 192.168.1.70/library/postgres:13

# Scan only HIGH/CRITICAL vulnerabilities
trivy image --server http://192.168.1.70:4954 --severity HIGH,CRITICAL 192.168.1.70/library/nginx:latest
```

### Automated Scanning of All Cached Images

Create a comprehensive scanning script:

```bash
#!/bin/bash
# scan-all-cached.sh

REGISTRY="192.168.1.70"
TRIVY_SERVER="http://192.168.1.70:4954"
REPORT_DIR="./vulnerability-reports"

mkdir -p $REPORT_DIR

echo "Scanning all cached images in registry..."

# Get all repositories (both pulled from Docker Hub and manually pushed)
curl -s http://$REGISTRY/v2/_catalog | jq -r '.repositories[]' | while read repo; do
    echo "Processing repository: $repo"
    
    # Get all tags for this repository
    curl -s http://$REGISTRY/v2/$repo/tags/list | jq -r '.tags[]' | while read tag; do
        IMAGE="$REGISTRY/$repo:$tag"
        SAFE_NAME=$(echo "$repo-$tag" | tr '/' '_')
        
        echo "  Scanning $IMAGE..."
        
        # Generate reports
        trivy image --server $TRIVY_SERVER --format json --output "$REPORT_DIR/$SAFE_NAME.json" $IMAGE
        trivy image --server $TRIVY_SERVER --severity HIGH,CRITICAL $IMAGE > "$REPORT_DIR/$SAFE_NAME-summary.txt"
        
        # Log vulnerabilities for Wazuh/monitoring
        VULN_COUNT=$(trivy image --server $TRIVY_SERVER --format json $IMAGE | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL" or .Severity=="HIGH")] | length')
        
        if [ "$VULN_COUNT" -gt 0 ]; then
            echo "$(date): Found $VULN_COUNT HIGH/CRITICAL vulnerabilities in $IMAGE" | logger -t CONTAINER_VULNERABILITY
        fi
    done
done

echo "Scan complete. Reports saved to $REPORT_DIR/"
```

### Integration with Wazuh

For comprehensive security monitoring, integrate vulnerability scanning with Wazuh:

```bash
#!/bin/bash
# wazuh-integration.sh

# Scan and send results to Wazuh
scan_and_report() {
    local IMAGE=$1
    local SCAN_RESULT=$(trivy image --server http://192.168.1.70:4954 --format json $IMAGE)
    
    # Extract vulnerability counts
    local CRITICAL=$(echo "$SCAN_RESULT" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")] | length')
    local HIGH=$(echo "$SCAN_RESULT" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH")] | length')
    
    # Send structured log to Wazuh
    logger -p local0.warn "VULNERABILITY_SCAN: {\"image\":\"$IMAGE\",\"critical\":$CRITICAL,\"high\":$HIGH,\"timestamp\":\"$(date -Iseconds)\"}"
}

# Scan all cached images
curl -s http://192.168.1.70/v2/_catalog | jq -r '.repositories[]' | while read repo; do
    curl -s http://192.168.1.70/v2/$repo/tags/list | jq -r '.tags[]' | while read tag; do
        scan_and_report "192.168.1.70/$repo:$tag"
    done
done
```

## Registry Management

### Web Interface

- **Browse All Images**: Visit `http://192.168.1.70:8080` to view both cached and pushed images
- **Cached Images**: Docker Hub images appear as `library/nginx`, `library/postgres`, etc.
- **Custom Images**: Your pushed images appear with their original names
- **Delete Images**: Remove unused images via the web interface

### Health Monitoring

```bash
# Registry health
curl http://192.168.1.70/v2/

# View cached repositories
curl http://192.168.1.70/v2/_catalog

# Trivy server health  
curl http://192.168.1.70:4954/version

# Web UI availability
curl http://192.168.1.70:8080
```

### Storage Management

```bash
# Check registry storage usage
docker exec central-registry du -sh /var/lib/registry

# View storage breakdown by repository
docker exec central-registry find /var/lib/registry -name repositories -exec du -sh {} \;
```

## Architecture Integration

### With Agent Stacks

Agent containers automatically benefit from the pull-through cache:

```yaml
# Agent stack compose - images automatically cached
version: '3.8'
services:
  nginx:
    image: nginx:alpine     # Cached from Docker Hub
  app:
    image: node:18          # Cached from Docker Hub
```

### With Application Stacks

All application images are automatically cached and scanned:

```yaml
version: '3.8'
services:
  web:
    image: nginx:alpine                    # Cached automatically
  database:
    image: postgres:13                     # Cached automatically  
  app:
    image: 192.168.1.70/mycompany/webapp   # Custom pushed image
```

## Workflow Benefits

The pull-through cache architecture provides:

1. **Zero Configuration**: All Docker operations automatically populate the registry
2. **Complete Coverage**: Every image used in your infrastructure gets scanned
3. **Performance**: Faster pulls after initial cache population
4. **Bandwidth Savings**: Reduces external Docker Hub requests
5. **Security Visibility**: Comprehensive vulnerability scanning of all images
6. **Compliance**: Centralized audit trail of all container images

## Future Enhancements

### Authentication
Add authentication for production environments:

```yaml
services:
  registry:
    environment:
      - REGISTRY_AUTH=htpasswd
      - REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd
```

### Multiple Registry Support
Extend caching to additional registries:

```yaml
services:
  registry:
    environment:
      - REGISTRY_PROXY_REMOTEURL=https://registry-1.docker.io
      - REGISTRY_PROXY_REMOTEURL_QUAY=https://quay.io
```

This pull-through cache configuration ensures that every Docker image used in your infrastructure is automatically stored in your registry and available for vulnerability scanning, providing comprehensive security coverage with zero operational overhead.

## Nginx Proxy Manager Integration (Optional)

When `enable_npm = true`, the stack deploys NPM for reverse proxy and SSL management:

- **NPM Admin Interface**: `http://192.168.1.70:81` (admin@example.com / changeme)
- **HTTP Proxy**: Port 80 for client traffic  
- **HTTPS Proxy**: Port 443 for SSL-terminated traffic

### Post-Deployment Data Migration
For migrating existing NPM configurations, see the [NPM Migration Documentation](../../ansible/02-infrastructure/README.md).

# NPM Data Migration Playbook

This directory contains infrastructure automation playbooks, including the NPM (Nginx Proxy Manager) data migration utility.

## Overview

The `migrate-npm-data.yml` playbook migrates production NPM configuration data to a freshly deployed management-stack instance. This two-phase approach ensures reliable infrastructure deployment followed by safe data migration.

## Architecture

### Deployment Phases

**Phase 1: Infrastructure Deployment**
- Terraform provisions LXC containers and base infrastructure
- Ansible deploys clean NPM instance via Portainer API
- NPM operational with default credentials (`admin@example.com` / `changeme`)

**Phase 2: Data Migration** 
- Separate Ansible playbook handles production data migration
- Configurable source locations for flexible deployment scenarios
- Safe backup and rollback capabilities

### Why Two Phases?

**Infrastructure First Approach Benefits:**
- **Proven Base**: Ensures NPM container and volumes work correctly before data migration
- **Failure Isolation**: Infrastructure issues separate from data migration issues  
- **Rollback Safety**: Clean backup available before production data replacement
- **Flexible Sources**: Can migrate from various source environments (LXC, Docker, bare metal)

## Playbook: migrate-npm-data.yml

### Purpose
Migrate production NPM data (database, SSL certificates, configuration) from source environment to management-stack deployment.

### Target Architecture
- **Source**: Production NPM deployment (LXC container, Docker, etc.)
- **Destination**: Management-stack container at `192.168.1.70`
- **Data Paths**: `/srv/npm/data` (database, config) and `/srv/npm/letsencrypt` (SSL certificates)

### Interactive Configuration
The playbook prompts for deployment-specific information:

| Prompt | Default | Description |
|--------|---------|-------------|
| Source Host/Container IP | `192.168.1.4` | IP address of source NPM deployment |
| Source Data Path | `/nginx/data` | Path to NPM data directory on source |
| Source Certs Path | `/nginx/certs` | Path to SSL certificates on source |
| Confirmation | `no` | Safety confirmation before migration |

### Migration Process

#### Pre-Migration Validation
1. **Connectivity Test**: Verifies SSH access to source host
2. **Source Verification**: Confirms database exists at specified path
3. **Container Status**: Ensures target NPM container is running
4. **Size Analysis**: Reports source database size for verification

#### Data Migration Steps
1. **Safe Shutdown**: Stops NPM container to prevent corruption
2. **Backup Creation**: Archives current data as rollback point
3. **Database Copy**: Transfers production SQLite database
4. **Configuration Copy**: Migrates keys.json and other config files
5. **Certificate Migration**: Copies SSL certificates and Let's Encrypt data
6. **Container Restart**: Starts NPM with production data
7. **Health Verification**: Confirms NPM accessibility post-migration

#### Data Types Migrated
- **Database**: SQLite database containing all proxy host configurations
- **SSL Certificates**: Let's Encrypt certificates, private keys, renewal configs
- **NPM Keys**: Internal RSA keypair for certificate management
- **Access Configuration**: User accounts, access lists, authentication settings

### Usage

#### Prerequisites
- Management-stack deployed and operational via Terraform
- NPM container running with default configuration
- SSH access to source NPM environment
- Source NPM data accessible and readable

#### Inventory Configuration
Playbook uses dedicated inventory at `inventory/migration.yml`:

```yaml
all:
  hosts:
    management_stack:
      ansible_host: 192.168.1.70
      ansible_user: root
      ansible_ssh_private_key_file: ~/.ssh/id_rsa
```

#### Execution
```bash
cd ansible
ansible-playbook -i inventory/migration.yml 02-infrastructure/migrate-npm-data.yml
```

#### Example Session
```bash
$ ansible-playbook -i inventory/migration.yml 02-infrastructure/migrate-npm-data.yml

Enter the source host/container IP for NPM data [192.168.1.4]: 192.168.1.4
Enter the source path for NPM data [/nginx/data]: /nginx/data  
Enter the source path for NPM certificates [/nginx/certs]: /nginx/certs
This will replace NPM data on 192.168.1.70. Continue? (yes/no) [no]: yes

PLAY [Migrate NPM Production Data] *********************************

TASK [Test connectivity to source host] ***************************
ok: [management_stack]

TASK [Get source database information] ****************************
ok: [management_stack -> 192.168.1.4]

TASK [Display source database info] *******************************
ok: [management_stack] => {
    "msg": [
        "Source database size: 152.0KB",
        "Source database modified: 2024-08-27 08:52:00"
    ]
}

TASK [Stop NPM container for data replacement] ********************
changed: [management_stack]

[... migration tasks continue ...]

TASK [Display migration results] **********************************
ok: [management_stack] => {
    "msg": [
        "Migration completed successfully!",
        "Final database size: 152.0KB", 
        "NPM accessible at: http://192.168.1.70:81",
        "SSL certificates: Migrated",
        "Backup saved to: /tmp/npm-backup-1693834567.tar.gz"
    ]
}
```

### Safety Features

#### Backup and Recovery
- **Automatic Backup**: Creates timestamped archive before migration
- **Rollback Path**: Backup can restore pre-migration state if needed
- **Verification**: Database size comparison confirms successful transfer

#### Error Handling
- **Connectivity Validation**: Fails fast if source unreachable
- **Data Verification**: Confirms source database exists before proceeding  
- **User Confirmation**: Explicit confirmation required before destructive operations
- **Graceful Cleanup**: Removes temporary files on completion or failure

#### Rollback Procedure
If migration fails or produces unexpected results:

```bash
# SSH to management-stack
ssh root@192.168.1.70

# Stop NPM container
docker stop nginx-proxy-manager

# Restore from backup (use actual timestamp from migration output)
tar -xzf /tmp/npm-backup-TIMESTAMP.tar.gz -C /srv/npm/

# Start NPM container  
docker start nginx-proxy-manager
```

### Common Migration Scenarios

#### LXC Container Source
```
Source Host: 192.168.1.4 (LXC container)  
Data Path: /nginx/data
Certs Path: /nginx/certs
```

#### Docker Container Source
```bash
# First extract data from Docker container to filesystem
docker cp npm-container:/data /tmp/npm-source/data
docker cp npm-container:/etc/letsencrypt /tmp/npm-source/certs

# Then migrate using filesystem paths
Source Host: 192.168.1.5 (Docker host)
Data Path: /tmp/npm-source/data
Certs Path: /tmp/npm-source/certs  
```

#### TrueNAS Scale Migration
```
Source Host: 192.168.1.10 (TrueNAS host)
Data Path: /mnt/pool/apps/nginx-proxy-manager/data
Certs Path: /mnt/pool/apps/nginx-proxy-manager/certs
```

### Post-Migration Verification

#### Database Verification
```bash
# Check database size matches source
ssh root@192.168.1.70 'ls -lah /srv/npm/data/database.sqlite'

# Verify table structure (optional)
ssh root@192.168.1.70 'sqlite3 /srv/npm/data/database.sqlite .schema'
```

#### Configuration Verification  
- Access NPM at `http://192.168.1.70:81`
- Login with production credentials (not `admin@example.com`)
- Verify proxy hosts appear in dashboard
- Check SSL certificate status
- Test proxy functionality to backend services

#### SSL Certificate Verification
```bash
# Check certificate files migrated
ssh root@192.168.1.70 'find /srv/npm/letsencrypt -name "*.pem" | wc -l'

# Verify certificate validity
ssh root@192.168.1.70 'find /srv/npm/letsencrypt/live -name "cert.pem" -exec openssl x509 -in {} -text -noout \;'
```

### Troubleshooting

#### Migration Fails - Connectivity Issues
```bash
# Test SSH access manually
ssh root@192.168.1.4 'ls -la /nginx/data/'

# Check source database permissions  
ssh root@192.168.1.4 'ls -la /nginx/data/database.sqlite'
```

#### Migration Succeeds But NPM Won't Start
```bash
# Check container logs
docker logs nginx-proxy-manager

# Verify file permissions
ls -la /srv/npm/data/

# Common fix - ownership issues
chown -R root:root /srv/npm/
```

#### Database Size Mismatch
```bash
# Compare source and destination
ssh root@192.168.1.4 'stat -c%s /nginx/data/database.sqlite'
ssh root@192.168.1.70 'stat -c%s /srv/npm/data/database.sqlite'

# If different, re-run migration or restore from backup
```

#### SSL Certificates Not Working
```bash
# Check certificate directory structure
ssh root@192.168.1.70 'find /srv/npm/letsencrypt -type f -name "*.pem"'

# Verify NPM can read certificates
docker exec nginx-proxy-manager ls -la /etc/letsencrypt/live/
```

### Integration with Infrastructure Pipeline

#### Terraform Integration
The migration playbook integrates with the broader infrastructure deployment:

```bash
# Complete deployment workflow
cd terraform/management-stack
terraform apply                    # Deploy infrastructure

cd ../../ansible  
ansible-playbook -i inventory/migration.yml 02-infrastructure/migrate-npm-data.yml    # Migrate data
```

#### CI/CD Integration
For automated deployments, the migration can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions step
- name: Migrate NPM Production Data
  run: |
    cd ansible
    echo "yes" | ansible-playbook -i inventory/migration.yml \
      02-infrastructure/migrate-npm-data.yml \
      -e source_host=${{ env.SOURCE_NPM_HOST }} \
      -e source_path=${{ env.SOURCE_NPM_PATH }}
```

### Security Considerations

#### Credential Protection
- NPM database contains encrypted passwords and API keys
- SSL private keys require secure transport and storage
- Migration occurs over SSH with key-based authentication
- Temporary files cleaned up automatically

#### Network Security  
- Migration traffic flows over SSH (encrypted)
- Source systems require SSH access from management-stack
- Consider VPN or secure network segments for production migrations

#### Access Control
- Migration requires root access on both source and destination
- SSH keys should be properly secured and rotated regularly
- Consider using dedicated migration user with minimal required permissions

### Performance Considerations

#### Network Bandwidth
- Database transfers typically < 1MB (fast)
- SSL certificate directories may be larger (multiple domains)
- Large certificate archives may take several minutes

#### Downtime Window
- NPM container stopped during migration (typically 1-2 minutes)
- Proxy services unavailable during this window
- Plan migration during maintenance windows for production systems

#### Storage Requirements
- Backup archives stored in `/tmp` (cleaned automatically)
- Ensure sufficient disk space for backup + migration data
- Consider backup retention policy for production environments

## Related Documentation

- [Management Stack Deployment](../../terraform/management-stack/README.md)
- [NPM Container Architecture](../../terraform/ansible/shared-roles/nginx_proxy_manager/README.md)
- [Infrastructure Overview](../README.md)