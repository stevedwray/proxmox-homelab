#!/usr/bin/env bash
# Restore Portainer from the latest NAS backup after a fresh terragrunt apply.
#
# Sequence:
#   1. Run provision.sh --tags pre_restore  (Docker base + Portainer CE start, no init)
#   2. Wait for uninitialized Portainer API
#   3. POST /api/restore from latest NAS backup
#   4. Restart Portainer container to load restored DB
#   5. Run provision.sh (full — init gets 409, skips; everything else idempotent)
#
# Usage:
#   export TASK_APPROVAL="<task-name>"
#   ./with-secrets-prod scripts/portainer-restore.sh
#
# Environment (resolved by with-secrets-prod):
#   LAB_IP_PORTAINER         — Portainer LXC IP
#   PORTAINER_ADMIN_PASSWORD — admin password (used by provision.sh after restore)

set -euo pipefail

PORTAINER_IP="${LAB_IP_PORTAINER:-192.168.20.20}"
PORTAINER_PORT="9000"
PORTAINER_VMID="20020"
PVE_HOST="pve.gibbsgreatly.xyz"
NAS_BACKUP_DIR="/mnt/nas-backup/portainer-backup"
CONTAINER_NAME="portainer-portainer-1"
WAIT_TIMEOUT=180

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------

wait_for_api() {
    local label="$1"
    local url="http://${PORTAINER_IP}:${PORTAINER_PORT}/api/system/status"
    local deadline=$(( $(date +%s) + WAIT_TIMEOUT ))
    echo -n "${label}"
    while true; do
        if curl -sf --max-time 5 "$url" > /dev/null 2>&1; then
            echo " OK"
            return 0
        fi
        if [[ $(date +%s) -ge $deadline ]]; then
            echo " TIMEOUT after ${WAIT_TIMEOUT}s"
            return 1
        fi
        echo -n "."
        sleep 5
    done
}

# ---------------------------------------------------------------------------

echo "=== Portainer Restore ==="
echo "Target:  http://${PORTAINER_IP}:${PORTAINER_PORT}"
echo "PVE:     ${PVE_HOST}  (VMID ${PORTAINER_VMID})"
echo ""

# Step 1: start Portainer CE without initialising
echo "=== Phase 1: deploy Docker base + Portainer CE (no init) ==="
ANSIBLE_TAGS="pre_restore" "${SCRIPT_DIR}/provision.sh" --stack portainer-stack
echo ""

# Step 2: wait for fresh uninitialized instance
wait_for_api "Waiting for Portainer API (uninitialized)"

INSTANCE_BEFORE=$(curl -sf --max-time 5 \
    "http://${PORTAINER_IP}:${PORTAINER_PORT}/api/system/status" | jq -r .InstanceID)
echo "InstanceID (new instance): ${INSTANCE_BEFORE}"
echo ""

# Step 3: find latest backup on NAS via pve SSH
echo "Finding latest backup on NAS..."
BACKUP=$(ssh root@"${PVE_HOST}" \
    "ls -t ${NAS_BACKUP_DIR}/portainer-*.tar.gz 2>/dev/null | head -1")
if [[ -z "$BACKUP" ]]; then
    echo "ERROR: no backup found in ${NAS_BACKUP_DIR} on ${PVE_HOST}"
    exit 1
fi
BACKUP_SIZE=$(ssh root@"${PVE_HOST}" "du -sh ${BACKUP} | cut -f1")
echo "Restoring from: ${BACKUP} (${BACKUP_SIZE})"
echo ""

# Step 4: restore (no auth — instance is uninitialised)
echo "POSTing restore..."
HTTP=$(ssh root@"${PVE_HOST}" \
    "curl -sf --max-time 30 -X POST http://${PORTAINER_IP}:${PORTAINER_PORT}/api/restore \
     -F 'file=@${BACKUP}' -o /dev/null -w '%{http_code}'")
echo "Restore response: HTTP ${HTTP}"
if [[ "$HTTP" != "200" ]]; then
    echo "ERROR: restore failed (HTTP ${HTTP})"
    exit 1
fi
echo ""

# Step 5: restart to load restored DB
echo "Restarting Portainer container..."
ssh root@"${PVE_HOST}" "pct exec ${PORTAINER_VMID} -- docker restart ${CONTAINER_NAME}"
sleep 8

# Step 6: wait for it to come back up
wait_for_api "Waiting for Portainer API after restart"
echo ""

# Step 7: verify InstanceID changed to match backup
INSTANCE_AFTER=$(curl -sf --max-time 5 \
    "http://${PORTAINER_IP}:${PORTAINER_PORT}/api/system/status" | jq -r .InstanceID)
echo "InstanceID (restored): ${INSTANCE_AFTER}"
if [[ "$INSTANCE_BEFORE" == "$INSTANCE_AFTER" ]]; then
    echo "WARN: InstanceID unchanged — restore may not have applied"
else
    echo "OK: InstanceID changed — database restored from backup"
fi
echo ""

# Step 8: full provision (init gets 409 and skips; OAuth, bind mount, timer all idempotent)
echo "=== Phase 2: full provision (init + OAuth + backup timer) ==="
"${SCRIPT_DIR}/provision.sh" --stack portainer-stack
