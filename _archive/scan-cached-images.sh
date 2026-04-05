#!/bin/bash
# scan-cached-images.sh

REGISTRY="192.168.1.70"
TRIVY_SERVER="http://192.168.1.70:4954"

echo "Scanning all cached images..."

# Get all cached repositories
curl -s http://$REGISTRY/v2/_catalog | jq -r '.repositories[]' | while read repo; do
    # Get all tags for each repository
    curl -s http://$REGISTRY/v2/$repo/tags/list | jq -r '.tags[]' | while read tag; do
        IMAGE="$REGISTRY/$repo:$tag"
        echo "Scanning: $IMAGE"
        
        # Scan and save results
        trivy image --server $TRIVY_SERVER --severity HIGH,CRITICAL $IMAGE
    done
done
