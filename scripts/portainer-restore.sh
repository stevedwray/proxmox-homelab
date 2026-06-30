#!/usr/bin/env bash
# Restore Portainer from the latest NAS backup.
#
# Automatically selects the correct restore path based on current Portainer state:
#
#   NORMAL PATH (HTTP != 200): fresh LXC after terragrunt apply, or Portainer not yet started.
#     Uses POST /api/restore (only available before admin/init).
#     Sequence: wipe db → pre_restore provision → POST /api/restore → restart → full provision
#     The follow-up provision now re-pairs migrated legacy app endpoints with lab Portainer.
#
#   EMERGENCY PATH (HTTP 200): Portainer is running and admin is initialized, but database
#     was wiped while the container was live. POST /api/restore is unavailable.
#     Uses tar extraction from the NAS bind mount inside the LXC.
#     Sequence: stop container → move db aside → tar extract → start → full provision
#     The follow-up provision now re-pairs migrated legacy app endpoints with lab Portainer.
#
# Usage:
#   export TASK_APPROVAL="<task-name>"
#   ./with-secrets-prod scripts/portainer-restore.sh
#
# Environment (resolved by with-secrets-prod):
#   LAB_IP_PORTAINER              — Portainer LXC IP (default: 192.168.20.20)
#   TF_VAR_portainer_admin_password — admin password (used by provision.sh after restore)
set -euo pipefail

PORTAINER_IP="${LAB_IP_PORTAINER:-192.168.20.20}"
PORTAINER_PORT="9000"
PORTAINER_VMID="20020"
PVE_HOST="${PORTAINER_RESTORE_PVE_HOST:-pve.gibbsgreatly.xyz}"
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

# Detect current Portainer state to choose restore path.
# HTTP 200  → already initialized; POST /api/restore is closed → emergency tar path.
# Anything else (303, 000, etc.) → uninitialized or down → normal API restore path.
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    "http://${PORTAINER_IP}:${PORTAINER_PORT}/api/system/status" 2>/dev/null || echo "000")

echo "Current Portainer status: HTTP ${HTTP_STATUS}"
echo ""

# ---------------------------------------------------------------------------
# EMERGENCY PATH
# Portainer is initialized (HTTP 200) but database was wiped while running.
# POST /api/restore is no longer available after admin/init.
# ---------------------------------------------------------------------------
if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "=== Emergency tar-restore path ==="
    echo "Admin is already initialized — cannot use POST /api/restore."
    echo "Extracting backup via tar while container is stopped."
    echo ""

    echo "Stopping Portainer container and preserving current state..."
    ssh root@"${PVE_HOST}" "pct exec ${PORTAINER_VMID} -- bash -c '
        docker stop ${CONTAINER_NAME} 2>/dev/null || true
        STAMP=\$(date +%Y%m%d%H%M%S)
        if [[ -e /var/lib/portainer ]]; then
            mv /var/lib/portainer /var/lib/portainer.pre-restore-\${STAMP}
            echo \"Previous state preserved at /var/lib/portainer.pre-restore-\${STAMP}\"
        fi
    '"
    echo ""

    echo "Finding latest backup on NAS (via LXC bind mount at /var/backups/portainer)..."
    BACKUP=$(ssh root@"${PVE_HOST}" "pct exec ${PORTAINER_VMID} -- bash -c \
        'ls -t /var/backups/portainer/portainer-*.tar.gz 2>/dev/null | head -1'" \
        2>/dev/null || true)
    if [[ -z "$BACKUP" ]]; then
        echo "ERROR: no backup found in /var/backups/portainer/ inside LXC ${PORTAINER_VMID}"
        echo "       Check that the NAS bind mount is present:"
        echo "         ssh root@${PVE_HOST} pct exec ${PORTAINER_VMID} -- ls /var/backups/portainer/"
        exit 1
    fi
    BACKUP_SIZE=$(ssh root@"${PVE_HOST}" \
        "pct exec ${PORTAINER_VMID} -- du -sh ${BACKUP} | cut -f1" 2>/dev/null || echo "?")
    echo "Restoring from: ${BACKUP} (${BACKUP_SIZE})"
    echo ""

    echo "Extracting backup..."
    ssh root@"${PVE_HOST}" "pct exec ${PORTAINER_VMID} -- bash -c '
        mkdir -p /var/lib/portainer
        tar -xzf ${BACKUP} -C /var/lib/portainer
    '"
    echo "Extraction complete."
    echo ""

    echo "Starting Portainer..."
    ssh root@"${PVE_HOST}" "pct exec ${PORTAINER_VMID} -- bash -c \
        'cd /opt/portainer && docker compose up -d'"
    sleep 8

    wait_for_api "Waiting for Portainer API after tar restore"
    echo ""

    echo "=== Full provision (init gets 409 and skips; OAuth + backup support idempotent) ==="
    echo "This also re-pairs migrated legacy app endpoints with lab Portainer."
    "${SCRIPT_DIR}/provision.sh" --stack portainer-stack
    exit 0
fi

# ---------------------------------------------------------------------------
# NORMAL PATH
# Fresh LXC after terragrunt apply, or Portainer not yet started.
# POST /api/restore is available (admin not yet initialized).
# ---------------------------------------------------------------------------

echo "=== Normal API restore path ==="
echo ""

# Step 1: wipe Portainer database so the instance is guaranteed uninitialized.
# /var/lib/portainer can survive a destroy/apply cycle if the storage profile
# reuses an existing volume or the template has stale data.
# Stop+remove the container first so the DB isn't live in memory during wipe.
echo "Wiping /var/lib/portainer to guarantee a fresh uninitialized instance..."
ssh root@"${PVE_HOST}" "pct exec ${PORTAINER_VMID} -- bash -c '
    docker stop ${CONTAINER_NAME} 2>/dev/null || true
    docker rm   ${CONTAINER_NAME} 2>/dev/null || true
    rm -rf /var/lib/portainer
'"
echo "Wiped."
echo ""

# Step 2: start Portainer CE without initialising (plays 1+2 only)
echo "=== Phase 1: deploy Docker base + Portainer CE (no init) ==="
ANSIBLE_TAGS="pre_restore" "${SCRIPT_DIR}/provision.sh" --stack portainer-stack
echo ""

# Step 3: wait for fresh uninitialized instance
wait_for_api "Waiting for Portainer API (uninitialized)"

INSTANCE_BEFORE=$(curl -sf --max-time 5 \
    "http://${PORTAINER_IP}:${PORTAINER_PORT}/api/system/status" | jq -r .InstanceID)
echo "InstanceID (new instance): ${INSTANCE_BEFORE}"
echo ""

# Step 4: find latest backup on NAS via pve SSH
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

# Step 5: restore (no auth — instance is uninitialised)
# Note: -s suppresses progress but errors are still captured via -w; no -f so
# we always get the HTTP code rather than a silent exit-22 on 4xx.
echo "POSTing restore..."
RESTORE_RESPONSE=$(ssh root@"${PVE_HOST}" \
    "curl -s --max-time 30 -X POST http://${PORTAINER_IP}:${PORTAINER_PORT}/api/restore \
     -F 'file=@${BACKUP}' -w '\nHTTP %{http_code}'")
echo "${RESTORE_RESPONSE}"

HTTP=$(echo "${RESTORE_RESPONSE}" | grep -oE 'HTTP [0-9]+' | awk '{print $2}')
if [[ "$HTTP" != "200" ]]; then
    echo "ERROR: restore failed (HTTP ${HTTP})"
    echo "       Ensure provision.sh has NOT run (init play must not have executed yet)"
    echo "       If admin was already initialized, re-run this script — it will"
    echo "       detect the initialized state and switch to the emergency tar path."
    exit 1
fi
echo ""

# Step 6: restart to load restored DB
echo "Restarting Portainer container..."
ssh root@"${PVE_HOST}" "pct exec ${PORTAINER_VMID} -- docker restart ${CONTAINER_NAME}"
sleep 8

# Step 7: wait for it to come back up
wait_for_api "Waiting for Portainer API after restart"
echo ""

# Step 8: verify InstanceID changed
INSTANCE_AFTER=$(curl -sf --max-time 5 \
    "http://${PORTAINER_IP}:${PORTAINER_PORT}/api/system/status" | jq -r .InstanceID)
echo "InstanceID (restored): ${INSTANCE_AFTER}"
if [[ "$INSTANCE_BEFORE" == "$INSTANCE_AFTER" ]]; then
    echo "WARN: InstanceID unchanged — restore may not have applied"
else
    echo "OK: InstanceID changed — database restored from backup"
fi
echo ""

# Step 9: full provision (init gets 409 and skips; OAuth, bind mount, timer all idempotent)
echo "=== Phase 2: full provision (init + OAuth + backup timer) ==="
echo "This also re-pairs migrated legacy app endpoints with lab Portainer."
"${SCRIPT_DIR}/provision.sh" --stack portainer-stack
