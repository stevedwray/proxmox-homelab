# File: scripts/health-check.sh
# Comprehensive health check for Sock Shop deployment
#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
FRONTEND_IP="192.168.1.60"
USER_IP="192.168.1.61"
CATALOGUE_IP="192.168.1.62"
CARTS_IP="192.168.1.63"
ORDERS_IP="192.168.1.64"
PAYMENT_IP="192.168.1.65"
SHIPPING_IP="192.168.1.66"
DATABASE_IP="192.168.1.67"

# Terraform-only IPs (if testing that deployment)
TF_FRONTEND_IP="192.168.1.70"
TF_USER_IP="192.168.1.71"
TF_CATALOGUE_IP="192.168.1.72"
TF_DATABASE_IP="192.168.1.73"

echo -e "${GREEN}=== Sock Shop Health Check ===${NC}"
echo "$(date)"
echo

# Function to check if host is reachable
check_host() {
    local ip=$1
    local name=$2
    if ping -c 1 -W 2 $ip &>/dev/null; then
        echo -e "${GREEN}✓${NC} $name ($ip) - Container reachable"
        return 0
    else
        echo -e "${RED}✗${NC} $name ($ip) - Container unreachable"
        return 1
    fi
}

# Function to check web service
check_web_service() {
    local ip=$1
    local name=$2
    local expected_content=$3

    if curl -s --connect-timeout 5 http://$ip | grep -q "$expected_content"; then
        echo -e "${GREEN}✓${NC} $name service responding correctly"
        return 0
    else
        echo -e "${RED}✗${NC} $name service not responding or incorrect content"
        return 1
    fi
}

# Function to check Docker containers on a host
check_docker_containers() {
    local ip=$1
    local name=$2

    echo -e "\n${YELLOW}Docker containers on $name ($ip):${NC}"
    if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no root@$ip "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'" 2>/dev/null; then
        return 0
    else
        echo -e "${RED}✗${NC} Could not connect to $name for Docker status"
        return 1
    fi
}

# Check Terraform+Ansible deployment
echo -e "${YELLOW}=== Checking Terraform+Ansible Deployment ===${NC}"
ANSIBLE_REACHABLE=0

check_host $FRONTEND_IP "Frontend" && ((ANSIBLE_REACHABLE++))
check_host $USER_IP "User Service" && ((ANSIBLE_REACHABLE++))
check_host $CATALOGUE_IP "Catalogue Service" && ((ANSIBLE_REACHABLE++))
check_host $DATABASE_IP "Database" && ((ANSIBLE_REACHABLE++))

if [ $ANSIBLE_REACHABLE -gt 0 ]; then
    echo -e "\n${YELLOW}Web Service Checks:${NC}"
    check_web_service $FRONTEND_IP "Frontend" "Sock Shop"

    echo -e "\n${YELLOW}Docker Container Status:${NC}"
    check_docker_containers $FRONTEND_IP "Frontend"
    check_docker_containers $DATABASE_IP "Database"

    echo -e "\n${YELLOW}Service Endpoints:${NC}"
    echo "Frontend: http://$FRONTEND_IP"
    echo "RabbitMQ Management: http://$DATABASE_IP:15672 (admin/admin)"
fi

# Check Terraform-only deployment
echo -e "\n${YELLOW}=== Checking Terraform-Only Deployment ===${NC}"
TERRAFORM_REACHABLE=0

check_host $TF_FRONTEND_IP "TF Frontend" && ((TERRAFORM_REACHABLE++))
check_host $TF_USER_IP "TF User Service" && ((TERRAFORM_REACHABLE++))
check_host $TF_CATALOGUE_IP "TF Catalogue Service" && ((TERRAFORM_REACHABLE++))
check_host $TF_DATABASE_IP "TF Database" && ((TERRAFORM_REACHABLE++))

if [ $TERRAFORM_REACHABLE -gt 0 ]; then
    echo -e "\n${YELLOW}Web Service Checks:${NC}"
    check_web_service $TF_FRONTEND_IP "TF Frontend" "Sock Shop"

    echo -e "\n${YELLOW}Docker Container Status:${NC}"
    check_docker_containers $TF_FRONTEND_IP "TF Frontend"
    check_docker_containers $TF_DATABASE_IP "TF Database"

    echo -e "\n${YELLOW}Service Endpoints:${NC}"
    echo "Terraform-only Frontend: http://$TF_FRONTEND_IP"
    echo "Terraform-only RabbitMQ: http://$TF_DATABASE_IP:15672 (admin/admin)"
fi

# Summary
echo -e "\n${YELLOW}=== Summary ===${NC}"
if [ $ANSIBLE_REACHABLE -eq 4 ]; then
    echo -e "${GREEN}✓${NC} Terraform+Ansible deployment: All containers reachable"
elif [ $ANSIBLE_REACHABLE -gt 0 ]; then
    echo -e "${YELLOW}⚠${NC} Terraform+Ansible deployment: $ANSIBLE_REACHABLE/4 containers reachable"
else
    echo -e "${RED}✗${NC} Terraform+Ansible deployment: No containers reachable"
fi

if [ $TERRAFORM_REACHABLE -eq 4 ]; then
    echo -e "${GREEN}✓${NC} Terraform-only deployment: All containers reachable"
elif [ $TERRAFORM_REACHABLE -gt 0 ]; then
    echo -e "${YELLOW}⚠${NC} Terraform-only deployment: $TERRAFORM_REACHABLE/4 containers reachable"
else
    echo -e "${RED}✗${NC} Terraform-only deployment: No containers reachable"
fi

echo -e "\n${YELLOW}Deployment validation complete!${NC}"
