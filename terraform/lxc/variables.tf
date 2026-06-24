# ---------------------------------------------------------------------------
# Stack identity — provided by Terragrunt from the stack's directory
# ---------------------------------------------------------------------------
variable "stack_name" {
  description = "Name of the stack (matches the stacks/<name>/ directory)"
  type        = string
}

variable "stack_yaml_path" {
  description = "Absolute path to the stack's stack.yaml file"
  type        = string
}

variable "generated_dir" {
  description = "Directory where generated runtime files (inventory.yml, network-*-vars.yml) are written. Empty string falls back to the stack source directory for legacy compatibility."
  type        = string
  default     = ""
}

variable "network_intent_path" {
  description = "Optional override path for the shared network intent YAML file"
  type        = string
  default     = null
}

variable "storage_manifest_path" {
  description = "Optional override path for the environment storage manifest YAML file"
  type        = string
  default     = null
}

# ---------------------------------------------------------------------------
# Proxmox connection
# ---------------------------------------------------------------------------
variable "proxmox_api_url" {
  description = "Proxmox API URL (e.g., https://pve.example.com:8006/api2/json)"
  type        = string
}

variable "pm_api_token_id" {
  description = "Proxmox API token ID (e.g., automation@pve!terraform)"
  type        = string
}

variable "pm_api_token_secret" {
  description = "Proxmox API token secret"
  type        = string
  sensitive   = true
}

variable "pm_tls_insecure" {
  description = "Skip TLS verification for self-signed certs"
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Defaults applied to all stacks (overridable per-stack in YAML)
# ---------------------------------------------------------------------------
variable "proxmox_node" {
  description = "Default Proxmox node name; wrappers/env vars override this per environment"
  type        = string
  default     = "pve-test"
}

variable "stack_hostname" {
  description = "Override LXC hostname (and Portainer endpoint name). Defaults to stack.yaml hostname."
  type        = string
  default     = null
}

variable "stack_app_name" {
  description = "Override Portainer stack name. Defaults to stack.yaml app_stack_name or stack directory name."
  type        = string
  default     = null
}

variable "stack_ip_address" {
  description = "Override LXC IP address (CIDR). Defaults to stack.yaml ip_address."
  type        = string
  default     = null
}

variable "lxc_password" {
  description = "Root password for LXC containers"
  type        = string
  sensitive   = true
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key file"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ssh_private_key_path" {
  description = "Path to SSH private key file (for Ansible)"
  type        = string
  default     = "~/.ssh/id_ed25519"
}

variable "default_gateway" {
  description = "Default network gateway (set from TF_VAR_default_gateway in .env)"
  type        = string
  default     = ""
}

variable "default_storage" {
  description = "DEPRECATED: legacy default storage backend; use storage manifests and storage_profile in stack.yaml"
  type        = string
  default     = "infrastructure-containers"
}

variable "portainer_server_ip" {
  description = "IP of the central Portainer server (for agent registration/cleanup)"
  type        = string
  default     = ""
}

variable "registry_host" {
  description = "Hostname or IP of the Harbor registry used for Docker image pulls"
  type        = string
  default     = ""
}

variable "apt_cacher_host" {
  description = "IP of the apt-cacher-ng proxy. Empty string disables apt proxy configuration."
  type        = string
  default     = ""
}

variable "portainer_admin_password" {
  description = "Admin password for the Portainer server"
  type        = string
  default     = null
  nullable    = true
  sensitive   = true
}

variable "proxmox_host" {
  description = "Proxmox host for SSH access (used by Ansible delegate_to for features that require root@pam)"
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# pve-test lab addressing inputs (expected from TF_VAR_* exported in .env)
# ---------------------------------------------------------------------------
variable "lab_ip_portainer" {
  description = "Portainer service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_ip_authentik" {
  description = "Authentik service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_ip_step_ca" {
  description = "step-ca service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_ip_monitoring" {
  description = "Monitoring service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_ip_dns" {
  description = "CoreDNS service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_ip_proxy" {
  description = "Traefik service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_ip_harbor" {
  description = "Harbor service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_ip_netbox" {
  description = "NetBox service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_ip_apt_cacher" {
  description = "apt-cacher service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_ip_ci_runner" {
  description = "CI runner service IPv4 address"
  type        = string
  default     = ""
}

variable "lab_gw_mgmt" {
  description = "Management subnet gateway IPv4 address"
  type        = string
  default     = ""
}

variable "lab_gw_edge" {
  description = "Edge subnet gateway IPv4 address"
  type        = string
  default     = ""
}

variable "lab_gw_infra" {
  description = "Infrastructure subnet gateway IPv4 address"
  type        = string
  default     = ""
}

variable "lab_gw_build" {
  description = "Build subnet gateway IPv4 address"
  type        = string
  default     = ""
}

variable "lab_subnet_mgmt_cidr" {
  description = "Management subnet CIDR"
  type        = string
  default     = ""
}

variable "lab_subnet_edge_cidr" {
  description = "Edge subnet CIDR"
  type        = string
  default     = ""
}

variable "lab_subnet_infra_cidr" {
  description = "Infrastructure subnet CIDR"
  type        = string
  default     = ""
}

variable "lab_subnet_build_cidr" {
  description = "Build subnet CIDR"
  type        = string
  default     = ""
}

variable "dayz_steam_username" {
  description = "Steam username for DayZ server authentication"
  type        = string
  default     = ""
}

variable "dayz_steam_password" {
  description = "Steam password for DayZ server authentication"
  type        = string
  default     = ""
}
