# File: docs/troubleshooting/vm-reset-recovery.md

# VM Reset Recovery Procedures

This document provides step-by-step procedures for recovering from Proxmox test VM resets or snapshots that lose automation configuration.

## When You Need This Guide

- After restoring a Proxmox VM from a snapshot
- After reinstalling Proxmox VE from scratch
- When automation fails due to missing users or configuration
- Before testing major infrastructure changes (establish known good state)

## Quick Recovery Checklist

```bash
# 1. Validate current state
./scripts/check-proxmox-status.sh

# 2. Apply baseline configuration
cd ansible
ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml

# 3. Set PVE user password manually
ssh root@pvetest.gibbsgreatly.xyz "pveum passwd automation@pve"

# 4. Update .env file with password
nano .env  # Set PROXMOX_PASSWORD=your-chosen-password

# 5. Validate recovery
./scripts/check-proxmox-status.sh
```

## Detailed Recovery Process

### Step 1: Assess Current State

Run the validation script to understand what's missing:
```bash
./scripts/check-proxmox-status.sh
```

Common failure patterns after reset:
- SSH access as automation user fails
- API authentication fails
- Proxmox configuration checks fail (repos, nag, users)

### Step 2: Apply Baseline Configuration

The base-config.yml playbook is idempotent and safe to run multiple times:

```bash
cd ansible
ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml
```

This playbook will:
- Fix repository configuration
- Remove subscription nag
- Create automation system user with SSH keys
- Create automation@pve API user (without password)
- Install required packages
- Configure sudo privileges

### Step 3: Manual Password Configuration

The playbook creates the PVE user but doesn't set a password for security reasons:

```bash
ssh root@pvetest.gibbsgreatly.xyz "pveum passwd automation@pve"
```

Choose a secure password and remember it for the .env file.

### Step 4: Update Environment Configuration

Edit your .env file to match the password you just set:
```bash
# Ensure these match your manual configuration
PROXMOX_HOST=pvetest.gibbsgreatly.xyz
PROXMOX_USER=automation@pve
PROXMOX_PASSWORD=your-chosen-password
```

### Step 5: Validate Complete Recovery

Run the validation script again:
```bash
./scripts/check-proxmox-status.sh
```

Expected result: All checks should pass with green checkmarks.

## Troubleshooting Recovery Issues

### SSH Access Problems

If SSH access still fails after running the playbook:

```bash
# Manually copy SSH key to automation user
ssh root@pvetest.gibbsgreatly.xyz "mkdir -p /home/automation/.ssh"
ssh root@pvetest.gibbsgreatly.xyz "chown automation:automation /home/automation/.ssh"
ssh root@pvetest.gibbsgreatly.xyz "chmod 700 /home/automation/.ssh"
cat ~/.ssh/id_rsa.pub | ssh root@pvetest.gibbsgreatly.xyz "cat > /home/automation/.ssh/authorized_keys"
ssh root@pvetest.gibbsgreatly.xyz "chown automation:automation /home/automation/.ssh/authorized_keys"
ssh root@pvetest.gibbsgreatly.xyz "chmod 600 /home/automation/.ssh/authorized_keys"
```

### API Authentication Problems

If API authentication fails:

1. Test manual authentication:
   ```bash
   curl -k -d "username=automation@pve&password=your-password" \
     https://pvetest.gibbsgreatly.xyz:8006/api2/json/access/ticket
   ```

2. Verify PVE user exists and has permissions:
   ```bash
   ssh root@pvetest.gibbsgreatly.xyz "pveum user list | grep automation"
   ssh root@pvetest.gibbsgreatly.xyz "pveum acl list | grep automation"
   ```

3. Reset PVE user if needed:
   ```bash
   ssh root@pvetest.gibbsgreatly.xyz "pveum user delete automation@pve"
   # Then re-run the base-config.yml playbook
   ```

### Repository Problems

If repository configuration fails:

```bash
# Manual repository fix
ssh root@pvetest.gibbsgreatly.xyz "
  # Disable enterprise repo
  sed -i 's/^/# /' /etc/apt/sources.list.d/pve-enterprise.sources

  # Add no-subscription repo
  cat > /etc/apt/sources.list.d/proxmox.sources << 'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF

  # Update package cache
  apt update
"
```

## Prevention Strategies

### Before Making Major Changes

1. Create VM snapshot with descriptive name
2. Document current working configuration
3. Run validation script to establish baseline
4. Test recovery procedure in non-critical environment

### Regular Maintenance

- Run validation script weekly: `./scripts/check-proxmox-status.sh`
- Update base-config.yml playbook when making manual changes
- Keep .env file backed up securely
- Document any manual configurations that need automation

## Recovery Time Expectations

- **Quick recovery** (known good playbook): 2-3 minutes
- **Troubleshooting required**: 10-15 minutes
- **Major issues requiring manual intervention**: 30+ minutes

## Integration with Testing Workflow

Use this recovery process as part of infrastructure testing:

1. **Pre-test**: Validate current state, create snapshot
2. **Test**: Run destructive tests or major changes
3. **Recovery**: Use this procedure to return to known good state
4. **Validate**: Confirm recovery before next test cycle

This procedure enables confident testing by providing reliable restoration capability.
