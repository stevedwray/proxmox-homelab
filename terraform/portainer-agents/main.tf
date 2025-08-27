terraform {
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "2.9.11"
    }
  }
}

provider "proxmox" {
  pm_api_url      = var.proxmox_api_url
  pm_user         = var.proxmox_user
  pm_password     = var.proxmox_password
  pm_tls_insecure = true
}

resource "proxmox_lxc" "portainer_agent" {
  target_node = "pvetest"
  hostname    = "portainer-agent-1"

  ostemplate   = "local:vztmpl/debian-12-docker.tar.gz"
  ostype       = "debian"
  password     = var.lxc_password
  unprivileged = true
  onboot       = true
  start        = true

  cores  = 1
  memory = 1536
  swap   = 512

  features {
    nesting = true
  }

  rootfs {
    storage = "local-zfs"
    size    = "10G"
  }

  network {
    name   = "eth0"
    bridge = "vmbr0"
    ip     = "192.168.1.71/24"
    gw     = "192.168.1.1"
  }

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "portainer,agent"
}

output "agent_ip" {
  value = "192.168.1.71"
}
