# Centralized Portainer Management Methodology

## Project Overview

Deploy a central Portainer server in an LXC container, then use Portainer's API to manage multiple agent nodes and deploy container stacks across your infrastructure.

## Phase 1: Central Portainer Server Deployment

### 1.1 Terraform Configuration

Create `terraform/portainer-central/main.tf`:

```hcl
terraform {
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "2.9.11"
    }
  }
}

provider "proxmox" {
  pm_api_url      = var.proxmox_api_url
  pm_user         = var.proxmox_user
  pm_password     = var.proxmox_password
  pm_tls_insecure = true
}

resource "proxmox_lxc" "portainer_server" {
  target_node = "pvetest"
  hostname    = "portainer-server"

  ostemplate   = "local:vztmpl/debian-12-docker.tar.gz"
  ostype       = "debian"
  password     = var.lxc_password
  unprivileged = true
  onboot       = true
  start        = true

  cores  = 2
  memory = 3072
  swap   = 1024

  features {
    nesting = true
  }

  rootfs {
    storage = "local-zfs"
    size    = "15G"
  }

  network {
    name   = "eth0"
    bridge = "vmbr0"
    ip     = "192.168.1.70/24"
    gw     = "192.168.1.1"
  }

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags = "portainer,server,management"
}

output "portainer_server_ip" {
  value = "192.168.1.70"
}
```

### 1.2 Ansible Server Configuration

Create `ansible/portainer/deploy-server.yml`:

```yaml
---
- name: Deploy Portainer Server
  hosts: portainer_server
  become: yes
  vars:
    portainer_data_dir: /opt/portainer/data
    portainer_version: "2.21.1"

  tasks:
    - name: Create portainer directories
      file:
        path: "{{ item }}"
        state: directory
        owner: root
        group: root
        mode: '0755'
      loop:
        - /opt/portainer
        - "{{ portainer_data_dir }}"

    - name: Create Portainer Server docker-compose
      copy:
        content: |
          version: '3.8'
          services:
            portainer:
              image: portainer/portainer-ce:{{ portainer_version }}
              container_name: portainer-server
              restart: unless-stopped
              ports:
                - "9000:9000"
                - "9443:9443"
                - "8000:8000"
              volumes:
                - {{ portainer_data_dir }}:/data
                - /var/run/docker.sock:/var/run/docker.sock
              environment:
                - PORTAINER_ADMIN_PASSWORD_HASH={{ portainer_admin_hash | default('') }}
              command: --admin-password='{{ portainer_admin_password | default("admin123") }}'
              networks:
                - portainer-net
              logging:
                driver: "json-file"
                options:
                  max-size: "10m"
                  max-file: "3"

          networks:
            portainer-net:
              external: false
        dest: /opt/portainer/docker-compose.yml

    - name: Start Portainer server
      shell: |
        cd /opt/portainer
        docker-compose up -d
      register: portainer_start

    - name: Wait for Portainer to be ready
      uri:
        url: "http://192.168.1.70:9000/api/status"
        method: GET
        timeout: 10
      register: portainer_status
      until: portainer_status.status == 200
      retries: 30
      delay: 10

    - name: Display Portainer access info
      debug:
        msg: |
          Portainer Server deployed successfully!
          Web Interface: http://192.168.1.70:9000
          Username: admin
          Password: {{ portainer_admin_password | default("admin123") }}
          API Endpoint: http://192.168.1.70:9000/api
```

## Phase 2: API Connectivity and Agent Management

### 2.1 Initial API Testing Script

Create `scripts/portainer-api-test.sh`:

```bash
#!/bin/bash
set -e

PORTAINER_URL="http://192.168.1.70:9000"
PORTAINER_USER="admin"
PORTAINER_PASS="admin123"

echo "=== Testing Portainer API Connectivity ==="

# Function to get auth token
get_auth_token() {
    local response=$(curl -s -X POST \
        "${PORTAINER_URL}/api/auth" \
        -H "Content-Type: application/json" \
        -d "{\"Username\":\"${PORTAINER_USER}\",\"Password\":\"${PORTAINER_PASS}\"}")

    echo $response | jq -r '.jwt' 2>/dev/null || {
        echo "Failed to get auth token. Response: $response"
        exit 1
    }
}

# Function to list endpoints
list_endpoints() {
    local token=$1
    curl -s -X GET \
        "${PORTAINER_URL}/api/endpoints" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" | jq .
}

# Function to add agent endpoint
add_agent_endpoint() {
    local token=$1
    local name=$2
    local url=$3

    curl -s -X POST \
        "${PORTAINER_URL}/api/endpoints" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "{
            \"Name\": \"${name}\",
            \"URL\": \"${url}\",
            \"EndpointCreationType\": 2,
            \"PublicURL\": \"${url}\"
        }" | jq .
}

# Test connectivity
echo "Getting authentication token..."
TOKEN=$(get_auth_token)
echo "Token obtained: ${TOKEN:0:20}..."

echo "Listing current endpoints..."
list_endpoints $TOKEN

echo "API connectivity test completed successfully!"
```

### 2.2 Agent Container Deployment

Create `terraform/portainer-agents/main.tf`:

```hcl
terraform {
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "2.9.11"
    }
  }
}

provider "proxmox" {
  pm_api_url      = var.proxmox_api_url
  pm_user         = var.proxmox_user
  pm_password     = var.proxmox_password
  pm_tls_insecure = true
}

resource "proxmox_lxc" "portainer_agents" {
  count = var.agent_count

  target_node = "pvetest"
  hostname    = "portainer-agent-${count.index + 1}"

  ostemplate   = "local:vztmpl/debian-12-docker.tar.gz"
  ostype       = "debian"
  password     = var.lxc_password
  unprivileged = true
  onboot       = true
  start        = true

  cores  = 1
  memory = 1536
  swap   = 512

  features {
    nesting = true
  }

  rootfs {
    storage = "local-zfs"
    size    = "10G"
  }

  network {
    name   = "eth0"
    bridge = "vmbr0"
    ip     = "192.168.1.${71 + count.index}/24"
    gw     = "192.168.1.1"
  }

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags = "portainer,agent,node-${count.index + 1}"
}

output "agent_ips" {
  value = [for i in range(var.agent_count) : "192.168.1.${71 + i}"]
}
```

### 2.3 Agent Registration Script

Create `scripts/register-agents.sh`:

```bash
#!/bin/bash
set -e

PORTAINER_URL="http://192.168.1.70:9000"
PORTAINER_USER="admin"
PORTAINER_PASS="admin123"

# Agent IPs (from Terraform output)
AGENT_IPS=("192.168.1.71" "192.168.1.72" "192.168.1.73")

# Get authentication token
get_auth_token() {
    curl -s -X POST \
        "${PORTAINER_URL}/api/auth" \
        -H "Content-Type: application/json" \
        -d "{\"Username\":\"${PORTAINER_USER}\",\"Password\":\"${PORTAINER_PASS}\"}" | \
        jq -r '.jwt'
}

# Register agent endpoint
register_agent() {
    local token=$1
    local agent_name=$2
    local agent_ip=$3
    local agent_url="http://${agent_ip}:9001"

    echo "Registering agent: $agent_name at $agent_url"

    response=$(curl -s -X POST \
        "${PORTAINER_URL}/api/endpoints" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "{
            \"Name\": \"${agent_name}\",
            \"URL\": \"${agent_url}\",
            \"EndpointCreationType\": 2,
            \"PublicURL\": \"${agent_url}\"
        }")

    echo "Response: $response" | jq .
}

# Wait for agent to be ready
wait_for_agent() {
    local agent_ip=$1
    local max_attempts=30
    local attempt=1

    echo "Waiting for agent at $agent_ip to be ready..."

    while [ $attempt -le $max_attempts ]; do
        if curl -s --connect-timeout 5 "http://${agent_ip}:9001" >/dev/null 2>&1; then
            echo "Agent at $agent_ip is ready!"
            return 0
        fi
        echo "Attempt $attempt/$max_attempts - Agent not ready, waiting..."
        sleep 10
        ((attempt++))
    done

    echo "Agent at $agent_ip failed to become ready"
    return 1
}

# Main execution
echo "=== Registering Portainer Agents ==="

TOKEN=$(get_auth_token)
echo "Authentication successful"

for i in "${!AGENT_IPS[@]}"; do
    agent_ip="${AGENT_IPS[$i]}"
    agent_name="portainer-agent-$((i + 1))"

    echo "Processing $agent_name ($agent_ip)..."

    if wait_for_agent "$agent_ip"; then
        register_agent "$TOKEN" "$agent_name" "$agent_ip"
    else
        echo "Skipping registration for $agent_name - agent not ready"
    fi

    echo "---"
done

echo "Agent registration process completed!"
```

## Phase 3: Docker Stack Deployment via API

### 3.1 Stack Management Functions

Create `scripts/portainer-stack-manager.sh`:

```bash
#!/bin/bash
set -e

PORTAINER_URL="http://192.168.1.70:9000"
PORTAINER_USER="admin"
PORTAINER_PASS="admin123"

# Get authentication token
get_auth_token() {
    curl -s -X POST \
        "${PORTAINER_URL}/api/auth" \
        -H "Content-Type: application/json" \
        -d "{\"Username\":\"${PORTAINER_USER}\",\"Password\":\"${PORTAINER_PASS}\"}" | \
        jq -r '.jwt'
}

# Get endpoint ID by name
get_endpoint_id() {
    local token=$1
    local endpoint_name=$2

    curl -s -X GET \
        "${PORTAINER_URL}/api/endpoints" \
        -H "Authorization: Bearer ${token}" | \
        jq -r ".[] | select(.Name == \"${endpoint_name}\") | .Id"
}

# Deploy stack to endpoint
deploy_stack() {
    local token=$1
    local endpoint_id=$2
    local stack_name=$3
    local compose_file=$4

    echo "Deploying stack '$stack_name' to endpoint ID $endpoint_id"

    # Read compose file content
    local compose_content
    if [ -f "$compose_file" ]; then
        compose_content=$(cat "$compose_file")
    else
        echo "Compose file not found: $compose_file"
        return 1
    fi

    # Deploy stack
    response=$(curl -s -X POST \
        "${PORTAINER_URL}/api/stacks?type=2&method=string&endpointId=${endpoint_id}" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "{
            \"Name\": \"${stack_name}\",
            \"StackFileContent\": $(echo "$compose_content" | jq -Rs .)
        }")

    echo "Stack deployment response:"
    echo "$response" | jq .
}

# List stacks on endpoint
list_stacks() {
    local token=$1
    local endpoint_id=$2

    curl -s -X GET \
        "${PORTAINER_URL}/api/stacks" \
        -H "Authorization: Bearer ${token}" | \
        jq ".[] | select(.EndpointId == $endpoint_id)"
}

# Usage function
usage() {
    echo "Usage: $0 {deploy|list} [options]"
    echo ""
    echo "Commands:"
    echo "  deploy <endpoint_name> <stack_name> <compose_file>"
    echo "  list <endpoint_name>"
    echo ""
    echo "Examples:"
    echo "  $0 deploy portainer-agent-1 webapp docker-compose.yml"
    echo "  $0 list portainer-agent-1"
}

# Main execution
case "$1" in
    deploy)
        if [ $# -ne 4 ]; then
            usage
            exit 1
        fi

        TOKEN=$(get_auth_token)
        ENDPOINT_ID=$(get_endpoint_id "$TOKEN" "$2")

        if [ -z "$ENDPOINT_ID" ] || [ "$ENDPOINT_ID" = "null" ]; then
            echo "Endpoint '$2' not found"
            exit 1
        fi

        deploy_stack "$TOKEN" "$ENDPOINT_ID" "$3" "$4"
        ;;
    list)
        if [ $# -ne 2 ]; then
            usage
            exit 1
        fi

        TOKEN=$(get_auth_token)
        ENDPOINT_ID=$(get_endpoint_id "$TOKEN" "$2")

        if [ -z "$ENDPOINT_ID" ] || [ "$ENDPOINT_ID" = "null" ]; then
            echo "Endpoint '$2' not found"
            exit 1
        fi

        list_stacks "$TOKEN" "$ENDPOINT_ID"
        ;;
    *)
        usage
        exit 1
        ;;
esac
```

### 3.2 Example Stack Templates

Create `stacks/nginx-example.yml`:

```yaml
version: '3.8'
services:
  nginx:
    image: nginx:alpine
    container_name: nginx-web
    restart: unless-stopped
    ports:
      - "8080:80"
    volumes:
      - nginx-data:/usr/share/nginx/html
    environment:
      - NGINX_HOST=localhost
      - NGINX_PORT=80
    networks:
      - web-network
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  nginx-data:

networks:
  web-network:
    external: false
```

## Phase 4: Advanced Automation Integration

### 4.1 Ansible Stack Deployment Playbook

Create `ansible/portainer/deploy-stacks.yml`:

```yaml
---
- name: Deploy stacks via Portainer API
  hosts: localhost
  vars:
    portainer_url: "http://192.168.1.70:9000"
    portainer_user: "admin"
    portainer_password: "admin123"
    stack_deployments:
      - endpoint: "portainer-agent-1"
        stack_name: "nginx-web"
        compose_file: "stacks/nginx-example.yml"
      - endpoint: "portainer-agent-2"
        stack_name: "monitoring"
        compose_file: "stacks/prometheus-stack.yml"

  tasks:
    - name: Get Portainer authentication token
      uri:
        url: "{{ portainer_url }}/api/auth"
        method: POST
        body_format: json
        body:
          Username: "{{ portainer_user }}"
          Password: "{{ portainer_password }}"
      register: auth_response

    - name: Set authentication token
      set_fact:
        portainer_token: "{{ auth_response.json.jwt }}"

    - name: Get all endpoints
      uri:
        url: "{{ portainer_url }}/api/endpoints"
        method: GET
        headers:
          Authorization: "Bearer {{ portainer_token }}"
      register: endpoints_response

    - name: Deploy stacks
      uri:
        url: "{{ portainer_url }}/api/stacks?type=2&method=string&endpointId={{ endpoint_id }}"
        method: POST
        headers:
          Authorization: "Bearer {{ portainer_token }}"
        body_format: json
        body:
          Name: "{{ item.stack_name }}"
          StackFileContent: "{{ lookup('file', item.compose_file) }}"
      vars:
        endpoint_id: "{{ endpoints_response.json | selectattr('Name', 'equalto', item.endpoint) | map(attribute='Id') | first }}"
      loop: "{{ stack_deployments }}"
      register: stack_results

    - name: Display deployment results
      debug:
        msg: "Stack '{{ item.item.stack_name }}' deployed to '{{ item.item.endpoint }}': {{ item.json.Id if item.json.Id is defined else 'Failed' }}"
      loop: "{{ stack_results.results }}"
```

## Usage Workflow

### Initial Setup
1. Deploy Portainer server: `terraform apply` in `portainer-central/`
2. Configure server: `ansible-playbook deploy-server.yml`
3. Test API: `./scripts/portainer-api-test.sh`

### Agent Management
1. Deploy agents: `terraform apply` in `portainer-agents/`
2. Register agents: `./scripts/register-agents.sh`
3. Verify in Portainer UI at `http://192.168.1.70:9000`

### Stack Deployment
1. Manual: `./scripts/portainer-stack-manager.sh deploy agent-1 webapp docker-compose.yml`
2. Automated: `ansible-playbook deploy-stacks.yml`

## Key Benefits

- **Centralized Management**: Single interface for all container operations
- **API-Driven**: Fully scriptable and automatable
- **Scalable**: Easy addition of new agents
- **Integrated**: Works with existing Terraform/Ansible workflow
- **Flexible**: Mix of UI and API management options
