#!/bin/bash
# npm-migrate-from-lxc.sh
# Copy NPM data from LXC container (192.168.1.4) to dev server (192.168.1.9)

set -e

# Server configuration
PROD_LXC="192.168.1.4"      # NPM LXC container IP
DEV_SERVER="192.168.1.9"    # Dev Proxmox server
PROD_PATH="/nginx"          # Path inside LXC container
DEV_DATASET="rpool/data/npm"
DEV_MOUNT="/srv/npm"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}=== NPM LXC to Dev Migration ===${NC}"
echo "NPM LXC container: $PROD_LXC"
echo "Dev server: $DEV_SERVER"
echo "Source path (in LXC): $PROD_PATH"
echo "Target dataset: $DEV_DATASET"
echo "Target mount: $DEV_MOUNT"
echo ""

# Function to check server connectivity
check_connectivity() {
    echo -e "${BLUE}Checking connectivity...${NC}"
    
    if ! ssh -o ConnectTimeout=5 -q root@$PROD_LXC exit; then
        echo -e "${RED}✗ Cannot connect to NPM LXC container ($PROD_LXC)${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ NPM LXC container accessible${NC}"
    
    if ! ssh -o ConnectTimeout=5 -q root@$DEV_SERVER exit; then
        echo -e "${RED}✗ Cannot connect to dev server ($DEV_SERVER)${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Dev server accessible${NC}"
}

# Function to verify source data in LXC container
verify_source_data() {
    echo -e "${BLUE}Verifying source data in LXC container...${NC}"
    
    if ! ssh root@$PROD_LXC "test -d $PROD_PATH"; then
        echo -e "${RED}✗ NPM directory not found in LXC: $PROD_PATH${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ NPM directory found in LXC${NC}"
    
    # Show the structure in LXC container
    echo -e "${BLUE}NPM directory structure in LXC:${NC}"
    ssh root@$PROD_LXC "ls -la $PROD_PATH/" || true
    
    # Check for typical NPM subdirectories
    if ssh root@$PROD_LXC "test -d $PROD_PATH/data"; then
        echo -e "${GREEN}✓ Data directory found${NC}"
        DATA_EXISTS=true
    else
        echo -e "${YELLOW}⚠ Data directory not found${NC}"
        DATA_EXISTS=false
    fi
    
    if ssh root@$PROD_LXC "test -d $PROD_PATH/letsencrypt -o -d $PROD_PATH/certs"; then
        echo -e "${GREEN}✓ SSL certificates directory found${NC}"
        CERTS_EXIST=true
        # Determine which cert directory exists
        if ssh root@$PROD_LXC "test -d $PROD_PATH/letsencrypt"; then
            CERT_DIR="letsencrypt"
        else
            CERT_DIR="certs"
        fi
        echo -e "${BLUE}Using certificate directory: $CERT_DIR${NC}"
    else
        echo -e "${YELLOW}⚠ SSL certificates directory not found${NC}"
        CERTS_EXIST=false
    fi
    
    # Try to find database
    if ssh root@$PROD_LXC "find $PROD_PATH -name 'database.sqlite' -type f" | grep -q database.sqlite; then
        echo -e "${GREEN}✓ NPM database found${NC}"
        DB_PATH=$(ssh root@$PROD_LXC "find $PROD_PATH -name 'database.sqlite' -type f" | head -1)
        echo -e "${BLUE}Database location: $DB_PATH${NC}"
    else
        echo -e "${YELLOW}⚠ NPM database not found (may be fresh installation)${NC}"
    fi
}

# Function to create ZFS dataset on dev server
create_zfs_dataset() {
    echo -e "${BLUE}Setting up ZFS dataset on dev server...${NC}"
    
    # Check if dataset already exists
    if ssh root@$DEV_SERVER "zfs list $DEV_DATASET >/dev/null 2>&1"; then
        echo -e "${YELLOW}Dataset $DEV_DATASET already exists${NC}"
        read -p "Destroy and recreate? (y/N): " confirm
        if [[ $confirm =~ ^[Yy]$ ]]; then
            echo -e "${YELLOW}Destroying existing dataset...${NC}"
            ssh root@$DEV_SERVER "zfs destroy -r $DEV_DATASET"
        else
            echo -e "${BLUE}Using existing dataset${NC}"
            return 0
        fi
    fi
    
    # Create the dataset
    echo -e "${GREEN}Creating ZFS dataset: $DEV_DATASET${NC}"
    ssh root@$DEV_SERVER "zfs create -o mountpoint=$DEV_MOUNT $DEV_DATASET"
    
    # Set appropriate permissions
    ssh root@$DEV_SERVER "chmod 755 $DEV_MOUNT"
    
    echo -e "${GREEN}✓ ZFS dataset created and mounted at $DEV_MOUNT${NC}"
}

# Function to stop NPM in LXC container
stop_npm_container() {
    echo -e "${BLUE}Checking for running NPM containers in LXC...${NC}"
    
    # Check if NPM container is running in LXC
    if ssh root@$PROD_LXC "docker ps --format '{{.Names}}' | grep -E 'nginx.*proxy|npm'" >/dev/null 2>&1; then
        echo -e "${YELLOW}Stopping NPM container in LXC...${NC}"
        ssh root@$PROD_LXC "docker stop \$(docker ps -q --filter ancestor=jc21/nginx-proxy-manager)" || true
        # Try with compose if available
        ssh root@$PROD_LXC "cd $PROD_PATH && docker compose down" 2>/dev/null || true
        NPM_STOPPED=true
    else
        echo -e "${GREEN}No NPM container running in LXC (or not using Docker)${NC}"
        NPM_STOPPED=false
    fi
}

# Function to copy data from LXC to dev server
copy_npm_data() {
    echo -e "${GREEN}Copying NPM data from LXC...${NC}"
    
    # Create target directories
    ssh root@$DEV_SERVER "mkdir -p $DEV_MOUNT/data $DEV_MOUNT/letsencrypt"
    
    # Copy entire nginx directory structure via intermediate tar transfer
    echo -e "${BLUE}Creating archive on LXC container...${NC}"
    ssh root@$PROD_LXC "cd $PROD_PATH && tar czf /tmp/npm-backup.tar.gz ."
    
    echo -e "${BLUE}Copying archive to dev server...${NC}"
    ssh root@$PROD_LXC "cat /tmp/npm-backup.tar.gz" | ssh root@$DEV_SERVER "cat > /tmp/npm-backup.tar.gz"
    
    echo -e "${BLUE}Extracting archive on dev server...${NC}"
    ssh root@$DEV_SERVER "cd $DEV_MOUNT && tar xzf /tmp/npm-backup.tar.gz"
    
    # Clean up temporary files
    ssh root@$PROD_LXC "rm -f /tmp/npm-backup.tar.gz"
    ssh root@$DEV_SERVER "rm -f /tmp/npm-backup.tar.gz"
    
    # If there's a specific data directory, ensure it's in the right place
    if [[ "$DATA_EXISTS" == "true" ]]; then
        echo -e "${BLUE}Ensuring data directory structure...${NC}"
        ssh root@$DEV_SERVER "test -d $DEV_MOUNT/data || (mkdir -p $DEV_MOUNT/data && cp -r $DEV_MOUNT/*/data/* $DEV_MOUNT/data/ 2>/dev/null || true)"
    fi
    
    # Handle certificate directory mapping
    if [[ "$CERTS_EXIST" == "true" ]]; then
        echo -e "${BLUE}Mapping certificate directory...${NC}"
        if [[ "$CERT_DIR" == "certs" ]]; then
            # Copy certs to letsencrypt for NPM compatibility
            ssh root@$DEV_SERVER "cp -r $DEV_MOUNT/certs/* $DEV_MOUNT/letsencrypt/ 2>/dev/null || true"
        fi
    fi
    
    # Set proper ownership for NPM
    echo -e "${BLUE}Setting proper ownership...${NC}"
    ssh root@$DEV_SERVER "chown -R root:root $DEV_MOUNT/"
    
    # Create any missing standard directories
    ssh root@$DEV_SERVER "mkdir -p $DEV_MOUNT/data/logs $DEV_MOUNT/data/nginx $DEV_MOUNT/data/custom_ssl"
}

# Function to restart NPM in LXC if needed
restart_npm_lxc() {
    if [[ "$NPM_STOPPED" == "true" ]]; then
        echo -e "${YELLOW}Restarting NPM in LXC container...${NC}"
        ssh root@$PROD_LXC "cd $PROD_PATH && docker compose up -d" 2>/dev/null || \
        ssh root@$PROD_LXC "docker run -d --name npm -p 80:80 -p 443:443 -p 81:81 -v $PROD_PATH/data:/data -v $PROD_PATH/letsencrypt:/etc/letsencrypt jc21/nginx-proxy-manager:latest" 2>/dev/null || \
        echo -e "${YELLOW}Could not restart automatically - please restart NPM manually in LXC${NC}"
    fi
}

# Function to verify migration
verify_migration() {
    echo -e "${BLUE}Verifying migration...${NC}"
    
    # Show what was copied
    echo -e "${BLUE}Target directory structure:${NC}"
    ssh root@$DEV_SERVER "ls -la $DEV_MOUNT/"
    
    # Look for database
    local db_found=$(ssh root@$DEV_SERVER "find $DEV_MOUNT -name '*.sqlite' -type f" | head -1)
    if [[ -n "$db_found" ]]; then
        local db_size=$(ssh root@$DEV_SERVER "stat -c%s '$db_found'")
        echo -e "${GREEN}✓ Database found: $db_found ($(($db_size / 1024))KB)${NC}"
    else
        echo -e "${YELLOW}⚠ No SQLite database found - may be fresh installation${NC}"
    fi
    
    # Check for configuration files
    local configs=$(ssh root@$DEV_SERVER "find $DEV_MOUNT -name '*.json' -o -name '*.conf' | wc -l")
    echo -e "${GREEN}✓ Found $configs configuration files${NC}"
}

# Main execution
main() {
    check_connectivity
    verify_source_data
    create_zfs_dataset
    stop_npm_container
    copy_npm_data
    restart_npm_lxc
    verify_migration
    
    echo ""
    echo -e "${GREEN}=== Migration Complete! ===${NC}"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "1. Update terraform.tfvars with:"
    echo "   npm_data_source = \"$DEV_MOUNT/data\""
    echo "   npm_letsencrypt_source = \"$DEV_MOUNT/letsencrypt\""
    echo ""
    echo "2. Deploy management stack:"
    echo "   cd terraform/management-stack"
    echo "   terraform apply"
    echo ""
    echo "3. Access NPM at: http://192.168.1.70:81"
    echo "   (Use your existing LXC credentials)"
    echo ""
    echo -e "${YELLOW}Note: You may need to reconfigure proxy backends${NC}"
    echo "to point to new IP addresses in your dev environment."
}

# Run main function
main