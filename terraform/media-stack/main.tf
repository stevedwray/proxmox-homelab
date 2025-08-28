# /mnt/i/proxmox/terraform/media-stack/main.tf

terraform {
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "2.9.11"
    }
  }
}

provider "proxmox" {
  pm_api_url          = var.proxmox_api_url
  pm_api_token_id     = var.pm_api_token_id
  pm_api_token_secret = var.pm_api_token_secret
  pm_tls_insecure     = true
}

resource "proxmox_lxc" "media_stack" {
  target_node = var.proxmox_node
  vmid        = 800
  hostname    = "media-stack"

  ostemplate = "local:vztmpl/debian-12-docker.tar.gz"
  ostype     = "debian"
  password   = var.lxc_password

  # IMPORTANT: unprivileged=true so we can set features via API (tokens).
  unprivileged = true
  onboot       = true
  start        = true

  cores  = 4
  memory = 8192
  swap   = 2048

  features {
    nesting = true
    # keyctl  = true
  }

  # rootfs: ZFS storage for the container
  rootfs {
    storage = "local-zfs"
    size    = "50G"
  }

  # Extra dataset for media (mounted inside the container)
  mountpoint {
    key     = "0"
    slot    = 0
    storage = "local-zfs"
    size    = "200G"
    mp      = "/mnt/media"
  }

  network {
    name   = "eth0"
    bridge = "vmbr0"
    ip     = "192.168.1.80/24"
    gw     = "192.168.1.1"
  }

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "portainer,media-stack,unprivileged"
}

output "media_stack_details" {
  value = {
    ip           = "192.168.1.80"
    hostname     = proxmox_lxc.media_stack.hostname
    container_id = proxmox_lxc.media_stack.vmid
    privileged   = !proxmox_lxc.media_stack.unprivileged
  }
}
