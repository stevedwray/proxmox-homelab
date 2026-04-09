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

  # Optional declarative network intent. Existing stacks continue to use the
  # current bridge defaults unless they opt in with stack.network.zone.
  stack_network               = try(local.stack.network, null)
  stack_network_zone          = try(local.stack.network.zone, null)
  network_intent_default_path = "${local.lxc_root}/network/pve-test.yaml"
  effective_network_intent_path = coalesce(
    var.network_intent_path,
    local.network_intent_default_path
  )

  network_intent = local.stack_network_zone != null ? yamldecode(file(local.effective_network_intent_path)) : null

  resolved_zone_attachment_name = local.stack_network_zone != null ? local.network_intent.zones[local.stack_network_zone].attachment : null
  resolved_zone_attachment      = local.resolved_zone_attachment_name != null ? local.network_intent.attachments[local.resolved_zone_attachment_name] : null
  resolved_attachment_type      = local.resolved_zone_attachment != null ? try(local.resolved_zone_attachment.type, "bridge") : "bridge"
  resolved_sdn_attachment       = local.resolved_attachment_type == "sdn_vnet" ? try(local.resolved_zone_attachment.sdn, null) : null

  effective_target_node = local.stack_network_zone != null ? local.network_intent.proxmox.target_node : try(local.stack.target_node, var.proxmox_node)
  effective_pve_host    = local.stack_network_zone != null ? local.network_intent.proxmox.pve_host : try(local.stack.proxmox_host, var.proxmox_host)

  effective_network_bridge = local.resolved_zone_attachment != null ? try(local.resolved_zone_attachment.bridge, "vmbr0") : try(local.stack.network_bridge, "vmbr0")
  effective_vlan_tag       = local.resolved_zone_attachment != null ? try(local.resolved_zone_attachment.vlan_tag, null) : null
  effective_firewall       = local.resolved_zone_attachment != null ? try(local.resolved_zone_attachment.firewall, null) : null

  all_stack_yaml_paths = fileset(local.lxc_root, "stacks/*/stack.yaml")
  all_zone_members = [
    for relpath in local.all_stack_yaml_paths : {
      stack_name  = basename(dirname(relpath))
      zone        = try(yamldecode(file("${local.lxc_root}/${relpath}")).network.zone, null)
      ip_address  = split("/", yamldecode(file("${local.lxc_root}/${relpath}")).ip_address)[0]
      description = try(yamldecode(file("${local.lxc_root}/${relpath}")).hostname, basename(dirname(relpath)))
    }
  ]

  zone_members = try(tomap({
    for zone_name, _zone in local.network_intent.zones :
    zone_name => [
      for member in local.all_zone_members : {
        stack_name  = member.stack_name
        ip_address  = member.ip_address
        description = member.description
      }
      if member.zone == zone_name
    ]
  }), tomap({}))

  inbound_zone_policies = try([
    for policy in local.network_intent.policies : policy
    if try(policy.to, null) == local.stack_network_zone
  ], tolist([]))

  vnet_policy_candidates = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" ? try([
    for policy in local.network_intent.policies : merge(policy, {
      from_attachment_name = try(local.network_intent.zones[policy.from].attachment, null)
      to_attachment_name   = try(local.network_intent.zones[policy.to].attachment, null)
    })
    if try(local.network_intent.attachments[local.network_intent.zones[policy.from].attachment].type, "bridge") == "sdn_vnet" &&
    try(local.network_intent.attachments[local.network_intent.zones[policy.to].attachment].type, "bridge") == "sdn_vnet" &&
    try(local.network_intent.attachments[local.network_intent.zones[policy.from].attachment].sdn.vnet, null) == try(local.resolved_sdn_attachment.vnet, null) &&
    try(local.network_intent.attachments[local.network_intent.zones[policy.to].attachment].sdn.vnet, null) == try(local.resolved_sdn_attachment.vnet, null)
  ], tolist([])) : tolist([])

  effective_firewall_rules = local.stack_network_zone != null && local.effective_firewall == true ? tolist(flatten([
    for policy in local.inbound_zone_policies : [
      for member in try(local.zone_members[policy.from], []) : {
        type        = "in"
        action      = "ACCEPT"
        source      = member.ip_address
        protocol    = lower(policy.protocol)
        destination = join(",", [for port in try(policy.ports, []) : tostring(port)])
        comment     = "${try(local.network_intent.zones[policy.from].description, policy.from)} -> ${try(local.network_intent.zones[policy.to].description, policy.to)} (${member.description})"
      }
    ]
  ])) : tolist([])

  effective_vnet_firewall_rules = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" && local.effective_firewall == true ? tolist(flatten([
    for policy in local.vnet_policy_candidates : flatten([
      for source_member in try(local.zone_members[policy.from], []) : [
        for dest_member in try(local.zone_members[policy.to], []) : [
          for port in try(policy.ports, []) : [
            {
              action         = "ACCEPT"
              source         = source_member.ip_address
              destination    = dest_member.ip_address
              protocol       = lower(policy.protocol)
              port_direction = "d"
              port           = tostring(port)
            },
            {
              action         = "ACCEPT"
              source         = dest_member.ip_address
              destination    = source_member.ip_address
              protocol       = lower(policy.protocol)
              port_direction = "s"
              port           = tostring(port)
            }
          ]
        ]
      ]
    ])
  ])) : tolist([])
}

check "network_layer_runs_only_on_pve_test" {
  assert {
    condition = local.stack_network_zone == null || (
      local.effective_target_node == "pve-test" &&
      local.effective_pve_host == "pve-test.gibbsgreatly.xyz"
    )
    error_message = "Stacks using stack.network.zone must target pve-test (node pve-test, host pve-test.gibbsgreatly.xyz) and must not run on pve."
  }
}

check "network_layer_attachment_type_is_supported" {
  assert {
    condition     = local.stack_network_zone == null || contains(["bridge", "sdn_vnet"], local.resolved_attachment_type)
    error_message = "Network intent attachments must use type 'bridge' or 'sdn_vnet'."
  }
}

check "network_layer_sdn_attachment_is_complete" {
  assert {
    condition = local.stack_network_zone == null || local.resolved_attachment_type != "sdn_vnet" || (
      local.resolved_sdn_attachment != null &&
      try(local.resolved_sdn_attachment.zone, "") != "" &&
      try(local.resolved_sdn_attachment.zone_type, "") != "" &&
      length(try(local.resolved_sdn_attachment.nodes, [])) > 0 &&
      try(local.resolved_sdn_attachment.vnet, "") != ""
    )
    error_message = "Attachments of type 'sdn_vnet' must define sdn.zone, sdn.zone_type, sdn.nodes, and sdn.vnet."
  }
}

# ---------------------------------------------------------------------------
# Proxmox SDN vars (only if network intent selects an SDN VNet attachment)
# Ensures the attachment exists on pve-test before the LXC is created.
# ---------------------------------------------------------------------------
resource "local_file" "network_sdn_vars" {
  count = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" ? 1 : 0

  filename = "${local.stack_dir}/network-sdn-vars.yml"
  content = yamlencode({
    network_sdn_enable     = true
    network_sdn_target     = local.effective_target_node
    network_sdn_pve_host   = local.effective_pve_host
    network_sdn_zone       = try(local.resolved_sdn_attachment.zone, null)
    network_sdn_zone_type  = try(local.resolved_sdn_attachment.zone_type, null)
    network_sdn_nodes      = try(local.resolved_sdn_attachment.nodes, [])
    network_sdn_vnet       = try(local.resolved_sdn_attachment.vnet, null)
    network_sdn_vnet_alias = try(local.resolved_zone_attachment.description, try(local.resolved_sdn_attachment.alias, local.resolved_sdn_attachment.vnet))
    network_sdn_ssh_key    = pathexpand(var.ssh_private_key_path)
  })
}

resource "null_resource" "configure_network_sdn_attachment" {
  count = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" ? 1 : 0

  triggers = {
    sdn_vars = local_file.network_sdn_vars[0].content
  }

  provisioner "local-exec" {
    command     = <<-EOT
      ansible-playbook \
        -i localhost, \
        playbooks/configure-network-sdn-vnet.yml \
        -e '@${local.stack_dir}/network-sdn-vars.yml'
    EOT
    working_dir = local.ansible_dir

    environment = {
      ANSIBLE_HOST_KEY_CHECKING    = "False"
      ANSIBLE_LOCAL_TEMP           = "/tmp/.ansible/tmp"
      ANSIBLE_SSH_CONTROL_PATH_DIR = "/tmp/.ansible/cp"
    }
  }

  depends_on = [local_file.network_sdn_vars]
}

# ---------------------------------------------------------------------------
# LXC container
# ---------------------------------------------------------------------------
module "lxc" {
  source = "./modules/lxc-docker-host"

  target_node  = local.effective_target_node
  hostname     = coalesce(var.stack_hostname, local.stack.hostname)
  vmid         = try(local.stack.vmid, null)
  ip_address   = coalesce(var.stack_ip_address, local.stack.ip_address)
  gateway      = try(local.stack.gateway, var.default_gateway)
  lxc_password = var.lxc_password

  cores               = try(local.stack.cores, 2)
  memory              = try(local.stack.memory, 2048)
  swap                = try(local.stack.swap, 512)
  rootfs_size         = try(local.stack.rootfs_size, 8)
  rootfs_storage      = try(local.stack.rootfs_storage, var.default_storage)
  docker_storage_size = try(local.stack.docker_storage_size, "20G")

  ostemplate       = try(local.stack.ostemplate, "local:vztmpl/debian-docker-template.tar.gz")
  ssh_public_keys  = file(pathexpand(var.ssh_public_key_path))
  tags             = try(local.stack.tags, [local.stack_name])
  network_bridge   = local.effective_network_bridge
  network_firewall = local.effective_firewall == true

  extra_mount_path    = try(local.stack.extra_mount_path, null)
  extra_mount_size    = try(local.stack.extra_mount_size, null)
  extra_mount_storage = try(local.stack.extra_mount_storage, null)

  depends_on = [null_resource.configure_network_sdn_attachment]
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
    app_stack_name      = coalesce(var.stack_app_name, try(local.stack.app_stack_name, null), local.stack_name)
    vmid                = module.lxc.container_id
    pve_host            = local.effective_pve_host
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
      ANSIBLE_HOST_KEY_CHECKING    = "False"
      ANSIBLE_LOCAL_TEMP           = "/tmp/.ansible/tmp"
      ANSIBLE_SSH_CONTROL_PATH_DIR = "/tmp/.ansible/cp"
    }
  }

  depends_on = [local_file.ansible_inventory]
}

# ---------------------------------------------------------------------------
# Proxmox firewall vars (only if network intent enables firewall for this zone)
# ---------------------------------------------------------------------------
resource "local_file" "network_firewall_vars" {
  count = local.stack_network_zone != null && local.resolved_attachment_type == "bridge" && local.effective_firewall == true ? 1 : 0

  filename = "${local.stack_dir}/network-firewall-vars.yml"
  content = yamlencode({
    network_firewall_enable     = true
    network_firewall_policy_in  = "DROP"
    network_firewall_policy_out = "ACCEPT"
    network_firewall_rules      = local.effective_firewall_rules
    network_firewall_vmid       = module.lxc.container_id
    network_firewall_target     = local.effective_target_node
    network_firewall_pve_host   = local.effective_pve_host
  })

  depends_on = [module.lxc]
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
# Proxmox firewall policy apply (only if network intent enables firewall)
# Applies after any guest provisioning to avoid disrupting the existing flow.
# ---------------------------------------------------------------------------
resource "null_resource" "configure_network_firewall" {
  count = local.stack_network_zone != null && local.resolved_attachment_type == "bridge" && local.effective_firewall == true ? 1 : 0

  triggers = {
    container_id      = module.lxc.container_id
    inventory_content = local_file.ansible_inventory.content
    firewall_vars     = local_file.network_firewall_vars[0].content
  }

  provisioner "local-exec" {
    command     = <<-EOT
      ansible-playbook \
        -i '${local.stack_dir}/inventory.yml' \
        playbooks/configure-network-firewall.yml \
        -e '@${local.stack_dir}/network-firewall-vars.yml'
    EOT
    working_dir = local.ansible_dir

    environment = {
      ANSIBLE_HOST_KEY_CHECKING    = "False"
      ANSIBLE_LOCAL_TEMP           = "/tmp/.ansible/tmp"
      ANSIBLE_SSH_CONTROL_PATH_DIR = "/tmp/.ansible/cp"
    }
  }

  depends_on = [
    local_file.ansible_inventory,
    local_file.network_firewall_vars,
    null_resource.configure_keyctl,
    null_resource.ansible_provision,
  ]
}

# ---------------------------------------------------------------------------
# Proxmox VNet firewall vars (only if network intent enables SDN VNet firewall)
# Applies a single VNet-level forward policy for the shared SDN attachment.
# ---------------------------------------------------------------------------
resource "local_file" "network_vnet_firewall_vars" {
  count = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" && local.effective_firewall == true ? 1 : 0

  filename = "${local.stack_dir}/network-vnet-firewall-vars.yml"
  content = yamlencode({
    network_vnet_firewall_enable         = true
    network_vnet_firewall_policy_forward = "DROP"
    network_vnet_firewall_rules          = local.effective_vnet_firewall_rules
    network_vnet_firewall_vnet           = try(local.resolved_sdn_attachment.vnet, null)
    network_vnet_firewall_vmid           = module.lxc.container_id
    network_vnet_firewall_target         = local.effective_target_node
    network_vnet_firewall_pve_host       = local.effective_pve_host
    network_vnet_firewall_ssh_key        = pathexpand(var.ssh_private_key_path)
  })

  depends_on = [module.lxc]
}

resource "null_resource" "configure_network_vnet_firewall" {
  count = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" && local.effective_firewall == true ? 1 : 0

  triggers = {
    container_id       = module.lxc.container_id
    vnet_firewall_vars = local_file.network_vnet_firewall_vars[0].content
  }

  provisioner "local-exec" {
    command     = <<-EOT
      ansible-playbook \
        -i localhost, \
        playbooks/configure-network-vnet-firewall.yml \
        -e '@${local.stack_dir}/network-vnet-firewall-vars.yml'
    EOT
    working_dir = local.ansible_dir

    environment = {
      ANSIBLE_HOST_KEY_CHECKING = "False"
    }
  }

  depends_on = [
    local_file.network_vnet_firewall_vars,
    null_resource.configure_keyctl,
    null_resource.ansible_provision,
  ]
}

# ---------------------------------------------------------------------------
# Portainer cleanup on destroy (only if portainer_agent: true in stack.yaml)
# ---------------------------------------------------------------------------
resource "null_resource" "stack_cleanup" {
  count = try(local.stack.portainer_agent, false) ? 1 : 0

  triggers = {
    stack_name          = local.stack_name
    hostname            = coalesce(var.stack_hostname, local.stack.hostname)
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
