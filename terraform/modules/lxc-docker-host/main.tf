# terraform/modules/lxc-docker-host/main.tf

terraform {
  required_providers {
    proxmox = {
      source = "telmate/proxmox"
    }
  }
}

resource "proxmox_lxc" "docker_host" {
  target_node = var.target_node
  hostname    = var.hostname
  vmid        = var.vmid

  ostemplate   = var.ostemplate
  ostype       = var.ostype
  password     = var.lxc_password
  unprivileged = var.unprivileged
  onboot       = var.onboot
  start        = var.start

  cores  = var.cores
  memory = var.memory
  swap   = var.swap

  # Docker engine storage
  mountpoint {
    slot    = 0
    key     = "mp0"
    storage = var.rootfs_storage
    size    = "20G"
    mp      = "/var/lib/docker"
  }

  features {
    nesting = var.nesting
  }

  rootfs {
    storage = var.rootfs_storage
    size    = var.rootfs_size
  }

  network {
    name   = "eth0"
    bridge = var.network_bridge
    ip     = var.ip_address
    gw     = var.gateway
  }

  ssh_public_keys = var.ssh_public_keys
  tags            = var.tags
}