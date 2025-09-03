# terraform/agent-stack/main.tf

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

# Deploy Portainer Agent
module "portainer_agent" {
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
  tags            = "portainer,agent"
}

# Generate dynamic Ansible inventory
resource "local_file" "ansible_inventory" {
  filename = "${path.module}/ansible/inventory.yml"
  content = templatefile("${path.module}/inventory.tpl", {
    agent_hostname = module.portainer_agent.hostname
    agent_ip = replace(module.portainer_agent.ip_address, "/24", "")
  })
}

# Run Ansible after inventory is created
resource "null_resource" "run_ansible" {
  triggers = {
    inventory_content = local_file.ansible_inventory.content
    container_id = module.portainer_agent.container_id
  }

  provisioner "local-exec" {
    command     = "sleep 15 && ansible-playbook -i inventory.yml playbook.yml"
    working_dir = "${path.module}/ansible"

    environment = {
      ANSIBLE_HOST_KEY_CHECKING = "False"
      PORTAINER_ADMIN_PASSWORD  = var.lxc_password  # Temporary - should be separate
    }
  }

  depends_on = [module.portainer_agent, local_file.ansible_inventory]
}

# Add this to terraform/agent-stack/main.tf after the existing null_resource

# Cleanup agent registration on destroy
resource "null_resource" "agent_cleanup" {
  # Store values as triggers so they're available during destroy
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
    
    on_failure = continue  # Don't block destroy if cleanup fails
  }

  depends_on = [module.portainer_agent]
}

output "agent_ip" {
  description = "IP address of the Portainer agent"
  value = replace(module.portainer_agent.ip_address, "/24", "")
}

output "agent_url" {
  description = "URL to access Portainer agent"
  value = "https://${replace(module.portainer_agent.ip_address, "/24", "")}:9001"
}

