# Phase 04: Core Shared Services Deployment Guide

> **Status**: Ready for deployment
> **Prerequisites**: ✓ All verified
> **Branch**: `feat/phase-04-core-services`
> **Services**: Authentik (identity) → Traefik (proxy) → step-ca (CA) → Monitoring (metrics/logs)

## Quick Start

```bash
cd /home/steve/git/proxmox-homelab

# Source environment for pve-test
source .env && source .env.pve-test
echo "Target node: $TF_VAR_proxmox_node"  # Should show: pve-test

# Deploy all services in sequence
bash scripts/deploy-phase-04-orchestrate.sh
```

## Manual Step-by-Step Deployment

If you prefer to deploy each service individually with visibility into each step:

### 1. Authentik (Identity Provider)

**Location**: `terraform/lxc/stacks/authentik-stack/`

```bash
# Setup environment
cd /home/steve/git/proxmox-homelab
source .env && source .env.pve-test
cd terraform/lxc/stacks/authentik-stack

# Initialize Terragrunt
terragrunt init

# Plan infrastructure (review output)
terragrunt plan

# Apply infrastructure  (creates LXC container VMID 150, IP 10.57.1.10)
terragrunt apply -auto-approve

# Deploy application via Ansible
cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i terraform/lxc/stacks/authentik-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml

# Validate health
curl -s http://10.57.1.10:9000/-/health/live/    # Expect: HTTP 204
curl -s http://10.57.1.10:9000/-/health/ready/   # Expect: HTTP 204

# Initialize via web UI (if 204 responses received)
# Visit: http://10.57.1.10:9000/if/flow/initial-setup/
# Create admin account with AUTHENTIK_SUPERUSER_PASSWORD from SOPS
```

**Secrets Used**:
- `AUTHENTIK_SECRET_KEY` — from SOPS
- `AUTHENTIK_POSTGRES_PASSWORD` — from SOPS
- `AUTHENTIK_SUPERUSER_PASSWORD` — from SOPS
- `AUTHENTIK_SUPERUSER_API_TOKEN` — from SOPS

**Network**:
- Zone: `mgmt_seg`
- IP: `10.57.1.10`
- VMID: `150`
- Ports: `9000` (HTTP), `9443` (HTTPS)

**Expected Resources**:
- PostgreSQL 16 database
- Redis cache
- Authentik server & worker containers

---

### 2. Traefik (Reverse Proxy)

**Location**: `terraform/lxc/stacks/proxy-stack/`

```bash
# Setup environment
cd /home/steve/git/proxmox-homelab
source .env && source .env.pve-test
cd terraform/lxc/stacks/proxy-stack

# Initialize Terragrunt
terragrunt init

# Plan infrastructure
terragrunt plan

# Apply infrastructure (creates LXC container VMID 153, IP 10.57.2.10)
terragrunt apply -auto-approve

# Deploy application via Ansible
cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i terraform/lxc/stacks/proxy-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml

# Validate routing (check Docker compose health)
docker ps  # From proxy-stack container after SSH

# Test ports (from LAN)
curl -I http://10.57.2.10/dashboard/  # Traefik dashboard
```

**Dependencies**:
- Must deploy AFTER Authentik (configured in stack.yaml)
- Requires Authentik running for forward-auth middleware

**Network**:
- Zone: `edge_seg`
- IP: `10.57.2.10`
- VMID: `153`
- Ports: `80` (HTTP), `443` (HTTPS) — exposed to LAN via MikroTik

**ACME Certificates**:
- Primary: Let's Encrypt (via Cloudflare DNS-01)
- Secondary: step-ca (internal) — configured but inactive until step-ca deployed
- Wildcard: `*.gibbsgreatly.xyz`

**Note**: step-ca resolver references are safe to keep even if step-ca not yet ready. Traefik only contacts resolvers for routes that explicitly request them.

---

### 3. step-ca (Internal Certificate Authority)

**Location**: `terraform/lxc/stacks/step-ca-stack/`

```bash
# Setup environment
cd /home/steve/git/proxmox-homelab
source .env && source .env.pve-test
cd terraform/lxc/stacks/step-ca-stack

# Initialize Terragrunt
terragrunt init

# Plan infrastructure
terragrunt plan

# Apply infrastructure (creates LXC container VMID 152, IP 10.57.1.11)
terragrunt apply -auto-approve

# Deploy application via Ansible
cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i terraform/lxc/stacks/step-ca-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-step-ca.yml

# Trust CA certificate on control machine and other services
./with-secrets ansible-playbook \
  -i terraform/lxc/stacks/step-ca-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/trust-homelab-ca.yml

# Validate ACME directory
curl -sk https://10.57.1.11/acme/acme/directory | jq .

# Traefik will automatically activate step-ca resolver once CA is active
```

**Network**:
- Zone: `mgmt_seg`
- IP: `10.57.1.11`
- VMID: `152`
- Port: `443` (HTTPS)

**ACME Directory**:
- URL: `https://10.57.1.11/acme/acme/directory`
- Used by: Traefik (for internal routes), CI runner, other internal services

**CA Certificate Distribution**:
- Distributed to Traefik container
- Distributed to CI runner
- Distributed to Ansible control machine
- Installed in any container calling internal services directly

---

### 4. Monitoring Stack (VictoriaMetrics + Grafana + Loki)

**Location**: `terraform/lxc/stacks/monitoring-stack/`

```bash
# Setup environment
cd /home/steve/git/proxmox-homelab
source .env && source .env.pve-test
cd terraform/lxc/stacks/monitoring-stack

# Initialize Terragrunt
terragrunt init

# Plan infrastructure
terragrunt plan

# Apply infrastructure (creates LXC container VMID 154, IP 10.57.1.12, 50GB storage)
terragrunt apply -auto-approve

# Deploy application via Ansible
cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i terraform/lxc/stacks/monitoring-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml

# Access Grafana dashboard
# URL: http://10.57.1.12:3000/
# Credentials: admin / (check logs or SOPS)

# Verify metrics collection
curl -s http://10.57.1.12:8428/api/v1/query?query=up | jq .
curl -s http://10.57.1.12:3100/loki/api/v1/query?query={} | jq .
```

**Network**:
- Zone: `mgmt_seg`
- IP: `10.57.1.12`
- VMID: `154`
- Ports: `8428` (VictoriaMetrics), `3100` (Loki), `3000` (Grafana)
- Storage: `50GB` (docker_storage_size)

**Services**:
- **VictoriaMetrics** — Time series database
  - API: `:8428`
  - Query: `http://10.57.1.12:8428/api/v1/query`

- **Grafana** — Metrics visualization
  - Web UI: `http://10.57.1.12:3000/`
  - Default creds: `admin/admin` (change after first login)

- **Loki** — Log aggregation
  - API: `:3100`
  - Query: `http://10.57.1.12:3100/loki/api/v1/query`

**Dependencies**:
- Must deploy LAST (depends on all other services)
- Configured to collect metrics from Authentik, Traefik, step-ca

---

## Validation Checklist

After each service deployment, verify:

### Infrastructure Level
```bash
# Verify container created on pve-test
pct list | grep -E "authentik|proxy-stack|step-ca|monitoring"

# Verify IP assignments
for ip in 10.57.1.10 10.57.2.10 10.57.1.11 10.57.1.12; do
  ping -c 1 $ip && echo "✓ $ip reachable" || echo "✗ $ip unreachable"
done

# Check NetBox for IP conflicts
for ip in 10.57.1.10 10.57.2.10 10.57.1.11 10.57.1.12; do
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://10.57.3.12/api/ipam/ip-addresses/?address=$ip" | jq '.count'
done
```

### Application Level
```bash
# Authentik health
curl -s http://10.57.1.10:9000/-/health/live/ -w "\n%{http_code}\n"

# Traefik dashboard (requires network access)
curl -I http://10.57.2.10/dashboard

# step-ca ACME directory
curl -sk https://10.57.1.11/acme/acme/directory | jq .nonce_url

# Monitoring services
curl -s http://10.57.1.12:8428/api/v1/targets?state=active | jq '.activeTargets | length'
```

---

## Security Scanning Before Merge

After all services are deployed and validated:

```bash
# Terraform IaC Security Scan
/home/steve/.local/bin/snyk iac test terraform/

# Code Quality Scan
source .env && sonar-scanner
```

If any new issues are detected, resolve or document them before merging.

---

## Commit Strategy

```bash
# Commit per-service after successful deployment + validation
git add -A
git commit -m "feat(phase-04): deploy authentik identity provider

- Created Authentik LXC container (VMID 150, 10.57.1.10)
- PostgreSQL 16 + Redis deployment via Docker Compose
- Secrets from SOPS (no env secrets in repo)
- Health endpoints validated"

git commit -m "feat(phase-04): deploy traefik reverse proxy

- Created Traefik LXC container (VMID 153, 10.57.2.10)
- Dual ACME resolvers configured (Let's Encrypt + step-ca)
- Authentik forward-auth middleware active
- Ports 80/443 exposed to LAN"

# ... continue for step-ca and monitoring

# After all services deployed and fully validated
git push origin feat/phase-04-core-services
```

Then either:
- Create PR from `feat/phase-04-core-services` → `dev/pve-test`
- Merge locally and test on pve-test
- PR `dev/pve-test` → `main`

---

## Troubleshooting

### Terragrunt Init Fails
```bash
# Ensure correct node target
echo $TF_VAR_proxmox_node  # Should be: pve-test

# Clear cache and retry
rm -rf terraform/lxc/stacks/*/force-copy .terragrunt-cache
terragrunt init
```

### Ansible Playbook Fails
```bash
# Check secrets are available
./with-secrets env | grep AUTHENTIK_

# Run playbook with verbose output
./with-secrets ansible-playbook -vvv \
  -i terraform/lxc/stacks/authentik-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml
```

### Container Unreachable
```bash
# SSH into container
ssh -i ~/.ssh/id_ed25519 root@10.57.1.10

# Check networking inside container
ip -4 addr show
route -n

# Check Docker services
docker ps -a
docker logs service-name
```

### Health Checks Return 5xx
```bash
# Wait for service initialization (first 2-3 minutes typical)
watch -n 2 'curl -s http://10.57.1.10:9000/-/health/ready/ && echo "✓" || echo "✗"'

# Check container logs
docker logs authentik-server
docker logs authentik-worker
```

---

## References

- **Stack Configurations**: `terraform/lxc/stacks/*/stack.yaml`
- **Docker Compose Files**: `terraform/lxc/stacks/*/docker-compose.yml`
- **Ansible Playbooks**: `terraform/lxc/ansible/playbooks/deploy-*.yml`
- **Terraform Modules**: `terraform/lxc/`
- **Networking**: See `docs/plan/` for SDN and MikroTik routing details
- **SOPS Secrets**: `terraform/secrets.enc.yaml` (access via `./with-secrets`)

---

## Next Steps After Phase 04

Once all four services are deployed, tested, and validated on pve-test:

1. **Merge to dev/pve-test**: All services should continue running and be fully functional
2. **Phase 05 (Supply Chain)**: Assumes Phase 04 services are stable
3. **Phase 06 (Application Migration)**: Assumes Phase 04 + Phase 05 complete
4. **Issue #114 Completion**: SDN zone routing between services

**Current Status**: Prerequisites verified ✓ | Ready to deploy ✓

---

## Example: Full Deployment Session

```bash
#!/bin/bash
# Complete Phase 04 deployment with logs

cd /home/steve/git/proxmox-homelab
source .env && source .env.pve-test

services=(authent authentik proxy step-ca monitoring)
logfile="/tmp/phase-04-deployment-$(date +%s).log"

for service in "${services[@]}"; do
  stack_name="${service}-stack"
  echo "$(date): Starting $stack_name deployment" | tee -a "$logfile"

  cd "terraform/lxc/stacks/$stack_name"
  terragrunt init 2>&1 | tee -a "$logfile"
  terragrunt apply -auto-approve 2>&1 | tee -a "$logfile"

  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook \
    -i "terraform/lxc/stacks/${stack_name}/inventory.yml" \
    "terraform/lxc/ansible/playbooks/deploy-${service}.yml" \
    2>&1 | tee -a "$logfile"

  echo "$(date): Completed $stack_name deployment" | tee -a "$logfile"
  sleep 60  # Wait before next service
done

echo "Phase 04 deployment complete. Log: $logfile"
```

deployed, tested, and validated on pve-test:

1. **Merge to dev/pve-test**: All services should continue running and be fully functional
2. **Phase 05** assumes Phase 04 is stable
3. **Phase 06** assumes both 04 and 05 complete
