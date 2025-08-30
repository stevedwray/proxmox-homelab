#!/bin/bash
# sync-secrets.sh (updated to merge template)

ORG_ID="03cd75dc-3db4-4b2e-8ecc-af86014151a7"

ENV_VARS=(
    "PROXMOX_TOKEN_ID"
    "PROXMOX_TOKEN_SECRET"
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
        # Replace placeholder in template with actual value
        if grep -q "__FROM_BITWARDEN__" .env; then
            sed -i "s|export $env_var='__FROM_BITWARDEN__'|export $env_var='$value'|g" .env
        else
            # If not in template, append it
            echo "export $env_var='$value'" >> .env
        fi
        echo "✅ $env_var"
    else
        echo "⚠️  Missing: $env_var"
    fi
done

echo "Environment synced to .env (template + secrets)"
