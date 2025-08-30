# Homelab Secrets Management

A secure way to manage Terraform and Ansible secrets using Bitwarden, designed to be resilient against accidental directory deletion while keeping secrets out of git.

## Quick Start

### 1. Get Your Secrets

```bash
# Clone the repository
git clone <your-repo-url>
cd proxmox-homelab

# Login to Bitwarden (one-time setup)
bw login homelab@gibbsgreatly.xyz

# Unlock and sync secrets
export BW_SESSION=$(bw unlock --raw)
./sync-secrets.sh

# Load environment variables
source .env

# Now run your infrastructure commands
terraform plan
ansible-playbook playbook.yml
```

### 2. Daily Workflow

```bash
cd proxmox-homelab

# If session expired, unlock again
export BW_SESSION=$(bw unlock --raw)

# Pull latest secrets (in case they were updated)
./sync-secrets.sh
source .env

# Work with your infrastructure
terraform apply
```

## Managing Secrets

### Adding New Secrets

**Option 1: Via Web Interface (Recommended)**
1. Login to [vault.bitwarden.com](https://vault.bitwarden.com) with your main account
2. Navigate to "Wray Family" organization → "Homelab" collection
3. Create new **Login** item
4. Set name to your environment variable name (e.g., `NEW_API_KEY`)
5. Put the secret value in the **Password** field
6. Save the item

**Option 2: Via Script**
1. Add your secret to your current `.env` file
2. Add the variable name to the `ENV_VARS` array in `populate-bitwarden.sh`
3. Run `./populate-bitwarden.sh`

After adding secrets either way:
```bash
# Update the sync script to include the new variable
# Edit sync-secrets.sh and add "NEW_API_KEY" to ENV_VARS array

# Pull the new secret
./sync-secrets.sh
source .env
```

### Updating Existing Secrets

**Via Web Interface:**
1. Login to vault.bitwarden.com with your main account
2. Find the secret in "Wray Family" → "Homelab" collection
3. Edit the item and update the password field
4. Save

**Then sync locally:**
```bash
./sync-secrets.sh
source .env
```

### Removing Secrets

1. Delete the item from Bitwarden web interface
2. Remove the variable name from `ENV_VARS` arrays in both scripts
3. Remove any references from `.env.template`

## Repository Structure

```
proxmox-homelab/
├── .env.template          # Template showing required secrets (committed)
├── .env                   # Generated file with actual secrets (ignored)
├── sync-secrets.sh        # Pulls secrets from Bitwarden
├── populate-bitwarden.sh  # Pushes secrets to Bitwarden
├── .gitignore            # Excludes .env and temp files
└── terraform/ansible files...
```

## Files Explained

### `.env.template`
Shows the structure of required environment variables. Contains placeholder values and non-secret configuration. **This is committed to git** so team members know what secrets are needed.

```bash
# Secret values (populated by sync-secrets.sh)
export PROXMOX_TOKEN_ID='__FROM_BITWARDEN__'
export PROXMOX_TOKEN_SECRET='__FROM_BITWARDEN__'

# Non-secret configuration
export TF_VAR_pm_api_url='https://proxmox.local:8006/api2/json'
export ANSIBLE_HOST_KEY_CHECKING=False
```

### `.env`
Generated file containing actual secret values. **This is never committed to git**. Recreated each time you run `sync-secrets.sh`.

### `sync-secrets.sh`
Pulls secrets from Bitwarden and generates a complete `.env` file by:
1. Starting with your `.env.template`
2. Replacing `__FROM_BITWARDEN__` placeholders with actual secrets
3. Preserving all non-secret configuration

### `populate-bitwarden.sh`
Migration tool to push existing environment variables into Bitwarden. Used when:
- Setting up the system initially
- Adding new secrets via script instead of web interface

## How It Works

### The Problem This Solves
- **Lost secrets**: Accidentally deleting your project directory meant losing `.env` files with secrets
- **No backup**: Secrets weren't backed up anywhere safe
- **Not in git**: Couldn't commit secrets to version control for obvious security reasons
- **Manual recreation**: Had to manually recreate secret files after `git clone`

### The Solution
1. **Bitwarden as backend**: All secrets stored encrypted in Bitwarden
2. **Separate account**: Uses `homelab@gibbsgreatly.xyz` account for isolation
3. **Organization sharing**: Secrets shared via "Wray Family" organization's "Homelab" collection
4. **Template approach**: `.env.template` in git shows structure, actual `.env` generated from secrets
5. **CLI automation**: Scripts handle the sync automatically

### Security Model
- **Homelab account**: Has CLI access to read secrets but limited web UI access
- **Main account**: Full control via web interface for managing secrets
- **Bitwarden encryption**: All secrets encrypted at rest and in transit
- **No plaintext in git**: Only templates and scripts are committed
- **Local isolation**: Generated `.env` file only exists on your machine

### Why Login Items Instead of Secure Notes?
The Bitwarden CLI has better support for reading login item passwords than secure note content. Each secret is stored as a login item with the secret value in the password field.

## Troubleshooting

### "Command not found: bw"
Install the Bitwarden CLI:
```bash
# Download and install
curl -L https://github.com/bitwarden/clients/releases/download/cli-v2024.8.1/bw-linux-2024.8.1.zip -o bw.zip
unzip bw.zip
chmod +x bw
sudo mv bw /usr/local/bin/
```

### "Session expired" or authentication issues
```bash
# Check status
bw status

# Re-unlock if needed
export BW_SESSION=$(bw unlock --raw)
```

### Missing secrets in generated `.env`
```bash
# Check if secret exists in Bitwarden
bw get item "SECRET_NAME" --organizationid 03cd75dc-3db4-4b2e-8ecc-af86014151a7

# Verify it's in the ENV_VARS array in sync-secrets.sh
```

### Special characters in secrets
The scripts handle special characters (like `!`, `$`, `*`) by wrapping values in single quotes. This prevents shell interpretation issues.

## Security Notes

- The `homelab@gibbsgreatly.xyz` account can read secrets via CLI but cannot see/edit them in the web interface
- Session tokens expire after a period of inactivity
- Always use `bw logout` when finished if working on a shared machine
- The `.env` file contains plaintext secrets - ensure it's in `.gitignore`
- Consider using `shred .env` instead of `rm .env` on sensitive systems

## Benefits

✅ **Resilient**: Secrets survive directory deletion  
✅ **Backed up**: Bitwarden handles backup and sync  
✅ **Version controlled**: Structure documented in git  
✅ **Secure**: Encrypted storage, isolated access  
✅ **Automated**: One command to sync all secrets  
✅ **Portable**: Works on any machine with Bitwarden CLI