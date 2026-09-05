#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_NAME="${NETBOX_POPULATE_IMAGE:-netbox-populate:daily}"
# Candidate identity file from env fallbacks; may be absent when socket-proxy is used
SSH_KEY_FILE="${NETBOX_GUEST_SSH_IDENTITY_FILE:-${ANSIBLE_PRIVATE_KEY_FILE:-$HOME/.ssh/id_ed25519}}"
SSH_KEY_DEST="/ssh/id_ed25519"
# populate.py derives its network intent YAML from its own script location
# (parents[3] / "network"), which only resolves inside a real git checkout —
# never true in this container (only the integrations/*.py files are COPY'd
# in). Mount the real network dir and point NETBOX_NETWORK_INTENT_PATH at
# it explicitly, matching populate.py's own documented fallback for
# "deployed outside a git checkout".
NETWORK_DIR="${ROOT_DIR}/terraform/lxc/network"
NETWORK_DIR_DEST="/network"
ENV_FILE="$(mktemp)"
trap 'rm -f "${ENV_FILE}"' EXIT

# If a docker socket proxy is configured in the environment, the runner
# should prefer that transport and not require a mounted guest SSH key.
# Treat unresolved template placeholders like '${...}' as not configured
# to avoid a mismatch where the wrapper skips SSH key mounting but
# the Python discovery code treats the template as unresolved and
# falls back to SSH (causing a silent failure when no key is mounted).
USE_SOCKET_PROXY=false
# Only consider the proxy configured when the env var is both non-empty
# and does not look like an unresolved template placeholder (contains '${').
# shellcheck disable=SC2016  # single quotes intentional — matching literal '${' substring, not expanding
if [ -n "${DOCKER_SOCKET_PROXY_URL_TEMPLATE:-}" ] && [[ "${DOCKER_SOCKET_PROXY_URL_TEMPLATE}" != *'${'* ]]; then
  USE_SOCKET_PROXY=true
elif [ -n "${DOCKER_SOCKET_PROXY_URL:-}" ] && [[ "${DOCKER_SOCKET_PROXY_URL}" != *'${'* ]]; then
  USE_SOCKET_PROXY=true
fi

MOUNT_SSH_KEY=false
if [[ -f "${SSH_KEY_FILE}" ]]; then
  MOUNT_SSH_KEY=true
else
  if [ "${USE_SOCKET_PROXY}" = "true" ]; then
    echo "Note: SSH identity file ${SSH_KEY_FILE} not found, but socket-proxy config present; proceeding without SSH key mount." >&2
    MOUNT_SSH_KEY=false
  else
    echo "ERROR: SSH identity file not found at ${SSH_KEY_FILE}" >&2
    exit 1
  fi
fi

# Carry the repository/env configuration into the container. Keep the
# private SSH key mounted separately when available so the env file stays text-only.
# NOTE: the prefix group (NETBOX_, PROXMOX_, ...) intentionally has no
# trailing '=' -- these need to match var names that continue past the
# prefix (e.g. LAB_IP_NETBOX=, NETBOX_API_TOKEN=). The second group is
# exact whole-name vars, which do need the trailing '=' so they don't
# accidentally match as substrings of something else.
env | grep -E '^(NETBOX_|PROXMOX_|TF_VAR_|MIKROTIK_|LAB_IP_|PORTAINER_)|^(PVE_ENV|LAB_DOMAIN|TF_WORKSPACE|ANSIBLE_PRIVATE_KEY_FILE|DOCKER_SOCKET_PROXY_URL_TEMPLATE|DOCKER_SOCKET_PROXY_URL)=' | sort > "${ENV_FILE}"
printf 'NETBOX_GUEST_SSH_USER=%s\n' "${NETBOX_GUEST_SSH_USER:-automation}" >> "${ENV_FILE}"
# Only export an identity file path into the env file when we will mount it
if [ "${MOUNT_SSH_KEY}" = "true" ]; then
  printf 'NETBOX_GUEST_SSH_IDENTITY_FILE=%s\n' "${SSH_KEY_DEST}" >> "${ENV_FILE}"
fi
# Respect an explicit override if the caller already set one; otherwise
# derive it from PVE_ENV (pve, pve-test, pve-test-vm all map 1:1 to a
# <env>.yaml file in terraform/lxc/network/).
if [ -z "${NETBOX_NETWORK_INTENT_PATH:-}" ] && [ -n "${PVE_ENV:-}" ]; then
  printf 'NETBOX_NETWORK_INTENT_PATH=%s/%s.yaml\n' "${NETWORK_DIR_DEST}" "${PVE_ENV}" >> "${ENV_FILE}"
fi

if [ "${MOUNT_SSH_KEY}" = "true" ]; then
  exec docker run --rm \
    --network host \
    --env-file "${ENV_FILE}" \
    -v "${SSH_KEY_FILE}:${SSH_KEY_DEST}:ro" \
    -v "${NETWORK_DIR}:${NETWORK_DIR_DEST}:ro" \
    "${IMAGE_NAME}" "$@"
else
  exec docker run --rm \
    --network host \
    --env-file "${ENV_FILE}" \
    -v "${NETWORK_DIR}:${NETWORK_DIR_DEST}:ro" \
    "${IMAGE_NAME}" "$@"
fi
