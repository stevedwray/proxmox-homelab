#!/bin/bash
# populate-bitwarden.sh

ORG_ID="03cd75dc-3db4-4b2e-8ecc-af86014151a7"
COLLECTION_ID="fa8ec932-22d8-4b7e-b13f-b349013d627b"

ENV_VARS=(
    "PROXMOX_TOKEN_ID"
    "PROXMOX_TOKEN_SECRET"
    "SERVICE_PASSWORD"
    "ANTHROPIC_API_KEY"
)

source .env

echo "Starting migration using bw encode..."

for env_var in "${ENV_VARS[@]}"; do
    value="${!env_var}"
    
    if [ -z "$value" ]; then
        echo "⚠️  Skipping $env_var - not set"
        continue
    fi
    
    echo "📝 Creating: $env_var"
    
    # Create JSON file for this item
    cat > temp_item.json << EOF
{
  "type": 1,
  "name": "$env_var",
  "organizationId": "$ORG_ID",
  "collectionIds": ["$COLLECTION_ID"],
  "login": {
    "username": null,
    "password": "$value"
  }
}
EOF

    # Use bw encode to create the item
    bw encode < temp_item.json | bw create item --quiet
    
    if [ $? -eq 0 ]; then
        echo "   ✅ Created"
    else
        echo "   ❌ Failed"
    fi
    
    # Clean up temp file
    rm temp_item.json
done

echo "Done! Check your HomeLab collection."