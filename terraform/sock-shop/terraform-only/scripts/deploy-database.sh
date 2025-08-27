# File: terraform/sock-shop/terraform-only/scripts/deploy-database.sh
# Database services deployment script for Terraform-only approach
#!/bin/bash
set -e

echo "Starting database services deployment..."

# Regenerate SSH host keys if missing
if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then
    ssh-keygen -A
    systemctl restart ssh
fi

# Wait for Docker to be ready
echo "Waiting for Docker service..."
while ! systemctl is-active docker &>/dev/null; do
  echo "Docker not ready, waiting 5 seconds..."
  sleep 5
done

# Create network
echo "Creating Docker network..."
docker network create sock-shop 2>/dev/null || true

# Create data directories
mkdir -p /data/sock-shop/{catalogue-db,user-db,orders-db,session-db}

# Deploy MongoDB for catalogue
echo "Deploying MongoDB for catalogue..."
docker run -d --name catalogue-db \
  --network sock-shop \
  --restart unless-stopped \
  -v /data/sock-shop/catalogue-db:/data/db \
  mongo:4.4

# Deploy MySQL for users
echo "Deploying MySQL for users..."
docker run -d --name user-db \
  --network sock-shop \
  --restart unless-stopped \
  -v /data/sock-shop/user-db:/var/lib/mysql \
  -e MYSQL_ROOT_PASSWORD=fake_password \
  -e MYSQL_DATABASE=socksdb \
  weaveworksdemos/user-db:0.3.0

# Deploy MongoDB for orders
echo "Deploying MongoDB for orders..."
docker run -d --name orders-db \
  --network sock-shop \
  --restart unless-stopped \
  -v /data/sock-shop/orders-db:/data/db \
  mongo:4.4

# Deploy Redis for sessions
echo "Deploying Redis for sessions..."
docker run -d --name session-db \
  --network sock-shop \
  --restart unless-stopped \
  redis:alpine

# Deploy RabbitMQ for messaging
echo "Deploying RabbitMQ..."
docker run -d --name queue-master \
  --network sock-shop \
  --restart unless-stopped \
  -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=admin \
  -e RABBITMQ_DEFAULT_PASS=admin \
  rabbitmq:3.8-management

echo "Database services deployed successfully!"
echo "Services running:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
