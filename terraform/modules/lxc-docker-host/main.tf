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


  # ZFS-backed extra volumes (created on the storage ID you pass from the stack, e.g. "local-zfs")
  # NPM data (covers /srv/npm/{data,letsencrypt} used by your Ansible role)
  mountpoint {
    slot    = 0
    key     = "mp0"
    storage = var.rootfs_storage
    size    = "10G"
    mp      = "/srv/npm"
  }

  # Docker engine root (images, volumes, Portainer data, registry cache)
  mountpoint {
    slot    = 1
    key     = "mp1"
    storage = var.rootfs_storage
    size    = "20G"
    mp      = "/var/lib/docker"
  }

# Docker Registry caches — one dataset per upstream registry.
# These mount directly onto Docker named-volume paths so each cache gets its own ZFS dataset.

  # Docker Hub cache volume
  mountpoint {
    slot    = 2
    key     = "mp2"
    storage = var.registry_storage     # e.g., "local-zfs" on rpool
    size    = "20G"                 # adjust as needed
    mp      = "/var/lib/docker/volumes/registry_dockerhub/_data"
  }

  # GHCR cache volume
  mountpoint {
    slot    = 3
    key     = "mp3"
    storage = var.registry_storage
    size    = "20G"
    mp      = "/var/lib/docker/volumes/registry_ghcr/_data"
  }

  # Quay cache volume
  mountpoint {
    slot    = 4
    key     = "mp4"
    storage = var.registry_storage
    size    = "20G"
    mp      = "/var/lib/docker/volumes/registry_quay/_data"
  }

  # GCR/ECR (pick one; rename later if you prefer)
  mountpoint {
    slot    = 5
    key     = "mp5"
    storage = var.registry_storage
    size    = "20G"
    mp      = "/var/lib/docker/volumes/registry_gcr/_data"
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
