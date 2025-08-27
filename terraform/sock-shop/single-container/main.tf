# File: terraform/sock-shop/single-container/main.tf
# Single container deployment for Sock Shop frontend testing

terraform {
  required_version = ">= 1.0"
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "2.9.11" # Older version that should work
    }
  }
}

provider "proxmox" {
  pm_api_url      = var.proxmox_api_url
  pm_user         = var.proxmox_user
  pm_password     = var.proxmox_password
  pm_tls_insecure = var.proxmox_tls_insecure
}

# Frontend container for initial testing
resource "proxmox_lxc" "sock_shop_frontend" {
  target_node  = var.proxmox_node
  hostname     = "sock-shop-frontend"
  ostemplate   = "901"
  password     = var.lxc_password
  unprivileged = true
  onboot       = true
  start        = true

  memory = 2048
  cores  = 2

  # Enable Docker features
  features {
    nesting = true
  }

  rootfs {
    storage = var.storage_pool
    size    = "12G"
  }

  network {
    name   = "eth0"
    bridge = var.network_bridge
    ip     = "192.168.1.60/24"
    gw     = "192.168.1.1"
  }

  # SSH public key for automation
  ssh_public_keys = file("~/.ssh/id_rsa.pub")

  tags = "sock-shop,frontend,test"
}

output "frontend_ip" {
  value = "192.168.1.60"
}
