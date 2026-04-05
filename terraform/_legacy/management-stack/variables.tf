# terraform/management-stack/variables.tf

variable "proxmox_api_url" {
  description = "Proxmox API URL"
  type        = string
}

variable "lxc_password" {
  description = "Password for LXC containers"
  type        = string
  sensitive   = true
}

variable "pm_api_token_id" {
  description = "Proxmox API token ID"
  type        = string
}

variable "pm_api_token_secret" {
  description = "Proxmox API token secret"
  type        = string
  sensitive   = true
}

# Existing management stack variables
variable "proxmox_node" {
  description = "Proxmox node name"
  type        = string
  default     = "pve"
}

variable "portainer_vmid" {
  description = "Container ID for Portainer management server"
  type        = number
  default     = 101
}

variable "portainer_hostname" {
  description = "Hostname for the Portainer management container"
  type        = string
  default     = "portainer-server"
}

variable "portainer_ip_address" {
  description = "Static IP address with CIDR notation for Portainer server"
  type        = string
  default     = "192.168.1.70/24"
}

variable "portainer_memory" {
  description = "Memory allocation in MB for Portainer server"
  type        = number
  default     = 3072
}

variable "portainer_cores" {
  description = "Number of CPU cores for Portainer server"
  type        = number
  default     = 2
}

variable "portainer_rootfs_size" {
  description = "Root filesystem size for Portainer server"
  type        = string
  default     = "15G"
}

variable "npm_data_target" {
  description = "Target mount path for NPM data in container"
  type        = string
  default     = "/srv/npm/data"
}

variable "npm_letsencrypt_target" {
  description = "Target mount path for NPM letsencrypt in container"
  type        = string
  default     = "/srv/npm/letsencrypt"
}

variable "rootfs_storage" {
  description = "Proxmox storage ID for the LXC rootfs and default extra volumes"
  type        = string
  default     = "local-zfs"
}

# NEW: storage ID for heavy registry caches (apps pool)
variable "registry_storage" {
  description = "Proxmox storage ID for registry cache volumes"
  type        = string
  default     = "apps-containers"
}
