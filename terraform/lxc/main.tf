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
# Stack configuration — loaded from the stack's own stack.yaml via Terragrunt.
# Absolute paths are derived from var.stack_yaml_path so they remain correct
# regardless of Terragrunt's working directory.
# ---------------------------------------------------------------------------
locals {
  stack_name = var.stack_name
  stack      = yamldecode(file(var.stack_yaml_path))

  # Derive stable absolute paths from the stack_yaml_path input.
  stack_dir   = dirname(var.stack_yaml_path)      # …/stacks/<name>
  lxc_root    = dirname(dirname(local.stack_dir)) # …/terraform/lxc
  ansible_dir = "${local.lxc_root}/ansible"
}

# ---------------------------------------------------------------------------
# LXC container
# ---------------------------------------------------------------------------
module "lxc" {
  source = "./modules/lxc-docker-host"

  target_node  = try(local.stack.target_node, var.proxmox_node)
  hostname     = local.stack.hostname
  vmid         = try(local.stack.vmid, null)
  ip_address   = local.stack.ip_address
  gateway      = try(local.stack.gateway, var.default_gateway)
  lxc_password = var.lxc_password

  cores               = try(local.stack.cores, 2)
  memory              = try(local.stack.memory, 2048)
  swap                = try(local.stack.swap, 512)
  rootfs_size         = try(local.stack.rootfs_size, 8)
  rootfs_storage      = try(local.stack.rootfs_storage, var.default_storage)
  docker_storage_size = try(local.stack.docker_storage_size, "20G")

  ostemplate      = try(local.stack.ostemplate, "local:vztmpl/debian-docker-template.tar.gz")
  ssh_public_keys = file(pathexpand(var.ssh_public_key_path))
  tags            = try(local.stack.tags, [local.stack_name])

  extra_mount_path    = try(local.stack.extra_mount_path, null)
  extra_mount_size    = try(local.stack.extra_mount_size, null)
  extra_mount_storage = try(local.stack.extra_mount_storage, null)
}

# ---------------------------------------------------------------------------
# Ansible inventory (always generated)
# ---------------------------------------------------------------------------
resource "local_file" "ansible_inventory" {
  filename = "${local.stack_dir}/inventory.yml"
  content = templatefile("${local.lxc_root}/templates/inventory.tpl", {
    stack_name          = local.stack_name
    hostname            = module.lxc.hostname
    ip_address          = replace(module.lxc.ip_address, "/24", "")
    ssh_key             = var.ssh_private_key_path
    ansible_playbook    = try(local.stack.ansible_playbook, "")
    portainer_server_ip = try(local.stack.portainer_server_ip, var.portainer_server_ip)
    app_stack_name      = try(local.stack.app_stack_name, local.stack_name)
    vmid                = module.lxc.container_id
    pve_host            = var.proxmox_host
  })
}

# ---------------------------------------------------------------------------
# keyctl feature flag via Ansible (only if keyctl: true in stack.yaml)
# Requires root@pam — cannot be set via API token.
# ---------------------------------------------------------------------------
resource "null_resource" "configure_keyctl" {
  count = try(local.stack.keyctl, false) ? 1 : 0

  triggers = {
    container_id = module.lxc.container_id
  }

  provisioner "local-exec" {
    command     = <<-EOT
      ansible-playbook \
        -i '${local.stack_dir}/inventory.yml' \
        playbooks/configure-keyctl.yml
    EOT
    working_dir = local.ansible_dir

    environment = {
      ANSIBLE_HOST_KEY_CHECKING = "False"
    }
  }

  depends_on = [local_file.ansible_inventory]
}

# ---------------------------------------------------------------------------
# Ansible provisioning (only if ansible_playbook is set in stack.yaml)
# ---------------------------------------------------------------------------
resource "null_resource" "ansible_provision" {
  count = try(local.stack.ansible_playbook, "") != "" ? 1 : 0

  triggers = {
    container_id      = module.lxc.container_id
    inventory_content = local_file.ansible_inventory.content
    playbook          = try(local.stack.ansible_playbook, "")
  }

  provisioner "local-exec" {
    command     = <<-EOT
      ansible-playbook \
        -i '${local.stack_dir}/inventory.yml' \
        'playbooks/${try(local.stack.ansible_playbook, "noop")}.yml'
    EOT
    working_dir = local.ansible_dir

    environment = {
      ANSIBLE_HOST_KEY_CHECKING = "False"
      PORTAINER_ADMIN_PASSWORD  = var.portainer_admin_password
    }
  }

  depends_on = [local_file.ansible_inventory, null_resource.configure_keyctl]
}

# ---------------------------------------------------------------------------
# Portainer cleanup on destroy (only if portainer_agent: true in stack.yaml)
# ---------------------------------------------------------------------------
resource "null_resource" "stack_cleanup" {
  count = try(local.stack.portainer_agent, false) ? 1 : 0

  triggers = {
    stack_name          = local.stack_name
    hostname            = local.stack.hostname
    portainer_server_ip = try(local.stack.portainer_server_ip, var.portainer_server_ip)
    # Stored as a trigger so destroy provisioner has a stable absolute path.
    ansible_dir = local.ansible_dir
  }

  provisioner "local-exec" {
    when        = destroy
    command     = <<-EOT
      export STACK_NAME="${self.triggers.stack_name}"
      export AGENT_HOSTNAME="${self.triggers.hostname}"
      export PORTAINER_SERVER_IP="${self.triggers.portainer_server_ip}"
      export ANSIBLE_HOST_KEY_CHECKING="False"
      ansible-playbook -i localhost, playbooks/cleanup.yml
    EOT
    working_dir = self.triggers.ansible_dir
    on_failure  = continue
  }

  depends_on = [module.lxc]
}
