#!/bin/bash
# sync-secrets.sh — Pull secrets from Bitwarden into .env
set -euo pipefail
export NODE_NO_WARNINGS=1

ORG_ID="03cd75dc-3db4-4b2e-8ecc-af86014151a7"

ENV_VARS=(
    "PROXMOX_TOKEN_SECRET"
    "SERVICE_PASSWORD"
    "PORTAINER_ADMIN_PASSWORD"
    "ANTHROPIC_API_KEY"
    "NETBOX_DB_PASSWORD"
    "NETBOX_REDIS_PASSWORD"
    "NETBOX_REDIS_CACHE_PASSWORD"
    "NETBOX_SECRET_KEY"
    "NETBOX_API_TOKEN_PEPPER"
    "NETBOX_SUPERUSER_PASSWORD"
    "NETBOX_SUPERUSER_API_TOKEN"
    "MIKROTIK_USER"
    "MIKROTIK_PASSWORD"
    "SONAR_TOKEN"
    "SNYK_TOKEN"
    "SOPS_AGE_KEY"
)

# Check that bw is available and unlocked
if ! command -v bw &>/dev/null; then
    echo "❌ Bitwarden CLI (bw) is not installed."
    exit 1
fi

if ! bw status 2>/dev/null | grep -q '"status":"unlocked"'; then
    echo "❌ Bitwarden vault is locked. Run: export BW_SESSION=\$(bw unlock --raw)"
    exit 1
fi

if ! command -v jq &>/dev/null; then
    echo "❌ jq is not installed."
    exit 1
fi

# Start with the template
if [[ -f ".env.template" ]]; then
    cp .env.template .env
    echo "Starting with .env.template..."
else
    echo "# Generated from Bitwarden on $(date)" > .env
    echo "Warning: No .env.template found, creating minimal .env"
fi

echo "Syncing secrets from Bitwarden..."

bw sync >/dev/null

shell_single_quote() {
    local value="$1"
    printf "'%s'" "$(printf '%s' "$value" | sed "s/'/'\\\\''/g")"
    return 0
}

for env_var in "${ENV_VARS[@]}"; do
    value=$(
        bw list items --search "$env_var" 2>/dev/null \
            | jq -r --arg name "$env_var" --arg org "$ORG_ID" '
                .[]
                | select(.name == $name and .organizationId == $org)
                | .login.password
            ' \
            | head -n1
    )
    if [[ -n "$value" && "$value" != "null" ]]; then
        echo "Processing $env_var..."

        quoted_value=$(shell_single_quote "$value")
        escaped_value=$(printf '%s\n' "$quoted_value" | sed 's/[&/\]/\\&/g')

        if grep -q "${env_var}=.*__FROM_BITWARDEN__" .env; then
            # Replace the placeholder line entirely with a shell-safe single-quoted value.
            sed -i "s|${env_var}=.*__FROM_BITWARDEN__.*|${env_var}=${escaped_value}|" .env
            echo "✅ Replaced $env_var in template"
        else
            # If not found in template, append it
            echo "export ${env_var}=${quoted_value}" >> .env
            echo "✅ Added $env_var to end of file"
        fi
    else
        echo "⚠️  Missing: $env_var (not found in Bitwarden)"
    fi
done

echo ""
echo "Environment synced to .env"
echo "Run: source .env"
