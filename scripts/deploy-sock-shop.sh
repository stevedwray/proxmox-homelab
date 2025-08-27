# File: scripts/deploy-sock-shop.sh
# Comprehensive deployment script for both approaches

#!/bin/bash

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

APPROACH=""
PHASE=""

usage() {
    echo "Usage: $0 [terraform-ansible|terraform-only] [single|multi|full]"
    echo
    echo "Approaches:"
    echo "  terraform-ansible   - Use Terraform + Ansible workflow"
    echo "  terraform-only      - Use Terraform-only workflow"
    echo
    echo "Phases:"
    echo "  single             - Deploy single container (frontend only)"
    echo "  multi              - Deploy multi-container (frontend + database + user)"
    echo "  full               - Deploy complete microservices stack"
    echo
    echo "Examples:"
    echo "  $0 terraform-ansible single"
    echo "  $0 terraform-only full"
    exit 1
}

validate_environment() {
    echo -e "${YELLOW}Validating environment...${NC}"

    # Check if we're in the right directory
    if [ ! -f ".env" ]; then
        echo -e "${RED}Error: .env file not found. Please run from project root.${NC}"
        exit 1
    fi

    # Source environment
    source .env

    # Check required tools
    for tool in terraform ansible-playbook ssh; do
        if ! command -v $tool &> /dev/null; then
            echo -e "${RED}Error: $tool is not installed${NC}"
            exit 1
        fi
    done

    # Check Proxmox connectivity
    if ! ping -c 1 pvetest.gibbsgreatly.xyz &> /dev/null; then
        echo -e "${RED}Error: Cannot reach Proxmox server${NC}"
        exit 1
    fi

    echo -e "${GREEN}Environment validation complete${NC}"
}

deploy_terraform_ansible_single() {
    echo -e "${YELLOW}Deploying single container with Terraform + Ansible...${NC}"

    cd terraform/sock-shop/single-container

    echo "Initializing Terraform..."
    terraform init

    echo "Planning deployment..."
    terraform plan

    echo "Applying infrastructure..."
    terraform apply -auto-approve

    cd ../../../

    echo "Waiting for container to be ready..."
    sleep 60

    echo "Deploying application with Ansible..."
    ansible-playbook -i ansible/inventory/sock-shop.yml ansible/sock-shop/deploy-frontend.yml

    echo -e "${GREEN}Single container deployment complete!${NC}"
    echo "Access: http://192.168.1.60"
}

deploy_terraform_ansible_multi() {
    echo -e "${YELLOW}Deploying multi-container with Terraform + Ansible...${NC}"

    cd terraform/sock-shop/multi-container

    terraform init
    terraform plan
    terraform apply -auto-approve

    cd ../../../

    echo "Waiting for containers to be ready..."
    sleep 90

    ansible-playbook -i ansible/inventory/sock-shop.yml ansible/sock-shop/deploy-multi-container.yml

    echo -e "${GREEN}Multi-container deployment complete!${NC}"
    echo "Access: http://192.168.1.60"
}

deploy_terraform_ansible_full() {
    echo -e "${YELLOW}Deploying full stack with Terraform + Ansible...${NC}"

    cd terraform/sock-shop/full-stack

    terraform init
    terraform plan
    terraform apply -auto-approve

    cd ../../../

    echo "Waiting for containers to be ready..."
    sleep 120

    ansible-playbook -i ansible/inventory/sock-shop.yml ansible/sock-shop/deploy-complete.yml

    echo -e "${GREEN}Full stack deployment complete!${NC}"
    echo "Access: http://192.168.1.60"
    echo "RabbitMQ Management: http://192.168.1.67:15672 (admin/admin)"
}

deploy_terraform_only() {
    echo -e "${YELLOW}Deploying with Terraform-only approach...${NC}"

    cd terraform/sock-shop/terraform-only

    terraform init
    terraform plan
    terraform apply -auto-approve

    cd ../../../

    echo -e "${GREEN}Terraform-only deployment complete!${NC}"
    echo "Access: http://192.168.1.70"
}

cleanup_deployment() {
    local approach=$1
    local phase=$2

    echo -e "${YELLOW}Cleaning up deployment...${NC}"

    if [ "$approach" = "terraform-ansible" ]; then
        case $phase in
            single)
                cd terraform/sock-shop/single-container
                ;;
            multi)
                cd terraform/sock-shop/multi-container
                ;;
            full)
                cd terraform/sock-shop/full-stack
                ;;
        esac
    else
        cd terraform/sock-shop/terraform-only
    fi

    terraform destroy -auto-approve
    cd ../../../

    echo -e "${GREEN}Cleanup complete${NC}"
}

# Parse arguments
if [ $# -lt 2 ]; then
    usage
fi

APPROACH=$1
PHASE=$2

case $APPROACH in
    terraform-ansible|terraform-only)
        ;;
    cleanup)
        cleanup_deployment $2 $3
        exit 0
        ;;
    *)
        echo -e "${RED}Error: Invalid approach '$APPROACH'${NC}"
        usage
        ;;
esac

case $PHASE in
    single|multi|full)
        ;;
    *)
        echo -e "${RED}Error: Invalid phase '$PHASE'${NC}"
        usage
        ;;
esac

# Execute deployment
validate_environment

echo -e "${GREEN}Starting deployment: $APPROACH approach, $PHASE phase${NC}"

case $APPROACH in
    terraform-ansible)
        case $PHASE in
            single)
                deploy_terraform_ansible_single
                ;;
            multi)
                deploy_terraform_ansible_multi
                ;;
            full)
                deploy_terraform_ansible_full
                ;;
        esac
        ;;
    terraform-only)
        deploy_terraform_only
        ;;
esac

# Run health check
echo -e "${YELLOW}Running health check...${NC}"
if [ -f "scripts/health-check.sh" ]; then
    chmod +x scripts/health-check.sh
    ./scripts/health-check.sh
else
    echo -e "${YELLOW}Health check script not found, skipping...${NC}"
fi

echo -e "${GREEN}Deployment completed successfully!${NC}"
echo
echo "To clean up this deployment, run:"
echo "  $0 cleanup $APPROACH $PHASE"
