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

resource "proxmox_lxc" "portainer_server" {
  target_node = "pvetest"
  hostname    = "portainer-server"

  ostemplate   = "local:vztmpl/debian-docker-template.tar.gz"
  ostype       = "debian"
  password     = var.lxc_password
  unprivileged = true
  onboot       = true
  start        = true

  cores  = 2
  memory = 3072
  swap   = 1024

  features {
    nesting = true
  }

  rootfs {
    storage = "local-zfs"
    size    = "15G"
  }

  network {
    name   = "eth0"
    bridge = "vmbr0"
    ip     = "192.168.1.70/24"
    gw     = "192.168.1.1"
  }

  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "portainer,server,management"
}

output "portainer_server_ip" {
  value = "192.168.1.70"
}
