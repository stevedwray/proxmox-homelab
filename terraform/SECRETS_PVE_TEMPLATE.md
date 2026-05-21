# Production Secrets Template
#
# This file describes the structure for terraform/secrets.pve.enc.yaml.
# The actual file must be encrypted with SOPS and age keys.
#
# To create the production secrets file:
#   1. Create terraform/secrets.pve.enc.yaml with the keys below
#   2. Encrypt it with SOPS: SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.pve.enc.yaml
#   3. Keep only production-specific secrets; do not duplicate dev secrets
#
# Expected keys for production environment (pve):
#
# Infrastructure Provisioning
# TF_VAR_lxc_password: <root password for production LXCs>
# TF_VAR_pm_api_token_secret: <Proxmox API token for production>
# TF_VAR_proxmox_password: <Proxmox root password for production (if different from pve-test)>
#
# Production Service Credentials
# (Add production-specific passwords, tokens, API keys here)
# Example:
# AUTHENTIK_SUPERUSER_PASSWORD: <production authentik admin password>
# GRAFANA_ADMIN_PASSWORD: <production grafana admin password>
# HARBOR_ADMIN_PASSWORD: <production harbor admin password>
#
# External Service Integrations (Production)
# CF_DNS_API_TOKEN: <Cloudflare API token for production DNS>
# MIKROTIK_ADMIN_PASSWORD: <production router admin password>
# SNYK_TOKEN: <Snyk token for production scanning (optional)>
#
# Production-Only Overrides
# Any keys that differ between pve-test and pve should be stored here.
# Keys from this file take precedence during ./with-secrets-prod execution.
#
# Note: This template is NOT encrypted. The actual terraform/secrets.pve.enc.yaml
# file must be encrypted with SOPS before use.
