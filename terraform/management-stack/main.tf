# terraform/management-stack/main.tf

terraform {
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "2.9.11"
    }
    null = {
      source = "hashicorp/null"
    }
  }
}

provider "proxmox" {
  pm_api_url          = var.proxmox_api_url
  pm_api_token_id     = var.pm_api_token_id
  pm_api_token_secret = var.pm_api_token_secret
  pm_tls_insecure     = true
}

# Deploy Portainer Server
module "portainer_server" {
  source = "../modules/lxc-docker-host"

  target_node   = var.proxmox_node
  hostname      = var.portainer_hostname
  vmid          = var.portainer_vmid  # Use the variable instead of hardcoded value
  ip_address    = "192.168.1.70/24"
  gateway       = "192.168.1.1"
  
  cores         = 2
  memory        = 3072
  swap          = 1024
  rootfs_size   = "15G"
  
  lxc_password    = var.lxc_password
  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "portainer,server,management"
}

# Generate dynamic Ansible inventory
resource "local_file" "ansible_inventory" {
  filename = "${path.module}/ansible/inventory.yml"
  content = templatefile("${path.module}/inventory.tpl", {
    portainer_hostname = module.portainer_server.hostname
    portainer_ip = replace(module.portainer_server.ip_address, "/24", "")
  })
}

# Run Ansible after inventory is created
resource "null_resource" "run_ansible" {
  triggers = {
    inventory_content = local_file.ansible_inventory.content
    container_id      = module.portainer_server.container_id
  }

  provisioner "local-exec" {
    command     = "sleep 15 && ansible-playbook -i inventory.yml playbook.yml --limit portainer_server"
    working_dir = "${path.module}/ansible"

    environment = {
      ANSIBLE_HOST_KEY_CHECKING = "False"

      # Portainer admin (existing)
      PORTAINER_ADMIN_PASSWORD  = var.lxc_password

      # NPM paths (existing)
      NPM_DATA_SOURCE           = var.npm_data_source
      NPM_LETSENCRYPT_SOURCE    = var.npm_letsencrypt_source
      NPM_DATA_TARGET           = var.npm_data_target
      NPM_LETSENCRYPT_TARGET    = var.npm_letsencrypt_target
    }
  }

  depends_on = [module.portainer_server, local_file.ansible_inventory]
}

# Outputs
output "portainer_server_ip" {
  description = "IP address of the Portainer server"
  value = replace(module.portainer_server.ip_address, "/24", "")
}

output "portainer_server_url" {
  description = "URL to access Portainer"
  value = "http://${replace(module.portainer_server.ip_address, "/24", "")}:9000"
}

output "npm_url" {
  description = "URL to access Nginx Proxy Manager"
  value = "http://${replace(module.portainer_server.ip_address, "/24", "")}:81"
}
