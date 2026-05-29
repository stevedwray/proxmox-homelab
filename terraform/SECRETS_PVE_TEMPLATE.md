# Production Secrets Template
#
# This file documents the expected key surface for terraform/secrets.pve.enc.yaml.
# The real file must be SOPS-encrypted.
#
# Creation/update flow:
#   1. Edit terraform/secrets.pve.enc.yaml via SOPS
#      SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.pve.enc.yaml
#   2. Keep this template in sync whenever required keys change.
#
# -----------------------------------------------------------------------------
# REQUIRED FOR NON-INTERACTIVE PRODUCTION TERRAGRUNT PLAN (read-only)
# -----------------------------------------------------------------------------
# These Terraform input variables have no defaults and must be present as
# TF_VAR_* environment variables when with-secrets-prod runs terragrunt/terraform.
#
# TF_VAR_lxc_password: <production LXC root password>
# TF_VAR_pm_api_token_secret: <production Proxmox API token secret>
#
# -----------------------------------------------------------------------------
# REQUIRED FOR ACTIVE STACK DEPLOYMENT WORKFLOWS (Ansible playbooks)
# -----------------------------------------------------------------------------
# Authentik stack
# AUTHENTIK_POSTGRES_PASSWORD: <authentik postgres password>
# AUTHENTIK_SECRET_KEY: <authentik secret key>
# AUTHENTIK_STEVE_PASSWORD: <authentik steve user password>
# AUTHENTIK_SUPERUSER_API_TOKEN: <authentik superuser API token>
# AUTHENTIK_SUPERUSER_PASSWORD: <authentik superuser password>
#
# step-ca stack
# STEP_CA_PASSWORD: <step-ca password>
# STEP_CA_PROVISIONER_PASSWORD: <step-ca provisioner password>
#
# Monitoring stack
# GRAFANA_ADMIN_PASSWORD: <grafana admin password>
# GRAFANA_OAUTH_CLIENT_SECRET: <grafana oauth client secret>
#
# Proxy stack
# CF_DNS_API_TOKEN: <cloudflare DNS API token>
#
# Harbor stack
# HARBOR_ADMIN_PASSWORD: <harbor admin password>
# HARBOR_DB_PASSWORD: <harbor database password>
# HARBOR_OIDC_CLIENT_SECRET: <harbor oidc client secret>
#
# NetBox stack
# NETBOX_API_TOKEN_PEPPER: <netbox API token pepper>
# NETBOX_DB_PASSWORD: <netbox database password>
# NETBOX_REDIS_CACHE_PASSWORD: <netbox redis cache password>
# NETBOX_REDIS_PASSWORD: <netbox redis password>
# NETBOX_SECRET_KEY: <netbox secret key>
# NETBOX_SUPERUSER_API_TOKEN: <netbox superuser API token>
# NETBOX_SUPERUSER_PASSWORD: <netbox superuser password>
#
# Shared breakglass credential (used by multiple stack playbooks)
# BREAKGLASS_PASSWORD: <breakglass account password>
#
# Portainer stack
# TF_VAR_portainer_admin_password: <Portainer admin password used by deploy-portainer-stack>
# Portainer OAuth (required when PORTAINER_OAUTH_ENABLED=true)
# PORTAINER_OAUTH_CLIENT_SECRET: <portainer oauth client secret>
#
# -----------------------------------------------------------------------------
# NOTES
# -----------------------------------------------------------------------------
# - with-secrets-prod loads only terraform/secrets.pve.enc.yaml.
# - Do not rely on terraform/secrets.enc.yaml for production runs.
# - This template is plaintext documentation; never store real secret values here.
