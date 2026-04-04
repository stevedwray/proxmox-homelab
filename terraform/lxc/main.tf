terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.78"
    }
  }
}

provider "proxmox" {
  endpoint  = var.proxmox_api_url
  api_token = "${var.pm_api_token_id}=${var.pm_api_token_secret}"
  insecure  = var.pm_tls_insecure
}

# ---------------------------------------------------------------------------
# Load stack definitions from YAML files
# ---------------------------------------------------------------------------
locals {
  stack_dirs = fileset("${path.module}/stacks", "*/stack.yaml")
  stacks = {
    for f in local.stack_dirs :
    dirname(f) => yamldecode(file("${path.module}/stacks/${f}"))
  }
}

# ---------------------------------------------------------------------------
# Create one LXC container per stack definition
# ---------------------------------------------------------------------------
module "lxc" {
  source   = "./modules/lxc-docker-host"
  for_each = local.stacks

  target_node  = try(each.value.target_node, var.proxmox_node)
  hostname     = each.value.hostname
  vmid         = try(each.value.vmid, null)
  ip_address   = each.value.ip_address
  gateway      = try(each.value.gateway, var.default_gateway)
  lxc_password = var.lxc_password

  cores              = try(each.value.cores, 2)
  memory             = try(each.value.memory, 2048)
  swap               = try(each.value.swap, 512)
  rootfs_size        = try(each.value.rootfs_size, 8)
  rootfs_storage     = try(each.value.rootfs_storage, var.default_storage)
  docker_storage_size = try(each.value.docker_storage_size, "20G")

  ostemplate      = try(each.value.ostemplate, "local:vztmpl/debian-docker-template.tar.gz")
  ssh_public_keys = file(pathexpand(var.ssh_public_key_path))
  tags            = try(each.value.tags, [each.key])
}

# ---------------------------------------------------------------------------
# Set keyctl feature flag via PVE CLI (requires root@pam, not available via API token)
# ---------------------------------------------------------------------------
resource "null_resource" "set_keyctl" {
  for_each = {
    for k, v in local.stacks : k => v
    if try(v.keyctl, false)
  }

  triggers = {
    container_id = module.lxc[each.key].container_id
  }

  provisioner "remote-exec" {
    inline = [
      "pct set ${module.lxc[each.key].container_id} -features nesting=1,keyctl=1",
      "pct reboot ${module.lxc[each.key].container_id}",
      "sleep 10",
    ]

    connection {
      type        = "ssh"
      host        = var.proxmox_host
      user        = var.ssh_pve_user
      private_key = file(pathexpand(var.ssh_private_key_path))
    }
  }

  depends_on = [module.lxc]
}

# ---------------------------------------------------------------------------
# Generate per-stack Ansible inventory
# ---------------------------------------------------------------------------
resource "local_file" "ansible_inventory" {
  for_each = local.stacks

  filename = "${path.module}/stacks/${each.key}/inventory.yml"
  content = templatefile("${path.module}/templates/inventory.tpl", {
    stack_name = each.key
    hostname   = module.lxc[each.key].hostname
    ip_address = replace(module.lxc[each.key].ip_address, "/24", "")
    ssh_key    = var.ssh_private_key_path
    ansible_playbook    = try(each.value.ansible_playbook, "")
    portainer_server_ip = try(each.value.portainer_server_ip, var.portainer_server_ip)
    app_stack_name      = try(each.value.app_stack_name, each.key)
  })
}

# ---------------------------------------------------------------------------
# Run Ansible provisioning per stack (only if ansible_playbook is defined)
# ---------------------------------------------------------------------------
resource "null_resource" "ansible_provision" {
  for_each = {
    for k, v in local.stacks : k => v
    if try(v.ansible_playbook, "") != ""
  }

  triggers = {
    container_id      = module.lxc[each.key].container_id
    inventory_content = local_file.ansible_inventory[each.key].content
    playbook          = each.value.ansible_playbook
  }

  provisioner "local-exec" {
    command     = <<-EOT
      sleep 15
      ansible-playbook \
        -i ../stacks/${each.key}/inventory.yml \
        playbooks/${each.value.ansible_playbook}.yml
    EOT
    working_dir = "${path.module}/ansible"

    environment = {
      ANSIBLE_HOST_KEY_CHECKING = "False"
      PORTAINER_ADMIN_PASSWORD  = var.portainer_admin_password
    }
  }

  depends_on = [local_file.ansible_inventory, null_resource.set_keyctl]
}

# ---------------------------------------------------------------------------
# Cleanup on destroy: deregister from Portainer if applicable
# ---------------------------------------------------------------------------
resource "null_resource" "stack_cleanup" {
  for_each = {
    for k, v in local.stacks : k => v
    if try(v.portainer_agent, false)
  }

  triggers = {
    stack_name          = each.key
    hostname            = each.value.hostname
    portainer_server_ip = try(each.value.portainer_server_ip, var.portainer_server_ip)
    working_dir         = "${path.module}/ansible"
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<-EOT
      export STACK_NAME="${self.triggers.stack_name}"
      export AGENT_HOSTNAME="${self.triggers.hostname}"
      export PORTAINER_SERVER_IP="${self.triggers.portainer_server_ip}"
      export ANSIBLE_HOST_KEY_CHECKING="False"
      ansible-playbook -i localhost, playbooks/cleanup.yml
    EOT
    working_dir = self.triggers.working_dir
    on_failure  = continue
  }

  depends_on = [module.lxc]
}
