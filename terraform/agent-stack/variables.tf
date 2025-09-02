# terraform/agent-stack/variables.tf

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
  description = "Container ID for Portainer agent"
  type        = number
  default     = null
}

variable "agent_hostname" {
  description = "Hostname for the Portainer agent container"
  type        = string
  default     = "portainer-agent-1"
}

variable "agent_ip_address" {
  description = "Static IP address with CIDR notation for Portainer agent"
  type        = string
  default     = "192.168.1.71/24"
}

variable "agent_memory" {
  description = "Memory allocation in MB for Portainer agent"
  type        = number
  default     = 1536
}

variable "agent_cores" {
  description = "Number of CPU cores for Portainer agent"
  type        = number
  default     = 1
}

variable "agent_rootfs_size" {
  description = "Root filesystem size for Portainer agent"
  type        = string
  default     = "10G"
}

variable "portainer_server_ip" {
  description = "IP address of the Portainer server for agent registration"
  type        = string
  default     = "192.168.1.70"
}