#!/bin/bash
# populate-bitwarden.sh — Push secrets from .env into Bitwarden
set -euo pipefail

ORG_ID="03cd75dc-3db4-4b2e-8ecc-af86014151a7"
COLLECTION_ID="fa8ec932-22d8-4b7e-b13f-b349013d627b"

ENV_VARS=(
    "PROXMOX_TOKEN_SECRET"
    "SERVICE_PASSWORD"
    "PORTAINER_ADMIN_PASSWORD"
    "ANTHROPIC_API_KEY"
    "HARBOR_DOCKERHUB_USERNAME"
    "HARBOR_DOCKERHUB_PASSWORD"
    "NETBOX_DB_PASSWORD"
    "NETBOX_REDIS_PASSWORD"
    "NETBOX_REDIS_CACHE_PASSWORD"
    "NETBOX_SECRET_KEY"
    "NETBOX_API_TOKEN_PEPPER"
    "NETBOX_SUPERUSER_PASSWORD"
    "NETBOX_SUPERUSER_API_TOKEN"
    "MIKROTIK_USER"
    "MIKROTIK_PASSWORD"
)

# Check that bw is available and unlocked
if ! command -v bw &>/dev/null; then
    echo "❌ Bitwarden CLI (bw) is not installed."
    exit 1
fi

if ! command -v jq &>/dev/null; then
    echo "❌ jq is not installed."
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

created_count=0
updated_count=0
skipped_count=0
moved_count=0

for env_var in "${ENV_VARS[@]}"; do
    value="${!env_var:-}"

    if [ -z "$value" ]; then
        echo "⚠️  Skipping $env_var - not set"
        skipped_count=$((skipped_count + 1))
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
    existing_item=$(bw list items --search "$env_var" 2>/dev/null \
        | jq -r ".[] | select(.name == \"$env_var\") | [.id, (.organizationId // \"\")] | @tsv" | head -1)
    existing_id=$(printf '%s\n' "$existing_item" | cut -f1)
    existing_org_id=$(printf '%s\n' "$existing_item" | cut -f2)

    if [ -n "$existing_id" ]; then
        echo "🔄 Updating: $env_var"
        echo "$json" | bw encode | bw edit item "$existing_id" --quiet
        updated_count=$((updated_count + 1))
    else
        echo "📝 Creating: $env_var"
        created_item=$(echo "$json" | bw encode | bw create item --quiet)
        existing_id=$(printf '%s\n' "$created_item" | jq -r '.id')
        existing_org_id=""
        created_count=$((created_count + 1))
    fi

    if [ "${existing_org_id:-}" != "$ORG_ID" ]; then
        echo "📦 Moving to organization: $env_var"
        move_payload=$(jq -nc --arg coll "$COLLECTION_ID" '[$coll]')
        echo "$move_payload" | bw encode | bw move "$existing_id" "$ORG_ID" --quiet
        moved_count=$((moved_count + 1))
    fi

    if [ $? -eq 0 ]; then
        echo "   ✅ Done"
    else
        echo "   ❌ Failed"
    fi
done

echo ""
echo "Summary: created=$created_count updated=$updated_count moved=$moved_count skipped=$skipped_count"
echo "Done! Check your HomeLab collection."
