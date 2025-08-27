# File: terraform/sock-shop/terraform-only/scripts/deploy-frontend.sh
# Frontend service deployment script for Terraform-only approach
#!/bin/bash
set -e

DATABASE_IP="${database_ip}"
USER_IP="${user_ip}"
CATALOGUE_IP="${catalogue_ip}"

echo "Starting frontend deployment..."

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

# Deploy frontend
echo "Deploying Sock Shop Frontend..."
docker run -d --name front-end \
  --network sock-shop \
  --restart unless-stopped \
  -p 80:8079 \
  -e SESSION_REDIS="$DATABASE_IP:6379" \
  -e CATALOGUE_ENDPOINT="$CATALOGUE_IP:80" \
  -e USER_ENDPOINT="$USER_IP:80" \
  -e CART_ENDPOINT="carts:80" \
  -e ORDERS_ENDPOINT="orders:80" \
  -e PAYMENT_ENDPOINT="payment:80" \
  -e SHIPPING_ENDPOINT="shipping:80" \
  --add-host="user:$USER_IP" \
  --add-host="catalogue:$CATALOGUE_IP" \
  --add-host="session-db:$DATABASE_IP" \
  weaveworksdemos/front-end:0.3.12

echo "Frontend service deployed successfully!"
echo "Access URL: http://${container_ip}"
echo "Services running:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
