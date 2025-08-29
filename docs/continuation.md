docs/project-status-summary.md
docs/phase4-testing-validation/proxmox-server-baseline.md
docs/phase4-testing-validation/lxc-template-creation.md
ansible/inventory/test-lab.yml
ansible/01-base-system/build-lxc-template.yml
ansible/01-base-system/enhance-lxc-template.yml
terraform/environments/test-vm/main.tf
terraform/environments/test-vm/variables.tf


I need help deploying a multi-container test stack using my existing Proxmox infrastructure. I have:

- Working Proxmox VE 9.0.3 server with validated API access
- LXC templates with Docker support (templates 900/901)
- Terraform and Ansible automation working
- All validation checks passing

I want to deploy the Sock Shop microservices demo application to test both:
1. Terraform + Ansible workflow
2. Terraform-only workflow

The goal is multiple containers communicating with each other, with a web service accessible on my LAN.

I'm attaching my current project documentation and the detailed deployment plan. Please review the infrastructure status and provide specific implementation steps for both deployment approaches.

Key constraints:
- Must use existing LXC templates (preferably 901 enhanced template)
- Target IP range: 192.168.1.x
- Docker containers running inside LXC containers
- Need LAN-accessible web interface for testing


# Deployment Plan: LXC Container Stack with Sock Shop Microservices

## Objective
Deploy and configure LXC containers from existing templates, then set up the Sock Shop microservices demo application to test both Terraform-only and Terraform+Ansible deployment workflows. The goal is to demonstrate multi-container communication with a service accessible on the LAN.

## Current Infrastructure State

### Available Resources
- **Proxmox Server**: pvetest.gibbsgreatly.xyz (fully validated and operational)
- **LXC Templates**:
  - Template 900: Base template with Docker support
  - Template 901: Enhanced template with security tools, monitoring (Prometheus Node Exporter), standardized directories
- **Storage Pools**: local-zfs (primary), others available via pvesm status
- **Network Bridges**: vmbr0 (primary), others available
- **IP Range**: 192.168.1.x network with DHCP available
- **Authentication**: automation@pve user with API access, automation system user with SSH keys

### Current Automation Status
- **Terraform**: Configured and validated with Proxmox provider
- **Ansible**: Working inventory, can deploy to both Proxmox host and LXC containers
- **API Access**: Ticket-based authentication working
- **Templates**: Docker-enabled containers ready for deployment

## Target Application: Sock Shop Microservices Demo

### Why Sock Shop
- **Real microservices architecture**: ~14 services with actual inter-service communication
- **Multiple technologies**: Node.js frontend, Go/Java services, MongoDB, RabbitMQ
- **LAN-accessible service**: Web interface on port 80/8080
- **Container-native**: Designed for Docker deployment
- **Well-documented**: Multiple deployment examples available
- **Testing complexity**: Sufficient to validate both simple and complex automation scenarios

### Architecture Overview
Services include: frontend, user management, catalog, cart, payment, orders, shipping, multiple databases
- **Frontend**: Node.js web application (LAN accessible)
- **Backend Services**: Go and Java microservices
- **Data Layer**: MongoDB, MySQL databases
- **Message Queue**: RabbitMQ for order processing
- **Load Balancer**: NGINX (in some configurations)

## Deployment Approaches to Test

### Approach 1: Terraform + Ansible (Recommended Primary)
1. **Terraform**: Deploy LXC containers from templates
2. **Ansible**: Configure containers and deploy application stack
3. **Benefits**: Separation of concerns, infrastructure vs configuration management
4. **Test Cases**:
   - Container lifecycle management
   - Service discovery and networking
   - Configuration management at scale

### Approach 2: Terraform Only
1. **Terraform**: Deploy containers and configure applications entirely through Terraform
2. **Benefits**: Single tool workflow, infrastructure as code
3. **Test Cases**:
   - Terraform's configuration management capabilities
   - Resource dependencies and ordering
   - State management complexity

## Implementation Plan

### Phase 1: Single Container Deployment
1. **Deploy one LXC container** from template 901 (enhanced)
2. **Verify networking** and SSH access
3. **Test Docker functionality** within the container
4. **Deploy simple application** (e.g., nginx) to validate LAN access

### Phase 2: Multi-Container Communication Test
1. **Deploy 2-3 containers** for basic stack (frontend, API, database)
2. **Configure container networking** for inter-container communication
3. **Test service discovery** between containers
4. **Validate data persistence** across container restarts

### Phase 3: Full Sock Shop Deployment
1. **Deploy complete microservices stack** (~6-8 core services initially)
2. **Configure all service dependencies** and communication
3. **Test end-to-end functionality** through web interface
4. **Validate monitoring** and logging capabilities

## Technical Requirements

### Container Specifications
- **Base Template**: Use template 901 (enhanced with Docker, monitoring)
- **Resource Allocation**: 2GB RAM, 2 CPU cores per container (adjust based on service needs)
- **Storage**: 8-20GB disk per container depending on service
- **Networking**: Bridge networking with DHCP, static IPs where needed

### Network Configuration
- **Container Network**: Use existing vmbr0 bridge
- **IP Assignment**: DHCP for initial deployment, consider static for production services
- **Port Mapping**: Map service ports to host for LAN accessibility
- **Service Discovery**: Use Docker networks and/or DNS resolution

### Security Considerations
- **Container Isolation**: Proper LXC security boundaries
- **Network Segmentation**: Consider VLAN separation if available
- **Service Authentication**: Secure inter-service communication
- **Monitoring**: Leverage existing Node Exporter in template 901

## Expected Deliverables

### Terraform Configurations
- **Container deployment modules** for different service types
- **Network configuration** for inter-container communication
- **Variable definitions** for flexible deployment
- **Output values** for service endpoints and IPs

### Ansible Playbooks
- **Container configuration** playbooks
- **Application deployment** playbooks
- **Service configuration** and orchestration
- **Monitoring and maintenance** tasks

### Documentation
- **Deployment procedures** for both approaches
- **Network architecture** documentation
- **Service interaction** diagrams
- **Troubleshooting guides** for common issues

## Success Criteria

### Functional Requirements
- [ ] Multiple LXC containers deployed and running
- [ ] Docker services running within containers
- [ ] Inter-container service communication working
- [ ] Web interface accessible from LAN (192.168.1.x network)
- [ ] Data persistence across container restarts
- [ ] Service discovery and networking functional

### Testing Requirements
- [ ] Terraform-only deployment working end-to-end
- [ ] Terraform+Ansible deployment working end-to-end
- [ ] Container lifecycle management (start, stop, restart, destroy)
- [ ] Service scaling capabilities demonstrated
- [ ] Monitoring and logging integration validated
- [ ] Recovery from failure scenarios tested

## Risk Mitigation

### Known Challenges
- **Docker in LXC**: Potential networking or permission issues
- **Service Dependencies**: Complex startup ordering requirements
- **Resource Constraints**: VM resource limitations in test environment
- **Network Complexity**: Multi-container communication setup

### Mitigation Strategies
- **Template Validation**: Templates already configured for Docker in LXC
- **Incremental Deployment**: Start simple, add complexity gradually
- **Resource Monitoring**: Use existing monitoring capabilities
- **Network Testing**: Validate connectivity at each step

## Context for AI Assistant

You have access to working Proxmox infrastructure with validated LXC templates that include Docker support. The templates include standardized directory structures (/data, /config, /logs) and monitoring capabilities. The infrastructure automation (Terraform/Ansible) is working and validated.

Focus on practical implementation of the Sock Shop deployment using the existing templates and infrastructure. Provide specific configurations for both deployment approaches, considering the constraints of the LXC environment while leveraging the existing Docker capabilities.
