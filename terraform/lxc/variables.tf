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

variable "network_intent_path" {
  description = "Optional override path for the shared network intent YAML file"
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
  description = "Default Proxmox node name"
  type        = string
  default     = "pve"
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
  description = "Default network gateway"
  type        = string
  default     = "192.168.1.1"
}

variable "default_storage" {
  description = "Default storage backend"
  type        = string
  default     = "local-zfs"
}

variable "portainer_server_ip" {
  description = "IP of the central Portainer server (for agent registration/cleanup)"
  type        = string
  default     = "192.168.1.4"
}

variable "registry_host" {
  description = "Hostname or IP of the Harbor registry used for Docker image pulls"
  type        = string
  default     = "192.168.1.10"
}

variable "apt_cacher_host" {
  description = "IP of the apt-cacher-ng proxy. Empty string disables apt proxy configuration."
  type        = string
  default     = "192.168.1.35"
}

variable "portainer_admin_password" {
  description = "Admin password for the Portainer server"
  type        = string
  sensitive   = true
}

variable "proxmox_host" {
  description = "Proxmox host for SSH access (used by Ansible delegate_to for features that require root@pam)"
  type        = string
  default     = "pve.gibbsgreatly.xyz"
}
