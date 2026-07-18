variable "target_node" {
  description = "Proxmox node to deploy the LXC container on"
  type        = string
}

variable "hostname" {
  description = "Hostname for the LXC container"
  type        = string
}

variable "vmid" {
  description = "Proxmox container ID (VMID). If null, Proxmox will auto-assign."
  type        = number
  default     = null
}

variable "ostemplate" {
  description = "OS template for the LXC container"
  type        = string
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
  description = "Enable nesting for Docker-in-LXC"
  type        = bool
  default     = true
}

variable "rootfs_storage" {
  description = "Storage backend for the root filesystem"
  type        = string
}

variable "docker_storage" {
  description = "Storage backend for the /var/lib/docker mount"
  type        = string
}

variable "rootfs_size" {
  description = "Size of the root filesystem in GB"
  type        = number
  default     = 8
}

variable "docker_storage_size" {
  description = "Size of the /var/lib/docker mountpoint"
  type        = string
  default     = "20G"
}

variable "docker_mount_backup_enabled" {
  description = "Whether the /var/lib/docker mountpoint is included in container backups"
  type        = bool
  default     = true
}

variable "network_bridge" {
  description = "Network bridge for the LXC container"
  type        = string
  default     = "vmbr0"
}

variable "network_firewall" {
  description = "Enable the Proxmox firewall flag on the LXC network interface"
  type        = bool
  default     = false
}

variable "ip_address" {
  description = "Static IP address with CIDR notation"
  type        = string
}

variable "gateway" {
  description = "Network gateway IP address (set via root module inputs from .env)"
  type        = string
  default     = ""
}

variable "dns_servers" {
  description = "DNS servers applied by Proxmox container initialization"
  type        = list(string)
  default     = null
}

variable "ssh_public_keys" {
  description = "SSH public keys for root access"
  type        = string
}

variable "tags" {
  description = "Tags for the LXC container"
  type        = list(string)
  default     = []
}

variable "extra_mount_path" {
  description = "Path for an optional extra data mount point (e.g. /var/lib/harbor)"
  type        = string
  default     = null
}

variable "extra_mount_size" {
  description = "Size of the optional extra data mount point (e.g. '100G')"
  type        = string
  default     = null
}

variable "extra_mount_storage" {
  description = "Storage backend for the optional extra data mount point"
  type        = string
  default     = null
}

variable "extra_mount_backup_enabled" {
  description = "Whether the optional extra data mount point is included in container backups"
  type        = bool
  default     = true
}

variable "host_bind_mounts" {
  description = "Host filesystem paths to bind-mount into the container (no size — host path must exist on the Proxmox node). NOT applied by this resource -- Proxmox hardcodes bind-type mount points to root@pam authentication only (confirmed via a live 403: \"mount point type bind is only allowed for root@pam\"), regardless of the API token's RBAC role. This variable exists so the value flows from stack.yaml through Terraform for documentation/consistency; the actual application happens out-of-band via ansible/playbooks/configure-device-passthrough.yml (direct root SSH `pct set`, which runs as true root@pam)."
  type        = list(object({ host_path = string, lxc_path = string }))
  default     = []
}

variable "docker_enabled" {
  description = "Whether this container gets the /var/lib/docker mount point. Default true preserves existing behavior for every current stack; native (non-Docker) GPU-passthrough stacks (llm-gpu-stack, comfyui-stack) set this false."
  type        = bool
  default     = true
}

variable "device_passthrough" {
  description = "Host devices to pass through to the container via Proxmox's native LXC device-passthrough mechanism (PVE 8.1+) — e.g. /dev/kfd, /dev/dri/renderD128 for AMD GPU compute. Default empty list means zero behavior change for every stack that doesn't set it. NOT applied by this resource -- Proxmox hardcodes this field to root@pam authentication only (confirmed via a live 403: \"configuring device passthrough is only allowed for root@pam\"), regardless of the API token's RBAC role. This variable exists so the value flows from stack.yaml through Terraform for documentation/consistency; the actual application happens out-of-band via ansible/playbooks/configure-device-passthrough.yml (direct root SSH `pct set`, which runs as true root@pam)."
  type = list(object({
    path       = string
    uid        = optional(number)
    gid        = optional(number)
    mode       = optional(string)
    deny_write = optional(bool)
  }))
  default = []
}
