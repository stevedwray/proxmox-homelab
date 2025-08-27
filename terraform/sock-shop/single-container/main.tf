# Single container deployment for Sock Shop frontend testing

terraform {
  required_version = ">= 1.0"
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "2.9.11" # keep as you had it
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
  target_node = var.proxmox_node
  hostname    = "sock-shop-frontend"

  # Use your new Docker-ready OS template tarball
  # (shown in UI under local -> CT Templates)
  ostemplate = "local:vztmpl/debian-12-docker.tar.gz"

  ostype       = "debian" # helps PVE apply the right defaults
  password     = var.lxc_password
  unprivileged = true
  onboot       = true
  start        = true

  cores  = 2
  memory = 2048
  swap   = 512

  # Docker in LXC needs both nesting and keyctl
  features {
    nesting = true
    #  keyctl  = true
  }

  rootfs {
    storage = var.storage_pool # e.g., "local-zfs"
    size    = "12G"
  }

  network {
    name   = "eth0"
    bridge = var.network_bridge # e.g., "vmbr0"
    ip     = "192.168.1.60/24"
    gw     = "192.168.1.1"
    # firewall = false  # uncomment if you want firewall disabled
  }

  # SSH access
  ssh_public_keys = file("~/.ssh/id_rsa.pub")

  tags = "sock-shop,frontend,test"
}

output "frontend_ip" {
  value = "192.168.1.60"
}
