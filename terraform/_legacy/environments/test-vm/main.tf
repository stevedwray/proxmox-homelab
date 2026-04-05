terraform {
  required_version = ">= 1.0"
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "~> 2.9"
    }
  }
}

provider "proxmox" {
  pm_api_url      = var.proxmox_api_url
  pm_user         = var.proxmox_user
  pm_password     = var.proxmox_password
  pm_tls_insecure = var.proxmox_tls_insecure
}

# Test LXC containers
resource "proxmox_lxc" "test_containers" {
  count        = var.test_container_count
  target_node  = var.proxmox_node
  hostname     = "test-${count.index + 1}"
  ostemplate   = var.lxc_template
  password     = var.lxc_password
  unprivileged = true

  memory = 512
  cores  = 1

  rootfs {
    storage = var.storage_pool
    size    = "8G"
  }

  network {
    name   = "eth0"
    bridge = var.network_bridge
    ip     = "dhcp"
  }

  tags = "test,development"
}
