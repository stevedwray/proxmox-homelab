# File: terraform/sock-shop/multi-container/main.tf
# Multi-container deployment for Sock Shop testing (3 containers)

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

# Frontend container
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

  features {
    nesting = true
    keyctl  = true
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

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "sock-shop,frontend,test"
}

# Database container
resource "proxmox_lxc" "sock_shop_database" {
  target_node  = var.proxmox_node
  hostname     = "sock-shop-db"
  ostemplate   = "901"
  password     = var.lxc_password
  unprivileged = true
  onboot       = true
  start        = true

  memory = 1024
  cores  = 1

  features {
    nesting = true
    keyctl  = true
  }

  rootfs {
    storage = var.storage_pool
    size    = "8G"
  }

  network {
    name   = "eth0"
    bridge = var.network_bridge
    ip     = "192.168.1.61/24"
    gw     = "192.168.1.1"
  }

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "sock-shop,database,test"
}

# User service container
resource "proxmox_lxc" "sock_shop_user" {
  target_node  = var.proxmox_node
  hostname     = "sock-shop-user"
  ostemplate   = "901"
  password     = var.lxc_password
  unprivileged = true
  onboot       = true
  start        = true

  memory = 1024
  cores  = 1

  features {
    nesting = true
    keyctl  = true
  }

  rootfs {
    storage = var.storage_pool
    size    = "8G"
  }

  network {
    name   = "eth0"
    bridge = var.network_bridge
    ip     = "192.168.1.62/24"
    gw     = "192.168.1.1"
  }

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "sock-shop,user-service,test"
}

output "container_ips" {
  value = {
    frontend = "192.168.1.60"
    database = "192.168.1.61"
    user     = "192.168.1.62"
  }
}
