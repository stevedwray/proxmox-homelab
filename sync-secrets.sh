#!/bin/bash
# sync-secrets.sh (working version + optional auto-source)

ORG_ID="03cd75dc-3db4-4b2e-8ecc-af86014151a7"

ENV_VARS=(
    "PROXMOX_TOKEN_ID"
    "PROXMOX_TOKEN_SECRET"
    "ANSIBLE_VAULT_PASSWORD"
    "SERVICE_PASSWORD"
    "ANTHROPIC_API_KEY"
)

# Start with the template
if [ -f ".env.template" ]; then
    cp .env.template .env
    echo "Starting with .env.template..."
else
    echo "# Generated from Bitwarden on $(date)" > .env
    echo "Warning: No .env.template found, creating minimal .env"
fi

echo "Syncing secrets from Bitwarden..."

for env_var in "${ENV_VARS[@]}"; do
    value=$(bw get password "$env_var" --organizationid $ORG_ID 2>/dev/null)
    if [ ! -z "$value" ] && [ "$value" != "null" ]; then
        echo "Processing $env_var..."
        
        # More robust replacement - handle different quote styles
        if grep -q "$env_var.*__FROM_BITWARDEN__" .env; then
            # Replace the placeholder, preserving the line structure
            sed -i "s|${env_var}='__FROM_BITWARDEN__'|${env_var}='${value}'|g" .env
            sed -i "s|${env_var}=\"__FROM_BITWARDEN__\"|${env_var}=\"${value}\"|g" .env
            sed -i "s|${env_var}=__FROM_BITWARDEN__|${env_var}='${value}'|g" .env
            echo "✅ Replaced $env_var in template"
        else
            # If not found in template, append it
            echo "export $env_var='$value'" >> .env
            echo "✅ Added $env_var to end of file"
        fi
    else
        echo "⚠️  Missing: $env_var"
    fi
done

echo "Environment synced to .env"
#echo "Current .env content:"
#echo "===================="
#cat .env
