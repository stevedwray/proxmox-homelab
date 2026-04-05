# Portainer Management Infrastructure Deployment Plan

## Objective
Deploy a centralized Portainer management server in one LXC container, then deploy additional LXC containers with Portainer agents and automatically register them with the central Portainer instance using the Portainer API. This creates a centralized Docker container management platform across multiple LXC containers.

## Current Infrastructure State

### Available Resources
- **Proxmox Server**: pvetest.gibbsgreatly.xyz (validated and operational)
- **Working Template**: `local:vztmpl/debian-12-docker.tar.gz` (Docker + Portainer Agent pre-configured)
- **Network**: 192.168.1.x with static IP assignments
- **Terraform Provider**: `telmate/proxmox` v2.9.11 (confirmed working)
- **Authentication**: automation@pve user with Administrator role

### Recent Achievements Reference
- Single container deployment successful (container 101 at 192.168.1.60)
- Multi-container infrastructure deployment working
- Template creation via vzdump method validated
- Docker-in-LXC functionality confirmed

## Target Architecture

### Central Portainer Server
- **Role**: Main Portainer management interface
- **Components**: Portainer CE server, web UI, API endpoint
- **Network Access**: Web interface accessible on LAN (port 9000)
- **API Access**: REST API for agent management (port 9000)

### Portainer Agent Nodes
- **Count**: 3-5 additional LXC containers
- **Components**: Portainer Agent, Docker daemon
- **Function**: Managed nodes reporting to central server
- **Communication**: Agent connects to server on port 9001

### Expected Benefits
- **Centralized Management**: Single interface for all Docker containers across LXC nodes
- **API-Driven Operations**: Automated agent registration and management
- **Scalability**: Easy addition of new nodes via automation
- **Monitoring**: Centralized view of all container resources and status

## Technical Requirements

### Portainer Server Container
- **Resources**: 2GB RAM, 2 CPU cores, 10GB disk
- **Network**: Static IP (e.g., 192.168.1.70)
- **Services**: Portainer CE server (port 9000), Docker daemon
- **Volumes**: Data persistence for Portainer configuration

### Portainer Agent Containers
- **Resources**: 1GB RAM, 1 CPU core, 8GB disk per container
- **Network**: Static IP assignments (192.168.1.71-75)
- **Services**: Portainer Agent (port 9001), Docker daemon
- **Template**: Use existing debian-12-docker.tar.gz

### API Integration Requirements
- **Portainer API**: RESTful API for endpoint management
- **Authentication**: API key or admin credentials for automation
- **Endpoints**: Automatic agent registration via API calls
- **Configuration**: Environment variables for agent connection settings

## Implementation Approach

### Phase 1: Central Portainer Server Deployment
1. **Terraform**: Deploy LXC container for Portainer server
2. **Ansible**: Configure Portainer server with data persistence
3. **Validation**: Confirm web interface accessibility and API functionality
4. **Documentation**: API endpoints and authentication methods

### Phase 2: Agent Container Deployment
1. **Terraform**: Deploy multiple LXC containers with agent configuration
2. **Ansible**: Configure Portainer agents with server connection parameters
3. **API Integration**: Automated registration of agents with central server
4. **Testing**: Verify centralized container management functionality

### Phase 3: Management Workflow Testing
1. **Container Operations**: Deploy, scale, and manage containers via Portainer UI
2. **API Automation**: Script-based container management via Portainer API
3. **Monitoring**: Validate centralized logging and metrics collection
4. **Scaling**: Add/remove agent nodes dynamically

## Testing Scenarios

### Infrastructure Management
- Deploy containers across multiple LXC nodes via Portainer UI
- Scale services across multiple agents
- Monitor resource usage across the cluster
- Test failover scenarios with node unavailability

### API-Driven Operations
- Automated agent registration via API calls
- Programmatic container deployment across nodes
- Stack deployment spanning multiple agents
- Automated backup and restore of Portainer configuration

### Integration Testing
- Combine Terraform infrastructure deployment with Portainer management
- Ansible-based configuration with Portainer orchestration
- Mixed deployment scenarios (some containers via Portainer, some via docker-compose)

## Expected Deliverables

### Terraform Configurations
- **Portainer server module**: LXC container with server-specific configuration
- **Agent container module**: Reusable module for agent deployment
- **Network configuration**: Static IP management and port assignments
- **Variable definitions**: Flexible deployment parameters

### Ansible Playbooks
- **Portainer server setup**: Server installation, configuration, and data persistence
- **Agent configuration**: Agent installation with server connection parameters
- **API integration**: Automated agent registration and management
- **Service validation**: Health checks and connectivity testing

### API Integration Scripts
- **Agent registration**: Automated endpoint creation via Portainer API
- **Container management**: Script-based container operations
- **Monitoring integration**: API-based metrics collection
- **Backup automation**: Configuration and data backup procedures

## Success Criteria

### Functional Requirements
- [ ] Portainer server accessible via web interface on LAN
- [ ] Multiple agent containers deployed and registered automatically
- [ ] Centralized container management working across all agents
- [ ] API-driven agent registration functional
- [ ] Container deployment possible via Portainer UI across multiple nodes
- [ ] Resource monitoring and logging centralized

### Integration Requirements
- [ ] Terraform deployment of complete infrastructure working
- [ ] Ansible configuration management integrated with Portainer API
- [ ] Automated agent onboarding via API
- [ ] Mixed management scenarios (Portainer + direct Docker) working
- [ ] Backup and restore procedures for Portainer configuration

### Scalability Testing
- [ ] Dynamic addition of new agent nodes
- [ ] Load balancing containers across multiple agents
- [ ] Resource constraint handling and scheduling
- [ ] Network communication between agents reliable

## Risk Considerations

### Technical Challenges
- **API Authentication**: Portainer API key management and rotation
- **Network Communication**: Agent-to-server connectivity in LXC environment
- **Data Persistence**: Portainer configuration and data backup
- **Version Compatibility**: Portainer server/agent version alignment

### Mitigation Strategies
- **Template Validation**: Existing template already includes Portainer Agent
- **Network Testing**: Validate connectivity at each deployment step
- **API Documentation**: Comprehensive API integration examples
- **Incremental Deployment**: Start with single agent, expand gradually

This plan builds on your successful Sock Shop deployment experience while introducing centralized container management capabilities that will be valuable for larger-scale infrastructure automation.
