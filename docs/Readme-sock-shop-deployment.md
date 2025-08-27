# File: README-sock-shop-deployment.md
# Sock Shop Microservices Deployment

This deployment demonstrates multi-container orchestration using your existing Proxmox infrastructure with LXC template 901. It provides two approaches: Terraform + Ansible (recommended) and Terraform-only, each testing different aspects of infrastructure automation.

## Prerequisites

- Proxmox VE 9.0.3 with validated API access
- LXC template 901 (enhanced template with Docker support)
- Terraform and Ansible installed and configured
- SSH key access to Proxmox server
- Available IP range: 192.168.1.60-73

## Quick Start

```bash
# Make deployment script executable
chmod +x scripts/deploy-sock-shop.sh

# Deploy single container with Terraform + Ansible
./scripts/deploy-sock-shop.sh terraform-ansible single

# Check deployment status
./scripts/health-check.sh

# Access the application
open http://192.168.1.60
```

## Deployment Approaches

### 1. Terraform + Ansible (Recommended)

This approach separates infrastructure provisioning from application deployment, following DevOps best practices.

**IP Range**: 192.168.1.60-67

**Structure**:
- **Terraform**: Provisions LXC containers from template 901
- **Ansible**: Configures containers and deploys Docker services
- **Benefits**: Clear separation of concerns, easier troubleshooting

**Files**:
- `terraform/sock-shop/single-container/` - Single container test
- `terraform/sock-shop/multi-container/` - 3-container communication test
- `terraform/sock-shop/full-stack/` - Complete 8-container deployment
- `ansible/sock-shop/` - Application deployment playbooks

### 2. Terraform-Only

This approach uses Terraform for both infrastructure and application deployment, testing Terraform's configuration management capabilities.

**IP Range**: 192.168.1.70-73

**Structure**:
- **Terraform**: Provisions containers AND deploys applications
- **Scripts**: Embedded shell scripts for application deployment
- **Benefits**: Single-tool workflow, everything in infrastructure as code

**Files**:
- `terraform/sock-shop/terraform-only/` - Complete Terraform-only deployment

## Deployment Phases

### Phase 1: Single Container
Tests basic container deployment and Docker functionality.

```bash
./scripts/deploy-sock-shop.sh terraform-ansible single
```

**What it deploys**:
- 1 LXC container (192.168.1.60)
- Frontend service with mock catalogue
- Tests Docker-in-LXC functionality

### Phase 2: Multi-Container Communication
Tests inter-container service communication.

```bash
./scripts/deploy-sock-shop.sh terraform-ansible multi
```

**What it deploys**:
- Frontend container (192.168.1.60)
- Database container (192.168.1.61) - MongoDB, MySQL, Redis
- User service container (192.168.1.62)
- Tests service discovery and networking

### Phase 3: Full Microservices Stack
Deploys complete Sock Shop application with all services.

```bash
./scripts/deploy-sock-shop.sh terraform-ansible full
```

**What it deploys**:
- 8 LXC containers with 14+ microservices
- Complete e-commerce application
- Inter-service communication
- Message queuing with RabbitMQ
- Multiple databases

## Service Architecture

### Services and Ports
- **Frontend**: Port 80 (web interface)
- **User Service**: Internal (user management)
- **Catalogue Service**: Internal (product catalog)
- **Carts Service**: Internal (shopping cart)
- **Orders Service**: Internal (order processing)
- **Payment Service**: Internal (payment processing)
- **Shipping Service**: Internal (shipping calculation)
- **RabbitMQ Management**: Port 15672 (admin/admin)

### Data Stores
- **MongoDB**: Catalogue, Orders, Carts data
- **MySQL**: User data
- **Redis**: Session storage

## File Structure

```
terraform/sock-shop/
├── single-container/
│   ├── main.tf
│   └── variables.tf
├── multi-container/
│   ├── main.tf
│   └── variables.tf
├── full-stack/
│   ├── main.tf
│   └── variables.tf
└── terraform-only/
    ├── main.tf
    ├── variables.tf
    └── scripts/
        ├── deploy-database.sh
        ├── deploy-frontend.sh
        ├── deploy-user.sh
        └── deploy-catalogue.sh

ansible/
├── inventory/
│   └── sock-shop.yml
└── sock-shop/
    ├── deploy-frontend.yml
    ├── deploy-multi-container.yml
    └── deploy-complete.yml

scripts/
├── deploy-sock-shop.sh
└── health-check.sh
```

## Manual Deployment Commands

### Terraform + Ansible Single Container
```bash
# Deploy infrastructure
cd terraform/sock-shop/single-container
terraform init && terraform apply -auto-approve

# Wait and deploy application
sleep 60
cd ../../../ansible
ansible-playbook -i inventory/sock-shop.yml sock-shop/deploy-frontend.yml
```

### Terraform + Ansible Full Stack
```bash
# Deploy infrastructure
cd terraform/sock-shop/full-stack
terraform init && terraform apply -auto-approve

# Wait and deploy applications
sleep 120
cd ../../../ansible
ansible-playbook -i inventory/sock-shop.yml sock-shop/deploy-complete.yml
```

### Terraform-Only Deployment
```bash
cd terraform/sock-shop/terraform-only
terraform init && terraform apply -auto-approve
```

## Validation and Testing

### Health Check Script
```bash
./scripts/health-check.sh
```

The health check validates:
- Container reachability (ping tests)
- Web service responses
- Docker container status
- Service endpoints

### Manual Testing Commands
```bash
# Test frontend response
curl http://192.168.1.60

# Check container Docker status
ssh root@192.168.1.60 "docker ps"

# View container logs
ssh root@192.168.1.60 "docker logs front-end"

# Test service communication
ssh root@192.168.1.60 "docker exec front-end curl -s http://catalogue:80/catalogue"
```

### Expected Results
- **Single Container**: Basic web interface accessible
- **Multi-Container**: User registration/login functional
- **Full Stack**: Complete e-commerce workflow (browse, add to cart, checkout)

## Cleanup

### Automated Cleanup
```bash
# Clean up any deployment
./scripts/deploy-sock-shop.sh cleanup terraform-ansible full
./scripts/deploy-sock-shop.sh cleanup terraform-only
```

### Manual Cleanup
```bash
# From appropriate terraform directory
terraform destroy -auto-approve
```

## Troubleshooting

### Common Issues

**Container Not Starting**
```bash
# Check Proxmox container status
ssh root@pvetest.gibbsgreatly.xyz "pct status <container-id>"

# Check container logs
ssh root@pvetest.gibbsgreatly.xyz "pct exec <container-id> -- journalctl -u docker"
```

**SSH Connection Issues**
```bash
# Regenerate SSH keys manually
ssh root@192.168.1.60 "ssh-keygen -A && systemctl restart ssh"
```

**Docker Service Issues**
```bash
# Restart Docker service
ssh root@192.168.1.60 "systemctl restart docker"

# Check Docker network
ssh root@192.168.1.60 "docker network ls"
```

**Template Issues**
```bash
# Verify template exists
ssh root@pvetest.gibbsgreatly.xyz "pct list | grep template"

# Check available templates
ssh root@pvetest.gibbsgreatly.xyz "pveam list local"
```

### Debug Commands
```bash
# Container system info
ssh root@192.168.1.60 "container-info"

# Security scan
ssh root@192.168.1.60 "security-scan"

# Docker network inspection
ssh root@192.168.1.60 "docker network inspect sock-shop"
```

## Success Criteria

### Functional Requirements
- [ ] Multiple LXC containers deployed and running
- [ ] Docker services running within containers
- [ ] Inter-container service communication working
- [ ] Web interface accessible from LAN
- [ ] Data persistence across container restarts
- [ ] Service discovery and networking functional

### Testing Requirements
- [ ] Terraform-only deployment working end-to-end
- [ ] Terraform+Ansible deployment working end-to-end
- [ ] Container lifecycle management tested
- [ ] Service scaling capabilities demonstrated
- [ ] Monitoring integration validated
- [ ] Recovery from failure scenarios tested

## Integration with Existing Infrastructure

This deployment leverages your existing:
- **Template 901**: Enhanced LXC template with Docker, security tools, monitoring
- **Directory Structure**: Uses /data, /config, /logs from template
- **Monitoring**: Prometheus Node Exporter available on port 9100
- **Security**: UFW firewall, fail2ban, automatic updates pre-configured
- **Networking**: Uses existing vmbr0 bridge and DHCP configuration

The deployment validates both your infrastructure automation approaches while demonstrating real-world microservices architecture patterns.
