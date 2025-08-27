# File: terraform/sock-shop/full-stack/main.tf
# Complete infrastructure for all Sock Shop microservices

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

locals {
  containers = {
    frontend  = { ip = "192.168.1.60", memory = 2048, cores = 2, disk = "12G" }
    user      = { ip = "192.168.1.61", memory = 1024, cores = 1, disk = "8G" }
    catalogue = { ip = "192.168.1.62", memory = 1024, cores = 1, disk = "8G" }
    carts     = { ip = "192.168.1.63", memory = 1024, cores = 1, disk = "8G" }
    orders    = { ip = "192.168.1.64", memory = 1024, cores = 1, disk = "8G" }
    payment   = { ip = "192.168.1.65", memory = 512, cores = 1, disk = "6G" }
    shipping  = { ip = "192.168.1.66", memory = 512, cores = 1, disk = "6G" }
    database  = { ip = "192.168.1.67", memory = 2048, cores = 2, disk = "16G" }
  }
}

resource "proxmox_lxc" "sock_shop_containers" {
  for_each = local.containers

  target_node  = var.proxmox_node
  hostname     = "sock-shop-${each.key}"
  ostemplate   = "901"
  password     = var.lxc_password
  unprivileged = true
  onboot       = true
  start        = true

  memory = each.value.memory
  cores  = each.value.cores

  features {
    nesting = true
    keyctl  = true
  }

  rootfs {
    storage = var.storage_pool
    size    = each.value.disk
  }

  network {
    name   = "eth0"
    bridge = var.network_bridge
    ip     = "${each.value.ip}/24"
    gw     = "192.168.1.1"
  }

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "sock-shop,${each.key},production"
}

output "container_ips" {
  value = {
    for name, config in local.containers : name => config.ip
  }
}

output "frontend_url" {
  value = "http://${local.containers.frontend.ip}"
}
