# NPM Data Migration Playbook

This directory contains infrastructure automation playbooks, including the NPM (Nginx Proxy Manager) data migration utility.

## Overview

The `migrate-npm-data.yml` playbook migrates production NPM configuration data to a freshly deployed management-stack instance. This two-phase approach ensures reliable infrastructure deployment followed by safe data migration.

## Architecture

### Deployment Phases

**Phase 1: Infrastructure Deployment**
- Terraform provisions LXC containers and base infrastructure
- Ansible deploys clean NPM instance via Portainer API
- NPM operational with default credentials (`admin@example.com` / `changeme`)

**Phase 2: Data Migration** 
- Separate Ansible playbook handles production data migration
- Configurable source locations for flexible deployment scenarios
- Safe backup and rollback capabilities

### Why Two Phases?

**Infrastructure First Approach Benefits:**
- **Proven Base**: Ensures NPM container and volumes work correctly before data migration
- **Failure Isolation**: Infrastructure issues separate from data migration issues  
- **Rollback Safety**: Clean backup available before production data replacement
- **Flexible Sources**: Can migrate from various source environments (LXC, Docker, bare metal)

## Playbook: migrate-npm-data.yml

### Purpose
Migrate production NPM data (database, SSL certificates, configuration) from source environment to management-stack deployment.

### Target Architecture
- **Source**: Production NPM deployment (LXC container, Docker, etc.)
- **Destination**: Management-stack container at `192.168.1.70`
- **Data Paths**: `/srv/npm/data` (database, config) and `/srv/npm/letsencrypt` (SSL certificates)

### Interactive Configuration
The playbook prompts for deployment-specific information:

| Prompt | Default | Description |
|--------|---------|-------------|
| Source Host/Container IP | `192.168.1.4` | IP address of source NPM deployment |
| Source Data Path | `/nginx/data` | Path to NPM data directory on source |
| Source Certs Path | `/nginx/certs` | Path to SSL certificates on source |
| Confirmation | `no` | Safety confirmation before migration |

### Migration Process

#### Pre-Migration Validation
1. **Connectivity Test**: Verifies SSH access to source host
2. **Source Verification**: Confirms database exists at specified path
3. **Container Status**: Ensures target NPM container is running
4. **Size Analysis**: Reports source database size for verification

#### Data Migration Steps
1. **Safe Shutdown**: Stops NPM container to prevent corruption
2. **Backup Creation**: Archives current data as rollback point
3. **Database Copy**: Transfers production SQLite database
4. **Configuration Copy**: Migrates keys.json and other config files
5. **Certificate Migration**: Copies SSL certificates and Let's Encrypt data
6. **Container Restart**: Starts NPM with production data
7. **Health Verification**: Confirms NPM accessibility post-migration

#### Data Types Migrated
- **Database**: SQLite database containing all proxy host configurations
- **SSL Certificates**: Let's Encrypt certificates, private keys, renewal configs
- **NPM Keys**: Internal RSA keypair for certificate management
- **Access Configuration**: User accounts, access lists, authentication settings

### Usage

#### Prerequisites
- Management-stack deployed and operational via Terraform
- NPM container running with default configuration
- SSH access to source NPM environment
- Source NPM data accessible and readable

#### Inventory Configuration
Playbook uses dedicated inventory at `inventory/migration.yml`:

```yaml
all:
  hosts:
    management_stack:
      ansible_host: 192.168.1.70
      ansible_user: root
      ansible_ssh_private_key_file: ~/.ssh/id_rsa
```

#### Execution
```bash
cd ansible
ansible-playbook -i inventory/migration.yml 02-infrastructure/migrate-npm-data.yml
```

#### Example Session
```bash
$ ansible-playbook -i inventory/migration.yml 02-infrastructure/migrate-npm-data.yml

Enter the source host/container IP for NPM data [192.168.1.4]: 192.168.1.4
Enter the source path for NPM data [/nginx/data]: /nginx/data  
Enter the source path for NPM certificates [/nginx/certs]: /nginx/certs
This will replace NPM data on 192.168.1.70. Continue? (yes/no) [no]: yes

PLAY [Migrate NPM Production Data] *********************************

TASK [Test connectivity to source host] ***************************
ok: [management_stack]

TASK [Get source database information] ****************************
ok: [management_stack -> 192.168.1.4]

TASK [Display source database info] *******************************
ok: [management_stack] => {
    "msg": [
        "Source database size: 152.0KB",
        "Source database modified: 2024-08-27 08:52:00"
    ]
}

TASK [Stop NPM container for data replacement] ********************
changed: [management_stack]

[... migration tasks continue ...]

TASK [Display migration results] **********************************
ok: [management_stack] => {
    "msg": [
        "Migration completed successfully!",
        "Final database size: 152.0KB", 
        "NPM accessible at: http://192.168.1.70:81",
        "SSL certificates: Migrated",
        "Backup saved to: /tmp/npm-backup-1693834567.tar.gz"
    ]
}
```

### Safety Features

#### Backup and Recovery
- **Automatic Backup**: Creates timestamped archive before migration
- **Rollback Path**: Backup can restore pre-migration state if needed
- **Verification**: Database size comparison confirms successful transfer

#### Error Handling
- **Connectivity Validation**: Fails fast if source unreachable
- **Data Verification**: Confirms source database exists before proceeding  
- **User Confirmation**: Explicit confirmation required before destructive operations
- **Graceful Cleanup**: Removes temporary files on completion or failure

#### Rollback Procedure
If migration fails or produces unexpected results:

```bash
# SSH to management-stack
ssh root@192.168.1.70

# Stop NPM container
docker stop nginx-proxy-manager

# Restore from backup (use actual timestamp from migration output)
tar -xzf /tmp/npm-backup-TIMESTAMP.tar.gz -C /srv/npm/

# Start NPM container  
docker start nginx-proxy-manager
```

### Common Migration Scenarios

#### LXC Container Source
```
Source Host: 192.168.1.4 (LXC container)  
Data Path: /nginx/data
Certs Path: /nginx/certs
```

#### Docker Container Source
```bash
# First extract data from Docker container to filesystem
docker cp npm-container:/data /tmp/npm-source/data
docker cp npm-container:/etc/letsencrypt /tmp/npm-source/certs

# Then migrate using filesystem paths
Source Host: 192.168.1.5 (Docker host)
Data Path: /tmp/npm-source/data
Certs Path: /tmp/npm-source/certs  
```

#### TrueNAS Scale Migration
```
Source Host: 192.168.1.10 (TrueNAS host)
Data Path: /mnt/pool/apps/nginx-proxy-manager/data
Certs Path: /mnt/pool/apps/nginx-proxy-manager/certs
```

### Post-Migration Verification

#### Database Verification
```bash
# Check database size matches source
ssh root@192.168.1.70 'ls -lah /srv/npm/data/database.sqlite'

# Verify table structure (optional)
ssh root@192.168.1.70 'sqlite3 /srv/npm/data/database.sqlite .schema'
```

#### Configuration Verification  
- Access NPM at `http://192.168.1.70:81`
- Login with production credentials (not `admin@example.com`)
- Verify proxy hosts appear in dashboard
- Check SSL certificate status
- Test proxy functionality to backend services

#### SSL Certificate Verification
```bash
# Check certificate files migrated
ssh root@192.168.1.70 'find /srv/npm/letsencrypt -name "*.pem" | wc -l'

# Verify certificate validity
ssh root@192.168.1.70 'find /srv/npm/letsencrypt/live -name "cert.pem" -exec openssl x509 -in {} -text -noout \;'
```

### Troubleshooting

#### Migration Fails - Connectivity Issues
```bash
# Test SSH access manually
ssh root@192.168.1.4 'ls -la /nginx/data/'

# Check source database permissions  
ssh root@192.168.1.4 'ls -la /nginx/data/database.sqlite'
```

#### Migration Succeeds But NPM Won't Start
```bash
# Check container logs
docker logs nginx-proxy-manager

# Verify file permissions
ls -la /srv/npm/data/

# Common fix - ownership issues
chown -R root:root /srv/npm/
```

#### Database Size Mismatch
```bash
# Compare source and destination
ssh root@192.168.1.4 'stat -c%s /nginx/data/database.sqlite'
ssh root@192.168.1.70 'stat -c%s /srv/npm/data/database.sqlite'

# If different, re-run migration or restore from backup
```

#### SSL Certificates Not Working
```bash
# Check certificate directory structure
ssh root@192.168.1.70 'find /srv/npm/letsencrypt -type f -name "*.pem"'

# Verify NPM can read certificates
docker exec nginx-proxy-manager ls -la /etc/letsencrypt/live/
```

### Integration with Infrastructure Pipeline

#### Terraform Integration
The migration playbook integrates with the broader infrastructure deployment:

```bash
# Complete deployment workflow
cd terraform/management-stack
terraform apply                    # Deploy infrastructure

cd ../../ansible  
ansible-playbook -i inventory/migration.yml 02-infrastructure/migrate-npm-data.yml    # Migrate data
```

#### CI/CD Integration
For automated deployments, the migration can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions step
- name: Migrate NPM Production Data
  run: |
    cd ansible
    echo "yes" | ansible-playbook -i inventory/migration.yml \
      02-infrastructure/migrate-npm-data.yml \
      -e source_host=${{ env.SOURCE_NPM_HOST }} \
      -e source_path=${{ env.SOURCE_NPM_PATH }}
```

### Security Considerations

#### Credential Protection
- NPM database contains encrypted passwords and API keys
- SSL private keys require secure transport and storage
- Migration occurs over SSH with key-based authentication
- Temporary files cleaned up automatically

#### Network Security  
- Migration traffic flows over SSH (encrypted)
- Source systems require SSH access from management-stack
- Consider VPN or secure network segments for production migrations

#### Access Control
- Migration requires root access on both source and destination
- SSH keys should be properly secured and rotated regularly
- Consider using dedicated migration user with minimal required permissions

### Performance Considerations

#### Network Bandwidth
- Database transfers typically < 1MB (fast)
- SSL certificate directories may be larger (multiple domains)
- Large certificate archives may take several minutes

#### Downtime Window
- NPM container stopped during migration (typically 1-2 minutes)
- Proxy services unavailable during this window
- Plan migration during maintenance windows for production systems

#### Storage Requirements
- Backup archives stored in `/tmp` (cleaned automatically)
- Ensure sufficient disk space for backup + migration data
- Consider backup retention policy for production environments

## Related Documentation

- [Management Stack Deployment](../../terraform/management-stack/README.md)
- [NPM Container Architecture](../../terraform/ansible/shared-roles/nginx_proxy_manager/README.md)
- [Infrastructure Overview](../README.md)