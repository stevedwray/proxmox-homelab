#!/bin/bash
# populate-bitwarden.sh — Push secrets from .env into Bitwarden
set -euo pipefail

ORG_ID="03cd75dc-3db4-4b2e-8ecc-af86014151a7"
COLLECTION_ID="fa8ec932-22d8-4b7e-b13f-b349013d627b"

ENV_VARS=(
    "PROXMOX_TOKEN_SECRET"
    "ANSIBLE_VAULT_PASSWORD"
    "SERVICE_PASSWORD"
    "ANTHROPIC_API_KEY"
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

if [ ! -f ".env" ]; then
    echo "❌ No .env file found. Create one first."
    exit 1
fi

source .env

echo "Pushing secrets to Bitwarden..."

for env_var in "${ENV_VARS[@]}"; do
    value="${!env_var:-}"

    if [ -z "$value" ]; then
        echo "⚠️  Skipping $env_var - not set"
        continue
    fi

    # Build JSON safely using jq to avoid injection
    json=$(jq -n \
        --arg name "$env_var" \
        --arg org "$ORG_ID" \
        --arg coll "$COLLECTION_ID" \
        --arg pw "$value" \
        '{
            type: 1,
            name: $name,
            organizationId: $org,
            collectionIds: [$coll],
            login: { username: null, password: $pw }
        }')

    # Check if item already exists
    existing_id=$(bw list items --search "$env_var" --organizationid "$ORG_ID" 2>/dev/null \
        | jq -r ".[] | select(.name == \"$env_var\") | .id" | head -1)

    if [ -n "$existing_id" ]; then
        echo "🔄 Updating: $env_var"
        echo "$json" | bw encode | bw edit item "$existing_id" --quiet
    else
        echo "📝 Creating: $env_var"
        echo "$json" | bw encode | bw create item --quiet
    fi

    if [ $? -eq 0 ]; then
        echo "   ✅ Done"
    else
        echo "   ❌ Failed"
    fi
done

echo ""
echo "Done! Check your HomeLab collection."