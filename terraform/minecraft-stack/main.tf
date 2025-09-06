# terraform/minecraft-stack/main.tf

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

# Deploy Minecraft Server Host
module "minecraft_host" {
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
  tags            = "minecraft,gaming"
}

# Generate dynamic Ansible inventory
resource "local_file" "ansible_inventory" {
  filename = "${path.module}/ansible/inventory.yml"
  content = templatefile("${path.module}/inventory.tpl", {
    agent_hostname = module.minecraft_host.hostname
    agent_ip = replace(module.minecraft_host.ip_address, "/24", "")
  })
}

# Run Ansible after inventory is created
resource "null_resource" "run_ansible" {
  triggers = {
    inventory_content = local_file.ansible_inventory.content
    container_id = module.minecraft_host.container_id
  }

  provisioner "local-exec" {
    command     = "sleep 15 && ansible-playbook -i inventory.yml playbook.yml"
    working_dir = "${path.module}/ansible"

    environment = {
      PORTAINER_ADMIN_PASSWORD  = var.lxc_password
      REGISTRY_MIRROR_IP        = var.registry_mirror_ip
      ENABLE_REGISTRY_MIRROR    = var.enable_registry_mirror
    }
  }

  depends_on = [module.minecraft_host, local_file.ansible_inventory]
}

# Cleanup minecraft stack registration on destroy
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

  depends_on = [module.minecraft_host]
}

output "minecraft_server_ip" {
  description = "IP address of the minecraft server"
  value = replace(module.minecraft_host.ip_address, "/24", "")
}

output "minecraft_server_connection" {
  description = "Minecraft server connection details"
  value = "${replace(module.minecraft_host.ip_address, "/24", "")}:25566"
}

output "registry_mirror_ip" {
  description = "IP address of the configured registry mirror"
  value = var.enable_registry_mirror ? var.registry_mirror_ip : "Registry mirror disabled"
}