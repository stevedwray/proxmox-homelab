# Complete Guide to Portainer Server & Agent API Control

## Overview

This guide documents a working proof of concept for controlling Portainer server and agent infrastructure entirely via API calls, enabling full automation through tools like Ansible, Terraform, or CI/CD pipelines.

## Architecture

```
Proxmox Host (192.168.1.2)
├── LXC Container 102 (192.168.1.70) - Portainer Server
│   └── Docker Container: Portainer CE (:9000, :9443)
└── LXC Container 103 (192.168.1.71) - Portainer Agent
    └── Docker Container: Portainer Agent (:9001)
```

## Infrastructure Setup

### LXC Container Creation

```bash
# Create Portainer Server container
pct create 102 local:vztmpl/debian-12-docker.tar.gz \
  --hostname portainer-server \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.1.70/24,gw=192.168.1.1 \
  --memory 3072 \
  --cores 2 \
  --rootfs local-zfs:15 \
  --unprivileged 1 \
  --features nesting=1 \
  --onboot 1 \
  --start

# Create Portainer Agent container
pct create 103 local:vztmpl/debian-12-docker.tar.gz \
  --hostname portainer-agent \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.1.71/24,gw=192.168.1.1 \
  --memory 1024 \
  --cores 1 \
  --rootfs local-zfs:8 \
  --unprivileged 1 \
  --features nesting=1 \
  --onboot 1 \
  --start
```

### Portainer Server Deployment

```bash
# SSH into server container
ssh root@192.168.1.70

# Create persistent volume
docker volume create portainer_data

# Deploy Portainer server with TLS skip verification
docker run -d \
  --name portainer \
  --restart unless-stopped \
  -p 9000:9000 \
  -p 9443:9443 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest --tlsskipverify
```

**Critical Notes:**
- The `--tlsskipverify` flag is a Portainer server argument, not a Docker flag
- It goes after the image name as a command parameter
- This enables the server to accept agent connections with certificate issues

### Portainer Agent Deployment

```bash
# SSH into agent container
ssh root@192.168.1.71

# Deploy Portainer agent
docker run -d \
  --name portainer-agent \
  --restart unless-stopped \
  -p 9001:9001 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/lib/docker/volumes:/var/lib/docker/volumes \
  portainer/agent:latest
```

**Critical Notes:**
- The agent ALWAYS runs with TLS enabled (`use_tls=true` in logs)
- There is no way to disable TLS on the agent
- Agent certificates are automatically generated for container internal IPs

## API Authentication

### Get Authentication Token

```bash
# Authenticate with Portainer server
TOKEN=$(curl -s -X POST http://192.168.1.70:9000/api/auth \
  -H "Content-Type: application/json" \
  -d '{"Username":"admin","Password":"YOUR_PASSWORD"}' | jq -r '.jwt')

# Verify token is valid
echo "Token: $TOKEN"
```

## Agent Registration via API

### The Critical Discovery

**GOTCHA**: Agent registration via API requires **form data**, not JSON payload.

```bash
# WRONG - This fails with "Invalid environment name"
curl -X POST http://192.168.1.70:9000/api/endpoints \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"Name":"agent1","EndpointCreationType":2,"URL":"tcp://192.168.1.71:9001"}'

# CORRECT - Use form data with -F flags
curl -s -X POST http://192.168.1.70:9000/api/endpoints \
  -H "Authorization: Bearer $TOKEN" \
  -F "Name=agent02" \
  -F "URL=tcp://192.168.1.71:9001" \
  -F "EndpointCreationType=2" \
  -F "TLS=true" \
  -F "TLSSkipVerify=true" \
  -F "TLSSkipClientVerify=true"
```

### Required Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Name | String (alphanumeric) | Environment name |
| URL | `tcp://IP:9001` | Agent connection URL |
| EndpointCreationType | `2` | Agent type (1=Docker API, 2=Agent) |
| TLS | `true` | Agent always uses TLS |
| TLSSkipVerify | `true` | Skip certificate validation |
| TLSSkipClientVerify | `true` | Skip client certificate validation |

### Certificate Issues

**The Problem**: Agent certificates are valid for container internal IPs (e.g., 172.17.0.2) but we connect via host IPs (192.168.1.71).

**Symptoms**:
```
tls: failed to verify certificate: x509: certificate is valid for 172.17.0.2, not 192.168.1.71
```

**Solution**: Use `TLSSkipVerify=true` and `TLSSkipClientVerify=true` in API registration.

### Successful Response

```json
{
  "Id": 6,
  "Name": "agent02",
  "Type": 2,
  "URL": "tcp://192.168.1.71:9001",
  "GroupId": 1,
  "TLSConfig": {
    "TLS": true,
    "TLSSkipVerify": true
  },
  "Status": 1
}
```

Note the `Id` field - this becomes the `endpointId` for stack operations.

## Stack Deployment via API

### The Critical Discovery

**GOTCHA**: Stack deployment requires a completely different API endpoint structure than documented.

```bash
# WRONG - Returns 405 Method Not Allowed
curl -X POST "http://192.168.1.70:9000/api/stacks?type=2&method=string&endpointId=6"

# WRONG - Also returns 405 Method Not Allowed
curl -X POST "http://192.168.1.70:9000/api/stacks"

# CORRECT - Must use the full create path
curl -X POST "http://192.168.1.70:9000/api/stacks/create/standalone/string?endpointId=6"
```

### Working Stack Deployment

```bash
# Deploy stack via API
curl -s -X POST "http://192.168.1.70:9000/api/stacks/create/standalone/string?endpointId=6" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "method": "string",
    "type": "standalone",
    "Name": "api-test",
    "StackFileContent": "version: '\''3.8'\''\nservices:\n  nginx:\n    image: nginx:alpine\n    ports:\n      - \"8082:80\"\n    restart: unless-stopped\n  whoami:\n    image: traefik/whoami\n    ports:\n      - \"8083:80\"\n    restart: unless-stopped",
    "Env": []
  }'
```

### Required JSON Structure

```json
{
  "method": "string",
  "type": "standalone",
  "Name": "stack-name",
  "StackFileContent": "docker-compose content as string",
  "Env": []
}
```

**Critical Notes**:
- `StackFileContent` must contain the entire docker-compose.yml as an escaped string
- `Env` array can contain environment variable objects
- `method: "string"` indicates compose content is provided directly
- `type: "standalone"` indicates Docker Compose (not Docker Swarm)

## Complete Working Example

### Full Automation Script

```bash
#!/bin/bash

PORTAINER_URL="http://192.168.1.70:9000"
USERNAME="admin"
PASSWORD="YOUR_PASSWORD"
AGENT_IP="192.168.1.71"

# 1. Get authentication token
echo "Authenticating..."
TOKEN=$(curl -s -X POST "${PORTAINER_URL}/api/auth" \
  -H "Content-Type: application/json" \
  -d "{\"Username\":\"${USERNAME}\",\"Password\":\"${PASSWORD}\"}" | jq -r '.jwt')

if [ "$TOKEN" = "null" ] || [ -z "$TOKEN" ]; then
  echo "Authentication failed"
  exit 1
fi

# 2. Register agent
echo "Registering agent..."
AGENT_RESULT=$(curl -s -X POST "${PORTAINER_URL}/api/endpoints" \
  -H "Authorization: Bearer $TOKEN" \
  -F "Name=production-agent" \
  -F "URL=tcp://${AGENT_IP}:9001" \
  -F "EndpointCreationType=2" \
  -F "TLS=true" \
  -F "TLSSkipVerify=true" \
  -F "TLSSkipClientVerify=true")

ENDPOINT_ID=$(echo "$AGENT_RESULT" | jq -r '.Id')
echo "Agent registered with ID: $ENDPOINT_ID"

# 3. Deploy stack
echo "Deploying stack..."
STACK_CONTENT="version: '3.8'
services:
  nginx:
    image: nginx:alpine
    ports:
      - \"8080:80\"
    restart: unless-stopped
  whoami:
    image: traefik/whoami
    ports:
      - \"8081:80\"
    restart: unless-stopped"

curl -s -X POST "${PORTAINER_URL}/api/stacks/create/standalone/string?endpointId=${ENDPOINT_ID}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"method\": \"string\",
    \"type\": \"standalone\",
    \"Name\": \"production-stack\",
    \"StackFileContent\": $(echo "$STACK_CONTENT" | jq -Rs .),
    \"Env\": []
  }" | jq '.'

# 4. Verify deployment
echo "Verifying deployment..."
curl -s -H "Authorization: Bearer $TOKEN" \
  "${PORTAINER_URL}/api/stacks?endpointId=${ENDPOINT_ID}" | jq '.[] | {Id: .Id, Name: .Name, Status: .Status}'
```

## Management Operations

### List Endpoints

```bash
# List all registered environments
curl -s -H "Authorization: Bearer $TOKEN" \
  "${PORTAINER_URL}/api/endpoints" | jq '.[] | {Id: .Id, Name: .Name, URL: .URL, Status: .Status}'
```

### List Stacks

```bash
# List stacks on specific endpoint
curl -s -H "Authorization: Bearer $TOKEN" \
  "${PORTAINER_URL}/api/stacks?endpointId=6" | jq '.[] | {Id: .Id, Name: .Name, Status: .Status}'
```

### Delete Stack

```bash
# Delete stack by ID
STACK_ID=3
ENDPOINT_ID=6
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
  "${PORTAINER_URL}/api/stacks/${STACK_ID}?endpointId=${ENDPOINT_ID}"
```

## Common Issues and Solutions

### 1. Agent Registration Fails with "Invalid environment name"

**Cause**: Using JSON payload instead of form data

**Solution**: Use `-F` flags for form data, not `-d` with JSON

### 2. Stack Deployment Returns 405 Method Not Allowed

**Cause**: Using wrong API endpoint path

**Solution**: Use full path `/api/stacks/create/standalone/string?endpointId=X`

### 3. TLS Certificate Validation Errors

**Cause**: Agent certificates valid for container IP, not host IP

**Solution**: Use `TLSSkipVerify=true` in agent registration

### 4. Port Already Allocated Errors

**Cause**: Multiple stacks trying to bind same ports

**Solution**: Use unique ports for each stack or remove conflicting stacks first

### 5. Agent Shows as Disconnected

**Cause**: Network connectivity or certificate issues

**Solution**:
- Verify agent container is running: `docker ps`
- Check agent logs: `docker logs portainer-agent`
- Test connectivity: `curl -k https://AGENT_IP:9001/ping`

## Integration Examples

### Ansible Playbook

```yaml
---
- name: Deploy Portainer Stack via API
  uri:
    url: "http://{{ portainer_server }}:9000/api/stacks/create/standalone/string?endpointId={{ endpoint_id }}"
    method: POST
    headers:
      Authorization: "Bearer {{ portainer_token }}"
      Content-Type: "application/json"
    body_format: json
    body:
      method: "string"
      type: "standalone"
      Name: "{{ stack_name }}"
      StackFileContent: "{{ compose_content | to_json }}"
      Env: []
```

### Terraform Custom Provider

```hcl
resource "portainer_environment" "agent" {
  name     = "production-agent"
  endpoint_url = "tcp://192.168.1.71:9001"
  endpoint_type = 2
  tls_skip_verify = true
}

resource "portainer_stack" "webapp" {
  name        = "webapp"
  endpoint_id = portainer_environment.agent.id
  compose_content = file("docker-compose.yml")
}
```

## Security Considerations

1. **TLS Skip Verification**: Required for agent communication but reduces security
2. **Token Management**: JWT tokens have expiration times
3. **Network Security**: Ensure agent ports (9001) are properly firewalled
4. **Access Control**: Use Portainer RBAC for production environments

## Troubleshooting Commands

```bash
# Test server connectivity
curl -s http://192.168.1.70:9000/api/status

# Test agent connectivity
curl -k -s https://192.168.1.71:9001/ping

# Check agent logs
ssh root@192.168.1.71 "docker logs portainer-agent"

# Check server logs
ssh root@192.168.1.70 "docker logs portainer"

# Verify containers on agent
ssh root@192.168.1.71 "docker ps"

# Test deployed services
curl -s http://192.168.1.71:8080  # nginx
curl -s http://192.168.1.71:8081  # whoami
```

## Conclusion

This proof of concept demonstrates complete API control over Portainer infrastructure. The key discoveries were:

1. Agent registration requires form data, not JSON
2. Stack deployment uses a non-obvious API path structure
3. TLS certificate validation must be skipped due to IP mismatches
4. Both operations work reliably once the correct format is used

The workflow is production-ready for automation via Ansible, Terraform, or CI/CD pipelines.
