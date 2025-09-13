# terraform/modules/lxc-docker-host/variables.tf

variable "target_node" {
  description = "Proxmox node to deploy the LXC container on"
  type        = string
}

variable "hostname" {
  description = "Hostname for the LXC container"
  type        = string
}

variable "ostemplate" {
  description = "OS template for the LXC container"
  type        = string
  default     = "local:vztmpl/debian-docker-template.tar.gz"
}

variable "ostype" {
  description = "OS type for the LXC container"
  type        = string
  default     = "debian"
}

variable "lxc_password" {
  description = "Root password for the LXC container"
  type        = string
  sensitive   = true
}

variable "unprivileged" {
  description = "Whether the LXC container should be unprivileged"
  type        = bool
  default     = true
}

variable "onboot" {
  description = "Whether the LXC container should start on boot"
  type        = bool
  default     = true
}

variable "start" {
  description = "Whether to start the LXC container after creation"
  type        = bool
  default     = true
}

variable "cores" {
  description = "Number of CPU cores for the LXC container"
  type        = number
  default     = 2
}

variable "memory" {
  description = "Memory allocation in MB for the LXC container"
  type        = number
  default     = 2048
}

variable "swap" {
  description = "Swap allocation in MB for the LXC container"
  type        = number
  default     = 512
}

variable "nesting" {
  description = "Enable nesting for Docker containers"
  type        = bool
  default     = true
}

variable "rootfs_storage" {
  description = "Storage backend for the root filesystem"
  type        = string
  default     = "local-zfs"
}

variable "rootfs_size" {
  description = "Size of the root filesystem"
  type        = string
  default     = "8G"
}

variable "network_bridge" {
  description = "Network bridge for the LXC container"
  type        = string
  default     = "vmbr0"
}

variable "ip_address" {
  description = "Static IP address with CIDR notation (e.g., 192.168.1.100/24)"
  type        = string
}

variable "gateway" {
  description = "Network gateway IP address"
  type        = string
  default     = "192.168.1.1"
}

variable "ssh_public_keys" {
  description = "SSH public keys for root access"
  type        = string
}

variable "tags" {
  description = "Tags for the LXC container"
  type        = string
  default     = ""
}

variable "vmid" {
  description = "Proxmox container ID (VMID). If not specified, Proxmox will auto-assign"
  type        = number
  default     = "301"
}

variable "mp0" {
  description = "Bind mount string for mp0 (e.g. /host/path,mp=/container/path)"
  type        = string
  default     = ""
}

variable "mp1" {
  description = "Bind mount string for mp1"
  type        = string
  default     = ""
}