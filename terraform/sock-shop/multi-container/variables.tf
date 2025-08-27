# File: terraform/sock-shop/single-container/variables.tf
# Variables for single container Sock Shop deployment

variable "proxmox_api_url" {
  description = "Proxmox API URL"
  type        = string
}

variable "proxmox_user" {
  description = "Proxmox username"
  type        = string
}

variable "proxmox_password" {
  description = "Proxmox password"
  type        = string
  sensitive   = true
}

variable "proxmox_tls_insecure" {
  description = "Skip TLS verification"
  type        = bool
  default     = true
}

variable "proxmox_node" {
  description = "Proxmox node name"
  type        = string
  default     = "pvetest"
}

variable "lxc_password" {
  description = "Password for LXC containers"
  type        = string
  sensitive   = true
}

variable "storage_pool" {
  description = "Storage pool for containers"
  type        = string
  default     = "local-zfs"
}

variable "network_bridge" {
  description = "Network bridge for containers"
  type        = string
  default     = "vmbr0"
}
