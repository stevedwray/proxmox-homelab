# File: terraform/sock-shop/terraform-only/main.tf
# Complete Terraform-only deployment with embedded configuration

terraform {
  required_version = ">= 1.0"
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "~> 2.9"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.1"
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
    frontend  = { ip = "192.168.1.70", memory = 2048, cores = 2, disk = "12G" }
    user      = { ip = "192.168.1.71", memory = 1024, cores = 1, disk = "8G" }
    catalogue = { ip = "192.168.1.72", memory = 1024, cores = 1, disk = "8G" }
    database  = { ip = "192.168.1.73", memory = 2048, cores = 2, disk = "16G" }
  }
}

resource "proxmox_lxc" "sock_shop_containers" {
  for_each = local.containers

  target_node  = var.proxmox_node
  hostname     = "sock-shop-tf-${each.key}"
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
  tags            = "sock-shop,${each.key},terraform-only"
}

# Wait for containers to be ready
resource "null_resource" "wait_for_containers" {
  count = length(local.containers)

  provisioner "local-exec" {
    command = "sleep 60" # Wait for containers to start
  }

  depends_on = [proxmox_lxc.sock_shop_containers]
}

# Deploy applications using remote-exec
resource "null_resource" "deploy_applications" {
  for_each = local.containers

  connection {
    type        = "ssh"
    user        = "root"
    private_key = file("~/.ssh/id_rsa")
    host        = each.value.ip
  }

  provisioner "file" {
    content = templatefile("${path.module}/scripts/deploy-${each.key}.sh", {
      container_ip = each.value.ip
      database_ip  = local.containers.database.ip
      user_ip      = local.containers.user.ip
      catalogue_ip = local.containers.catalogue.ip
    })
    destination = "/tmp/deploy.sh"
  }

  provisioner "remote-exec" {
    inline = [
      "chmod +x /tmp/deploy.sh",
      "/tmp/deploy.sh",
    ]
  }

  depends_on = [null_resource.wait_for_containers]
}

output "frontend_url" {
  value = "http://${local.containers.frontend.ip}"
}

output "container_ips" {
  value = {
    for name, config in local.containers : name => config.ip
  }
}
