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

  # host_bind_mounts (raw host-path bind mounts, as opposed to the two
  # managed-storage mount_point blocks above) and device_passthrough are
  # NOT managed here -- Proxmox hardcodes both to root@pam authentication
  # only, regardless of the API token's RBAC role. Confirmed via two live
  # 403s: "mount point type bind is only allowed for root@pam" and
  # "configuring device passthrough is only allowed for root@pam". Same
  # restriction class as the keyctl feature flag below. Both applied
  # out-of-band instead, via
  # ansible/playbooks/configure-device-passthrough.yml (direct root SSH
  # `pct set`, which runs as true root@pam and isn't subject to this
  # check) -- see var.host_bind_mounts/var.device_passthrough's
  # descriptions.

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
