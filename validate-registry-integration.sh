#!/bin/bash
# validate-registry-integration.sh
# Run this script on agent containers to validate registry integration

set -e

REGISTRY_IP="${1:-192.168.1.70}"
TEST_IMAGE="alpine:latest"

echo "=== Registry Integration Validation ==="
echo "Registry IP: $REGISTRY_IP"
echo "Test Image: $TEST_IMAGE"
echo ""

# Check Docker daemon configuration
echo "1. Checking Docker daemon configuration..."
if [ -f /etc/docker/daemon.json ]; then
    echo "✓ daemon.json exists"
    if grep -q "registry-mirrors" /etc/docker/daemon.json; then
        echo "✓ Registry mirrors configured"
        cat /etc/docker/daemon.json | jq .
    else
        echo "✗ No registry mirrors found in daemon.json"
        exit 1
    fi
else
    echo "✗ daemon.json not found"
    exit 1
fi

# Check Docker info shows mirrors
echo ""
echo "2. Checking Docker info for registry mirrors..."
DOCKER_INFO=$(docker info 2>/dev/null | grep -A 5 "Registry Mirrors" || echo "No mirrors found")
echo "$DOCKER_INFO"

if echo "$DOCKER_INFO" | grep -q "$REGISTRY_IP"; then
    echo "✓ Registry mirror active in Docker daemon"
else
    echo "✗ Registry mirror not active"
fi

# Test registry connectivity
echo ""
echo "3. Testing registry connectivity..."
if curl -s "http://$REGISTRY_IP/v2/" > /dev/null; then
    echo "✓ Registry is accessible"
else
    echo "✗ Registry not accessible"
    exit 1
fi

# Test image pull through cache
echo ""
echo "4. Testing image pull through cache..."
echo "Removing local image if exists..."
docker rmi "$TEST_IMAGE" 2>/dev/null || true

echo "Pulling image (should cache to registry)..."
docker pull "$TEST_IMAGE"

# Check if image appears in registry catalog
echo ""
echo "5. Checking registry catalog for cached image..."
CATALOG=$(curl -s "http://$REGISTRY_IP/v2/_catalog")
echo "Registry catalog: $CATALOG"

if echo "$CATALOG" | grep -q "library/alpine"; then
    echo "✓ Image successfully cached in registry"
else
    echo "⚠ Image not yet visible in catalog (may take time)"
fi

# Show registry storage
echo ""
echo "6. Registry repository list:"
curl -s "http://$REGISTRY_IP/v2/_catalog" | jq -r '.repositories[]' 2>/dev/null || echo "No repositories visible yet"

echo ""
echo "=== Validation Complete ==="
echo "If all checks passed, your agent is successfully integrated with the registry cache."
