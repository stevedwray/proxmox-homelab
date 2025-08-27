# File: terraform/sock-shop/terraform-only/scripts/deploy-catalogue.sh
# Catalogue service deployment script for Terraform-only approach
#!/bin/bash
set -e

DATABASE_IP="${database_ip}"

echo "Starting catalogue service deployment..."

# Regenerate SSH host keys if missing
if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then
    ssh-keygen -A
    systemctl restart ssh
fi

# Wait for Docker to be ready
echo "Waiting for Docker service..."
while ! systemctl is-active docker &>/dev/null; do
  echo "Docker not ready, waiting 10 seconds..."
  sleep 10
done

# Create network
echo "Creating Docker network..."
docker network create sock-shop 2>/dev/null || true

# Create application directories
mkdir -p /data/sock-shop /config/sock-shop /logs/sock-shop

# Deploy catalogue service
echo "Deploying Catalogue service..."
docker run -d --name catalogue \
  --network sock-shop \
  --restart unless-stopped \
  -e DATABASE_URL="mongodb://$DATABASE_IP:27017/catalogue" \
  --add-host="catalogue-db:$DATABASE_IP" \
  weaveworksdemos/catalogue:0.3.5

echo "Catalogue service deployed successfully!"
echo "Services running:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
