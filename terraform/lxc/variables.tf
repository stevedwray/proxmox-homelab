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

variable "portainer_admin_password" {
  description = "Admin password for the Portainer server"
  type        = string
  sensitive   = true
}

variable "proxmox_host" {
  description = "Proxmox host for SSH access (used to set features that require root@pam)"
  type        = string
  default     = "pve.gibbsgreatly.xyz"
}

variable "ssh_pve_user" {
  description = "SSH user for the Proxmox host"
  type        = string
  default     = "root"
}
