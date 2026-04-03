terraform {
  required_providers {
    proxmox = {
      source = "bpg/proxmox"
    }
  }
}

resource "proxmox_virtual_environment_container" "docker_host" {
  node_name     = var.target_node
  vm_id         = var.vmid
  description   = "Managed by Terraform"
  unprivileged  = var.unprivileged
  started       = var.start
  start_on_boot = var.onboot
  tags          = var.tags

  cpu {
    cores = var.cores
  }

  memory {
    dedicated = var.memory
    swap      = var.swap
  }

  features {
    nesting = var.nesting
  }

  disk {
    datastore_id = var.rootfs_storage
    size         = var.rootfs_size
  }

  mount_point {
    volume = var.rootfs_storage
    size   = var.docker_storage_size
    path   = "/var/lib/docker"
  }

  operating_system {
    template_file_id = var.ostemplate
    type             = var.ostype
  }

  initialization {
    hostname = var.hostname

    ip_config {
      ipv4 {
        address = var.ip_address
        gateway = var.gateway
      }
    }

    user_account {
      keys     = [trimspace(var.ssh_public_keys)]
      password = var.lxc_password
    }
  }

  network_interface {
    name   = "eth0"
    bridge = var.network_bridge
  }
}
