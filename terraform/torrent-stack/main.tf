# terraform/torrent-stack/main.tf

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

# Deploy Torrent Stack Host
module "torrent_stack_host" {
  source = "../modules/lxc-docker-host"

  target_node   = var.proxmox_node
  hostname      = var.agent_hostname
  vmid          = var.agent_vmid
  ip_address    = var.agent_ip_address
  gateway       = "192.168.1.1"
  
  cores         = var.agent_cores
  memory        = var.agent_memory
  swap          = 512
  rootfs_size   = var.agent_rootfs_size
  
  lxc_password    = var.lxc_password
  ssh_public_keys = file("~/.ssh/id_rsa.pub")
  tags            = "torrent,media"
}

# Generate dynamic Ansible inventory
resource "local_file" "ansible_inventory" {
  filename = "${path.module}/ansible/inventory.yml"
  content = templatefile("${path.module}/inventory.tpl", {
    agent_hostname = module.torrent_stack_host.hostname
    agent_ip = replace(module.torrent_stack_host.ip_address, "/24", "")
  })
}

# Run Ansible after inventory is created
resource "null_resource" "run_ansible" {
  triggers = {
    inventory_content = local_file.ansible_inventory.content
    container_id = module.torrent_stack_host.container_id
  }

  provisioner "local-exec" {
    command     = "sleep 15 && ansible-playbook -i inventory.yml playbook.yml"
    working_dir = "${path.module}/ansible"

    environment = {
      PORTAINER_ADMIN_PASSWORD  = var.lxc_password
      REGISTRY_MIRROR_IP        = var.registry_mirror_ip
      ENABLE_REGISTRY_MIRROR    = var.enable_registry_mirror
      CONTAINER_VMID           = module.torrent_stack_host.container_id
      PROXMOX_HOST             = "pvetest.gibbsgreatly.xyz"
    }
  }

  depends_on = [module.torrent_stack_host, local_file.ansible_inventory]
}

# Cleanup torrent stack registration on destroy
resource "null_resource" "agent_cleanup" {
  triggers = {
    agent_hostname = var.agent_hostname
    portainer_server_ip = var.portainer_server_ip
    working_dir = "${path.module}/ansible"
  }
  
  provisioner "local-exec" {
    when    = destroy
    command = <<-EOT
      export AGENT_HOSTNAME="${self.triggers.agent_hostname}"
      export PORTAINER_SERVER_IP="${self.triggers.portainer_server_ip}"
      export ANSIBLE_HOST_KEY_CHECKING="False"
      ansible-playbook -i inventory.yml cleanup.yml
    EOT
    working_dir = self.triggers.working_dir
    
    on_failure = continue
  }

  depends_on = [module.torrent_stack_host]
}

output "torrent_stack_ip" {
  description = "IP address of the torrent stack"
  value = replace(module.torrent_stack_host.ip_address, "/24", "")
}

output "service_urls" {
  description = "URLs to access torrent stack services"
  value = {
    qbittorrent  = "http://${replace(module.torrent_stack_host.ip_address, "/24", "")}:8080"
    prowlarr     = "http://${replace(module.torrent_stack_host.ip_address, "/24", "")}:9696"
    radarr       = "http://${replace(module.torrent_stack_host.ip_address, "/24", "")}:7878"
    sonarr       = "http://${replace(module.torrent_stack_host.ip_address, "/24", "")}:8989"
    lidarr       = "http://${replace(module.torrent_stack_host.ip_address, "/24", "")}:8686"
    flaresolverr = "http://${replace(module.torrent_stack_host.ip_address, "/24", "")}:8191"
  }
}

output "debug_container_id" {
  value = module.torrent_stack_host.container_id
}
