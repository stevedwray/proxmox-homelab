#!/usr/bin/env bash
# Restore Portainer from the latest NAS backup after a fresh terragrunt apply.
# Must run BEFORE provision.sh — POST /api/restore only works on an uninitialised instance.
#
# Usage:
#   export TASK_APPROVAL="<task-name>"
#   ./with-secrets-prod scripts/portainer-restore.sh
#
# Environment (resolved by with-secrets-prod):
#   LAB_IP_PORTAINER       — Portainer LXC IP (e.g. 192.168.20.20)
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

# Step 1: wait for fresh instance
wait_for_api "Waiting for Portainer API to be reachable"

INSTANCE_BEFORE=$(curl -sf --max-time 5 \
    "http://${PORTAINER_IP}:${PORTAINER_PORT}/api/system/status" | jq -r .InstanceID)
echo "InstanceID (new instance): ${INSTANCE_BEFORE}"
echo ""

# Step 2: find latest backup on NAS via pve SSH
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

# Step 3: restore (no auth — instance is uninitialised)
echo "POSTing restore..."
HTTP=$(ssh root@"${PVE_HOST}" \
    "curl -sf --max-time 30 -X POST http://${PORTAINER_IP}:${PORTAINER_PORT}/api/restore \
     -F 'file=@${BACKUP}' -o /dev/null -w '%{http_code}'")
echo "Restore response: HTTP ${HTTP}"
if [[ "$HTTP" != "200" ]]; then
    echo "ERROR: restore failed — check that the instance is still uninitialised"
    echo "       (provision.sh must NOT have run before this script)"
    exit 1
fi
echo ""

# Step 4: restart to load restored DB
echo "Restarting Portainer container to apply restored database..."
ssh root@"${PVE_HOST}" "pct exec ${PORTAINER_VMID} -- docker restart ${CONTAINER_NAME}"
sleep 8

# Step 5: wait for it to come back up
wait_for_api "Waiting for Portainer API after restart"
echo ""

# Step 6: verify InstanceID changed
INSTANCE_AFTER=$(curl -sf --max-time 5 \
    "http://${PORTAINER_IP}:${PORTAINER_PORT}/api/system/status" | jq -r .InstanceID)
echo "InstanceID (restored):     ${INSTANCE_AFTER}"

if [[ "$INSTANCE_BEFORE" == "$INSTANCE_AFTER" ]]; then
    echo "WARN: InstanceID unchanged — this may indicate the restore did not apply"
else
    echo "OK: InstanceID changed — database restored from backup"
fi
echo ""

# Step 7: provision (init play gets 409 and skips; everything else is idempotent)
echo "=== Running provision.sh --stack portainer-stack ==="
"${SCRIPT_DIR}/provision.sh" --stack portainer-stack
