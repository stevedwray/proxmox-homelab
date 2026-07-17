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

  dynamic "mount_point" {
    for_each = var.docker_enabled ? [1] : []
    content {
      volume = var.docker_storage
      size   = var.docker_storage_size
      path   = "/var/lib/docker"
      backup = var.docker_mount_backup_enabled
    }
  }

  dynamic "mount_point" {
    for_each = var.extra_mount_path != null ? [1] : []
    content {
      volume = var.extra_mount_storage
      size   = var.extra_mount_size
      path   = var.extra_mount_path
      backup = var.extra_mount_backup_enabled
    }
  }

  dynamic "mount_point" {
    for_each = var.host_bind_mounts
    content {
      volume = mount_point.value.host_path
      path   = mount_point.value.lxc_path
      backup = false
    }
  }

  dynamic "device_passthrough" {
    for_each = var.device_passthrough
    content {
      path       = device_passthrough.value.path
      uid        = device_passthrough.value.uid
      gid        = device_passthrough.value.gid
      mode       = device_passthrough.value.mode
      deny_write = device_passthrough.value.deny_write
    }
  }

  operating_system {
    template_file_id = var.ostemplate
    type             = var.ostype
  }

  initialization {
    hostname = var.hostname

    dynamic "dns" {
      for_each = var.dns_servers != null && length(var.dns_servers) > 0 ? [1] : []
      content {
        servers = var.dns_servers
      }
    }

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
    name     = "eth0"
    bridge   = var.network_bridge
    firewall = var.network_firewall
  }

  lifecycle {
    # keyctl is enabled out-of-band via configure-keyctl.yml because the
    # automation API token cannot manage non-nesting feature flags.
    ignore_changes = [features[0].keyctl]
  }
}

# Produces a new random ID each time the container is replaced (including
# out-of-band deletions detected on the next plan). Expose this as
# container_epoch_id so callers can use it as a Ansible provisioner trigger.
resource "terraform_data" "container_epoch" {
  triggers_replace = [proxmox_virtual_environment_container.docker_host.id]
}
