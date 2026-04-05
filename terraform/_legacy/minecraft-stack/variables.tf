# terraform/minecraft-stack/variables.tf

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

variable "agent_vmid" {
  description = "Container ID for minecraft server"
  type        = number
  default     = null
}

variable "agent_hostname" {
  description = "Hostname for the minecraft server container"
  type        = string
  default     = "minecraft-stack"
}

variable "agent_ip_address" {
  description = "Static IP address with CIDR notation for minecraft server"
  type        = string
  default     = "192.168.1.73/24"
}

variable "agent_memory" {
  description = "Memory allocation in MB for minecraft server"
  type        = number
  default     = 16384
}

variable "agent_cores" {
  description = "Number of CPU cores for minecraft server"
  type        = number
  default     = 4
}

variable "agent_rootfs_size" {
  description = "Root filesystem size for minecraft server"
  type        = string
  default     = "100G"
}

variable "portainer_server_ip" {
  description = "IP address of the Portainer server for agent registration"
  type        = string
  default     = "192.168.1.70"
}

# Registry integration variables
variable "registry_mirror_ip" {
  description = "IP address of local registry mirror"
  type        = string
  default     = "192.168.1.70"
}

variable "enable_registry_mirror" {
  description = "Enable local registry mirror configuration"
  type        = bool
  default     = true
}