# File: management-stack/variables.tf

variable "proxmox_api_url" {
  description = "Proxmox API URL"
  type        = string
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

variable "lxc_password" {
  description = "Password for LXC container"
  type        = string
  sensitive   = true
}