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
  description = "Proxmox API token ID, e.g. root@pam!terraform-root"
  type        = string
}

variable "pm_api_token_secret" {
  description = "Proxmox API token secret (value)"
  type        = string
  sensitive   = true
}

variable "proxmox_node" {
  description = "Proxmox node name"
  type        = string
  default     = "pvetest"
}

variable "portainer_vmid" {
  description = "Container ID for Portainer server"
  type        = number
  default     = 301
}

variable "portainer_hostname" {
  description = "Hostname for the Portainer server container"
  type        = string
  default     = "management-stack"
  
}

