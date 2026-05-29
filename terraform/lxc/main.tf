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
  stack_template_vars = {
    lab_ip_portainer      = var.lab_ip_portainer
    lab_ip_authentik      = var.lab_ip_authentik
    lab_ip_step_ca        = var.lab_ip_step_ca
    lab_ip_monitoring     = var.lab_ip_monitoring
    lab_ip_dns            = var.lab_ip_dns
    lab_ip_proxy          = var.lab_ip_proxy
    lab_ip_harbor         = var.lab_ip_harbor
    lab_ip_netbox         = var.lab_ip_netbox
    lab_ip_apt_cacher     = var.lab_ip_apt_cacher
    lab_ip_ci_runner      = var.lab_ip_ci_runner
    lab_gw_mgmt           = var.lab_gw_mgmt
    lab_gw_edge           = var.lab_gw_edge
    lab_gw_infra          = var.lab_gw_infra
    lab_gw_build          = var.lab_gw_build
    lab_subnet_mgmt_cidr  = var.lab_subnet_mgmt_cidr
    lab_subnet_edge_cidr  = var.lab_subnet_edge_cidr
    lab_subnet_infra_cidr = var.lab_subnet_infra_cidr
    lab_subnet_build_cidr = var.lab_subnet_build_cidr
    proxmox_host          = var.proxmox_host
  }
  stack = yamldecode(templatefile(var.stack_yaml_path, local.stack_template_vars))

  # Derive stable absolute paths from the stack_yaml_path input.
  stack_dir          = dirname(var.stack_yaml_path)      # …/stacks/<name>
  lxc_root           = dirname(dirname(local.stack_dir)) # …/terraform/lxc
  ansible_dir        = "${local.lxc_root}/ansible"
  ansible_cfg        = "${local.ansible_dir}/ansible.cfg"
  ansible_roles_path = "${local.ansible_dir}/roles"

  # Optional declarative network intent. Existing stacks continue to use the
  # current bridge defaults unless they opt in with stack.network.zone.
  stack_network                 = try(local.stack.network, null)
  stack_network_zone            = try(local.stack.network.zone, null)
  requested_network_access_path = try(local.stack.network.access_path, null)
  effective_proxmox_node        = try(local.stack.proxmox_node, var.proxmox_node)
  storage_manifest_default_path = "${local.lxc_root}/storage/${local.effective_proxmox_node}.yaml"
  effective_storage_manifest_path = coalesce(
    var.storage_manifest_path,
    local.storage_manifest_default_path
  )
  storage_manifest_exists = fileexists(local.effective_storage_manifest_path)
  storage_manifest        = try(yamldecode(file(local.effective_storage_manifest_path)), {})

  # Transitional compatibility: consume legacy stack fields only as selectors
  # into manifest mappings. Root resolves concrete backends before module call.
  legacy_rootfs_storage      = try(local.stack.rootfs_storage, null)
  legacy_extra_mount_storage = try(local.stack.extra_mount_storage, null)
  legacy_ostemplate          = try(local.stack.ostemplate, null)
  legacy_ostemplate_parts    = local.legacy_ostemplate != null ? split(":", local.legacy_ostemplate) : []
  legacy_template_storage    = length(local.legacy_ostemplate_parts) == 2 ? local.legacy_ostemplate_parts[0] : null
  legacy_template_name       = length(local.legacy_ostemplate_parts) == 2 ? trimprefix(local.legacy_ostemplate_parts[1], "vztmpl/") : null

  resolved_storage_profile = coalesce(
    try(local.stack.storage_profile, null),
    try(local.storage_manifest.legacy_rootfs_storage_profiles[local.legacy_rootfs_storage], null),
    try(local.storage_manifest.defaults.storage_profile, null)
  )
  resolved_storage_profile_mapping    = try(local.storage_manifest.profiles[local.resolved_storage_profile], null)
  resolved_rootfs_storage             = try(local.resolved_storage_profile_mapping.rootfs_storage, null)
  resolved_docker_storage             = coalesce(try(local.resolved_storage_profile_mapping.docker_storage, null), local.resolved_rootfs_storage)
  docker_mount_declared_size          = try(local.stack.docker_mount.size, null)
  docker_mount_declared_backup_policy = try(local.stack.docker_mount.backup_policy, null)
  legacy_docker_storage_size          = try(local.stack.docker_storage_size, null)
  resolved_docker_storage_size = coalesce(
    local.docker_mount_declared_size,
    local.legacy_docker_storage_size,
    "20G"
  )
  resolved_docker_mount_backup_policy  = coalesce(local.docker_mount_declared_backup_policy, "include")
  resolved_docker_mount_backup_enabled = local.resolved_docker_mount_backup_policy == "include"
  docker_storage_size_mismatch = (
    local.docker_mount_declared_size != null &&
    local.legacy_docker_storage_size != null &&
    tostring(local.docker_mount_declared_size) != tostring(local.legacy_docker_storage_size)
  )

  # Canonical extra_mount block support (while keeping legacy fields compatible)
  extra_mount_declared                      = try(local.stack.extra_mount, null)
  extra_mount_declared_path                 = try(local.extra_mount_declared.path, null)
  extra_mount_declared_size                 = try(local.extra_mount_declared.size, null)
  extra_mount_declared_profile              = try(local.extra_mount_declared.profile, null)
  extra_mount_declared_backup_policy        = try(local.extra_mount_declared.backup_policy, null)
  extra_mount_declared_resize_control_plane = try(local.extra_mount_declared.resize_control_plane, null)
  extra_mount_declared_mutation_policy      = try(local.extra_mount_declared.mutation_policy, null)
  resolved_extra_mount_path                 = local.extra_mount_declared_path != null ? local.extra_mount_declared_path : try(local.stack.extra_mount_path, null)
  resolved_extra_mount_size                 = local.extra_mount_declared_size != null ? local.extra_mount_declared_size : try(local.stack.extra_mount_size, null)
  resolved_extra_mount_backup_policy        = coalesce(local.extra_mount_declared_backup_policy, "include")
  resolved_extra_mount_backup_enabled       = local.resolved_extra_mount_backup_policy == "include"

  resolved_extra_mount_profile = coalesce(
    local.extra_mount_declared_profile,
    try(local.stack.extra_mount_profile, null),
    try(local.storage_manifest.legacy_extra_mount_storage_profiles[local.legacy_extra_mount_storage], null),
    try(local.storage_manifest.defaults.extra_mount_profile, null),
    local.resolved_storage_profile
  )
  resolved_extra_mount_profile_mapping = try(local.storage_manifest.extra_mount_profiles[local.resolved_extra_mount_profile], null)
  # Resolve extra mount storage only when either canonical or legacy path/size is present
  resolved_extra_mount_storage = local.resolved_extra_mount_path != null ? coalesce(
    try(local.resolved_extra_mount_profile_mapping.storage, null),
    local.resolved_rootfs_storage
  ) : null
  resolved_extra_mount_backend_type = try(local.storage_manifest.storage_backends[local.resolved_extra_mount_storage].backend_type, null)

  extra_mount_size_mismatch = (
    local.extra_mount_declared_size != null &&
    try(local.stack.extra_mount_size, null) != null &&
    tostring(local.extra_mount_declared_size) != tostring(try(local.stack.extra_mount_size, null))
  )

  resolved_template_profile = coalesce(
    try(local.stack.template_profile, null),
    try(local.storage_manifest.legacy_template_storage_profiles[local.legacy_template_storage], null),
    try(local.storage_manifest.defaults.template_profile, null)
  )
  resolved_template_profile_mapping = try(local.storage_manifest.template_profiles[local.resolved_template_profile], null)
  resolved_template_storage         = try(local.resolved_template_profile_mapping.storage, null)
  resolved_template_name = coalesce(
    try(local.stack.template_name, null),
    local.legacy_template_name,
    try(local.storage_manifest.templates.default.name, null)
  )
  resolved_ostemplate = "${local.resolved_template_storage}:vztmpl/${local.resolved_template_name}"

  storage_backend_catalog = try(local.storage_manifest.storage_backends, {})
  resolved_storage_backends = toset(compact([
    local.resolved_rootfs_storage,
    local.resolved_docker_storage,
    local.resolved_extra_mount_storage,
    local.resolved_template_storage,
  ]))

  network_intent_default_path = "${local.lxc_root}/network/${local.effective_proxmox_node}.yaml"
  effective_network_intent_path = coalesce(
    var.network_intent_path,
    local.network_intent_default_path
  )

  network_intent                    = local.stack_network_zone != null ? yamldecode(templatefile(local.effective_network_intent_path, local.stack_template_vars)) : null
  effective_zone_members_index_path = trimsuffix(local.effective_network_intent_path, ".yaml") != local.effective_network_intent_path ? "${trimsuffix(local.effective_network_intent_path, ".yaml")}.zone-members.yaml" : "${local.effective_network_intent_path}.zone-members.yaml"

  resolved_zone_attachment_name = local.stack_network_zone != null ? local.network_intent.zones[local.stack_network_zone].attachment : null
  resolved_zone_attachment      = local.resolved_zone_attachment_name != null ? local.network_intent.attachments[local.resolved_zone_attachment_name] : null
  resolved_attachment_type      = local.resolved_zone_attachment != null ? try(local.resolved_zone_attachment.type, "bridge") : "bridge"
  resolved_sdn_attachment       = local.resolved_attachment_type == "sdn_vnet" ? try(local.resolved_zone_attachment.sdn, null) : null
  resolved_sdn_subnet           = local.resolved_sdn_attachment != null ? try(local.resolved_sdn_attachment.subnet, null) : null
  resolved_sdn_gateway          = local.resolved_sdn_attachment != null ? try(local.resolved_sdn_attachment.gateway, null) : null
  resolved_sdn_snat             = local.resolved_sdn_attachment != null ? try(local.resolved_sdn_attachment.snat, null) : null
  effective_dns_server          = coalesce(try(local.stack.dns_server, null), local.resolved_sdn_gateway, try(local.stack.gateway, null), var.default_gateway)

  normalized_network_access_path = local.requested_network_access_path == null ? null : try(lower(trimspace(local.requested_network_access_path)), null)
  # Session 4 migration contract:
  # - sdn_vnet defaults to direct SSH
  # - bridge/default path preserves ProxyJump compatibility behavior
  effective_network_access_path = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" ? coalesce(local.normalized_network_access_path, "direct") : coalesce(local.normalized_network_access_path, "proxyjump_compat")

  effective_target_node = local.stack_network_zone != null ? local.network_intent.proxmox.target_node : try(local.stack.target_node, local.effective_proxmox_node)
  effective_pve_host    = local.stack_network_zone != null ? local.network_intent.proxmox.pve_host : try(local.stack.proxmox_host, var.proxmox_host)
  use_proxyjump         = local.effective_network_access_path == "proxyjump_compat" && local.effective_pve_host != ""

  effective_network_bridge = local.resolved_zone_attachment != null ? try(local.resolved_zone_attachment.bridge, "vmbr0") : try(local.stack.network_bridge, "vmbr0")
  effective_vlan_tag       = local.resolved_zone_attachment != null ? try(local.resolved_zone_attachment.vlan_tag, null) : null
  effective_firewall       = local.resolved_zone_attachment != null ? try(local.resolved_zone_attachment.firewall, null) : null

  all_stack_yaml_paths = fileset(local.lxc_root, "stacks/*/stack.yaml")
  all_zone_members = [
    for relpath in local.all_stack_yaml_paths : {
      stack_name  = basename(dirname(relpath))
      zone        = try(yamldecode(templatefile("${local.lxc_root}/${relpath}", local.stack_template_vars)).network.zone, null)
      ip_address  = split("/", yamldecode(templatefile("${local.lxc_root}/${relpath}", local.stack_template_vars)).ip_address)[0]
      gateway     = try(yamldecode(templatefile("${local.lxc_root}/${relpath}", local.stack_template_vars)).gateway, null)
      description = try(yamldecode(templatefile("${local.lxc_root}/${relpath}", local.stack_template_vars)).hostname, basename(dirname(relpath)))
    }
  ]
  # When the network intent declares a per-zone gateway, use it to keep
  # pve-test zone membership from silently absorbing stacks from other
  # environments that happen to reuse the same zone name.
  zone_gateways = local.stack_network_zone != null ? tomap({
    for zone_name, zone in local.network_intent.zones :
    zone_name => try(local.network_intent.attachments[zone.attachment].sdn.gateway, null)
  }) : tomap({})

  inferred_zone_members = local.stack_network_zone != null ? tomap({
    for zone_name, _zone in local.network_intent.zones :
    zone_name => [
      for member in local.all_zone_members : {
        stack_name  = member.stack_name
        ip_address  = member.ip_address
        description = member.description
      }
      if member.zone == zone_name
      && (
        try(local.zone_gateways[zone_name], null) == null ||
        member.gateway == try(local.zone_gateways[zone_name], null)
      )
    ]
  }) : tomap({})
  generated_zone_members_index = local.stack_network_zone != null && fileexists(local.effective_zone_members_index_path) ? yamldecode(templatefile(local.effective_zone_members_index_path, local.stack_template_vars)) : null
  zone_members                 = local.generated_zone_members_index != null ? try(tomap(local.generated_zone_members_index.zones), tomap({})) : local.inferred_zone_members

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

check "network_intent_node_matches_proxmox_node" {
  assert {
    condition     = local.stack_network_zone == null || local.network_intent.proxmox.target_node == local.effective_proxmox_node
    error_message = "Network intent file targets '${try(local.network_intent.proxmox.target_node, "unknown")}' but effective proxmox_node is '${local.effective_proxmox_node}'. Ensure the correct intent file exists for this environment."
  }
}

check "network_layer_attachment_type_is_supported" {
  assert {
    condition     = local.stack_network_zone == null || contains(["bridge", "sdn_vnet"], local.resolved_attachment_type)
    error_message = "Network intent attachments must use type 'bridge' or 'sdn_vnet'."
  }
}

check "network_access_path_is_supported" {
  assert {
    condition     = local.normalized_network_access_path == null || contains(["direct", "proxyjump_compat"], local.normalized_network_access_path)
    error_message = "stack.network.access_path must be either 'direct' or 'proxyjump_compat' when set."
  }
}

check "network_access_path_proxyjump_requires_pve_host" {
  assert {
    condition     = local.effective_network_access_path != "proxyjump_compat" || local.effective_pve_host != ""
    error_message = "stack.network.access_path is 'proxyjump_compat' but no pve_host is available for ProxyJump."
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

check "network_layer_sdn_attachment_egress_is_complete" {
  assert {
    condition = local.stack_network_zone == null || local.resolved_attachment_type != "sdn_vnet" || (
      !anytrue([
        local.resolved_sdn_subnet != null && local.resolved_sdn_subnet != "",
        local.resolved_sdn_gateway != null && local.resolved_sdn_gateway != "",
        try(local.resolved_sdn_snat, null) != null,
        ]) || alltrue([
        local.resolved_sdn_subnet != null && local.resolved_sdn_subnet != "",
        local.resolved_sdn_gateway != null && local.resolved_sdn_gateway != "",
        try(local.resolved_sdn_snat, null) != null,
      ])
    )
    error_message = "SDN attachments that define egress must set subnet, gateway, and snat together."
  }
}

check "storage_manifest_exists" {
  assert {
    condition     = local.storage_manifest_exists
    error_message = "Storage manifest is missing at '${local.effective_storage_manifest_path}'."
  }
}

check "legacy_rootfs_storage_mapping_exists" {
  assert {
    condition     = local.legacy_rootfs_storage == null || can(local.storage_manifest.legacy_rootfs_storage_profiles[local.legacy_rootfs_storage])
    error_message = "Legacy rootfs_storage '${coalesce(local.legacy_rootfs_storage, "<unset>")}' is not mapped in '${local.effective_storage_manifest_path}'."
  }
}

check "legacy_extra_mount_storage_mapping_exists" {
  assert {
    condition     = local.legacy_extra_mount_storage == null || can(local.storage_manifest.legacy_extra_mount_storage_profiles[local.legacy_extra_mount_storage])
    error_message = "Legacy extra_mount_storage '${coalesce(local.legacy_extra_mount_storage, "<unset>")}' is not mapped in '${local.effective_storage_manifest_path}'."
  }
}

check "legacy_ostemplate_mapping_exists" {
  assert {
    condition = local.legacy_ostemplate == null || (
      length(local.legacy_ostemplate_parts) == 2 &&
      startswith(local.legacy_ostemplate_parts[1], "vztmpl/") &&
      can(local.storage_manifest.legacy_template_storage_profiles[local.legacy_template_storage])
    )
    error_message = "Legacy ostemplate must match '<storage>:vztmpl/<name>' and map storage via legacy_template_storage_profiles in '${local.effective_storage_manifest_path}'."
  }
}

check "storage_profile_resolves" {
  assert {
    condition = (
      local.resolved_storage_profile != null &&
      local.resolved_storage_profile_mapping != null &&
      local.resolved_rootfs_storage != null &&
      local.resolved_docker_storage != null
    )
    error_message = "Unable to resolve storage_profile for stack '${local.stack_name}'."
  }
}

check "extra_mount_profile_resolves" {
  assert {
    condition = local.resolved_extra_mount_path == null || (
      local.resolved_extra_mount_profile != null &&
      local.resolved_extra_mount_profile_mapping != null &&
      local.resolved_extra_mount_storage != null
    )
    error_message = "Stack '${local.stack_name}' defines extra_mount_path but no resolvable extra mount storage profile."
  }
}

check "template_profile_resolves" {
  assert {
    condition = (
      local.resolved_template_profile != null &&
      local.resolved_template_profile_mapping != null &&
      local.resolved_template_storage != null &&
      local.resolved_template_name != null
    )
    error_message = "Unable to resolve template profile/name for stack '${local.stack_name}'."
  }
}

check "resolved_backends_declared" {
  assert {
    condition     = alltrue([for backend in local.resolved_storage_backends : contains(keys(local.storage_backend_catalog), backend)])
    error_message = "Resolved storage backend(s) for stack '${local.stack_name}' are missing from storage_backends in '${local.effective_storage_manifest_path}'."
  }
}

check "rootfs_backend_supports_required_content" {
  assert {
    condition     = contains(try(local.storage_backend_catalog[local.resolved_rootfs_storage].content_types, []), coalesce(try(local.resolved_storage_profile_mapping.rootfs_required_content_type, null), "rootdir"))
    error_message = "Resolved rootfs backend '${local.resolved_rootfs_storage}' does not advertise required content type for stack '${local.stack_name}'."
  }
}

check "docker_backend_supports_required_content" {
  assert {
    condition     = contains(try(local.storage_backend_catalog[local.resolved_docker_storage].content_types, []), coalesce(try(local.resolved_storage_profile_mapping.docker_required_content_type, null), "rootdir"))
    error_message = "Resolved docker backend '${local.resolved_docker_storage}' does not advertise required content type for stack '${local.stack_name}'."
  }
}

check "extra_mount_canonical_legacy_mismatch" {
  assert {
    condition = !(
      (local.extra_mount_declared_path != null && try(local.stack.extra_mount_path, null) != null && tostring(local.extra_mount_declared_path) != tostring(try(local.stack.extra_mount_path, null))) ||
      (local.extra_mount_declared_size != null && try(local.stack.extra_mount_size, null) != null && tostring(local.extra_mount_declared_size) != tostring(try(local.stack.extra_mount_size, null))) ||
      (local.extra_mount_declared_profile != null && try(local.stack.extra_mount_profile, null) != null && tostring(local.extra_mount_declared_profile) != tostring(try(local.stack.extra_mount_profile, null)))
    )
    error_message = "Canonical extra_mount fields (extra_mount.*) must match legacy extra_mount_path/size/profile while both are present"
  }
}

check "docker_mount_size_contract_is_consistent" {
  assert {
    condition     = !local.docker_storage_size_mismatch
    error_message = "Stack '${local.stack_name}' declares mismatched docker mount sizes: docker_mount.size must match legacy docker_storage_size while both are present."
  }
}

check "docker_mount_backup_policy_is_supported" {
  assert {
    condition     = contains(["include", "exclude"], local.resolved_docker_mount_backup_policy)
    error_message = "Stack '${local.stack_name}' must set docker_mount.backup_policy to 'include' or 'exclude'."
  }
}

check "extra_mount_backend_supports_required_content" {
  assert {
    condition = local.resolved_extra_mount_path == null || contains(
      try(local.storage_backend_catalog[local.resolved_extra_mount_storage].content_types, []),
      coalesce(try(local.resolved_extra_mount_profile_mapping.required_content_type, null), "rootdir")
    )
    error_message = "Resolved extra mount backend '${coalesce(local.resolved_extra_mount_storage, "<unset>")}' does not advertise required content type for stack '${local.stack_name}'."
  }
}

check "extra_mount_backup_policy_is_supported" {
  assert {
    condition     = local.resolved_extra_mount_path == null || contains(["include", "exclude"], local.resolved_extra_mount_backup_policy)
    error_message = "Stack '${local.stack_name}' must set extra_mount.backup_policy to 'include' or 'exclude' when an extra mount is declared."
  }
}

check "extra_mount_operational_contract_is_supported" {
  assert {
    condition = local.extra_mount_declared == null || (
      contains(["provider", "operational"], coalesce(local.extra_mount_declared_resize_control_plane, "provider")) &&
      coalesce(local.extra_mount_declared_mutation_policy, "grow-only") == "grow-only" &&
      (
        coalesce(local.extra_mount_declared_resize_control_plane, "provider") != "operational" ||
        local.resolved_extra_mount_backend_type == "zfs"
      )
    )
    error_message = "Stack '${local.stack_name}' may declare extra_mount.resize_control_plane='operational' only for grow-only extra mounts resolved to a zfs-backed extra-mount storage profile."
  }
}

check "template_backend_supports_required_content" {
  assert {
    condition = contains(
      try(local.storage_backend_catalog[local.resolved_template_storage].content_types, []),
      coalesce(try(local.resolved_template_profile_mapping.required_content_type, null), "vztmpl")
    )
    error_message = "Resolved template backend '${local.resolved_template_storage}' does not advertise vztmpl support for stack '${local.stack_name}'."
  }
}

check "template_name_allowed_by_profile" {
  assert {
    condition     = length(try(local.resolved_template_profile_mapping.allowed_templates, [])) == 0 || contains(local.resolved_template_profile_mapping.allowed_templates, local.resolved_template_name)
    error_message = "Template '${local.resolved_template_name}' is not allowed by template profile '${local.resolved_template_profile}' for stack '${local.stack_name}'."
  }
}

# ---------------------------------------------------------------------------
# Proxmox SDN vars (only if network intent selects an SDN VNet attachment)
# Ensures the attachment exists on the selected target environment before the
# LXC is created, while keeping destroy-time SDN teardown on the default-safe
# environment unless explicitly widened later.
# ---------------------------------------------------------------------------
resource "local_file" "network_sdn_vars" {
  count = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" ? 1 : 0

  filename = "${local.stack_dir}/network-sdn-vars.yml"
  content = yamlencode({
    network_sdn_enable            = true
    network_sdn_target            = local.effective_target_node
    network_sdn_pve_host          = local.effective_pve_host
    network_sdn_expected_target   = local.effective_target_node
    network_sdn_expected_pve_host = local.effective_pve_host
    network_sdn_allow_destroy     = local.effective_target_node == "pve-test"
    network_sdn_vmid              = try(local.stack.vmid, null)
    network_sdn_zone              = try(local.resolved_sdn_attachment.zone, null)
    network_sdn_zone_type         = try(local.resolved_sdn_attachment.zone_type, null)
    network_sdn_bridge            = try(local.resolved_sdn_attachment.bridge, null)
    network_sdn_nodes             = try(local.resolved_sdn_attachment.nodes, [])
    network_sdn_vnet              = try(local.resolved_sdn_attachment.vnet, null)
    network_sdn_vlan_tag          = try(local.resolved_sdn_attachment.vlan_tag, null)
    network_sdn_vnet_alias        = try(local.resolved_sdn_attachment.alias, try(local.resolved_zone_attachment.description, local.resolved_sdn_attachment.vnet))
    network_sdn_subnet            = local.resolved_sdn_subnet
    network_sdn_gateway           = local.resolved_sdn_gateway
    network_sdn_snat              = local.resolved_sdn_snat
    network_sdn_ssh_key           = pathexpand(var.ssh_private_key_path)
  })
}

resource "null_resource" "configure_network_sdn_attachment" {
  count = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" ? 1 : 0

  triggers = {
    ansible_dir        = local.ansible_dir
    ansible_cfg        = local.ansible_cfg
    ansible_roles_path = local.ansible_roles_path
    sdn_vars           = local_file.network_sdn_vars[0].content
    sdn_vars_file      = local_file.network_sdn_vars[0].filename
    vmid               = tostring(try(local.stack.vmid, ""))
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
      ANSIBLE_CONFIG               = lookup(self.triggers, "ansible_cfg", "./ansible.cfg")
      ANSIBLE_ROLES_PATH           = lookup(self.triggers, "ansible_roles_path", "./roles")
      ANSIBLE_LOCAL_TEMP           = "/tmp/.ansible/tmp"
      ANSIBLE_SSH_CONTROL_PATH_DIR = "/tmp/.ansible/cp"
    }
  }

  provisioner "local-exec" {
    when        = destroy
    working_dir = self.triggers.ansible_dir
    command     = <<-EOT
      tmp_vars_file="$(mktemp)"
      trap 'rm -f "$tmp_vars_file"' EXIT
      cat >"$tmp_vars_file" <<'EOF'
${self.triggers.sdn_vars}
EOF
      if [ "$${NETWORK_SDN_ALLOW_DESTROY_OVERRIDE:-}" = "true" ]; then
        printf '%s\n' '"network_sdn_allow_destroy": true' >>"$tmp_vars_file"
      fi
      if [ -n "$${NETWORK_SDN_EXPECTED_TARGET:-}" ]; then
        printf '%s\n' '"network_sdn_expected_target": '"'"'"$${NETWORK_SDN_EXPECTED_TARGET}"'"'"'' >>"$tmp_vars_file"
      fi
      if [ -n "$${NETWORK_SDN_EXPECTED_PVE_HOST:-}" ]; then
        printf '%s\n' '"network_sdn_expected_pve_host": '"'"'"$${NETWORK_SDN_EXPECTED_PVE_HOST}"'"'"'' >>"$tmp_vars_file"
      fi
      ansible-playbook \
        -i localhost, \
        playbooks/destroy-network-sdn-vnet.yml \
        -e "@$tmp_vars_file"
    EOT

    environment = {
      ANSIBLE_HOST_KEY_CHECKING    = "False"
      ANSIBLE_CONFIG               = lookup(self.triggers, "ansible_cfg", "./ansible.cfg")
      ANSIBLE_ROLES_PATH           = lookup(self.triggers, "ansible_roles_path", "./roles")
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

  cores                       = try(local.stack.cores, 2)
  memory                      = try(local.stack.memory, 2048)
  swap                        = try(local.stack.swap, 512)
  rootfs_size                 = try(local.stack.rootfs_size, 8)
  rootfs_storage              = local.resolved_rootfs_storage
  docker_storage              = local.resolved_docker_storage
  docker_storage_size         = local.resolved_docker_storage_size
  docker_mount_backup_enabled = local.resolved_docker_mount_backup_enabled

  ostemplate       = local.resolved_ostemplate
  ssh_public_keys  = file(pathexpand(var.ssh_public_key_path))
  tags             = try(local.stack.tags, [local.stack_name])
  network_bridge   = local.effective_network_bridge
  network_firewall = local.effective_firewall == true
  dns_servers      = local.effective_dns_server != null ? [local.effective_dns_server] : null

  extra_mount_path           = local.resolved_extra_mount_path
  extra_mount_size           = local.resolved_extra_mount_size
  extra_mount_storage        = local.resolved_extra_mount_storage
  extra_mount_backup_enabled = local.resolved_extra_mount_backup_enabled

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
    registry_host       = try(local.stack.registry_host, var.registry_host)
    apt_cacher_host     = try(local.stack.apt_cacher_host, var.apt_cacher_host)
    dns_server          = local.effective_dns_server
    network_zone        = local.stack_network_zone != null ? local.stack_network_zone : ""
    contract_dns_server = local.effective_dns_server != null ? local.effective_dns_server : ""
    app_stack_name      = coalesce(var.stack_app_name, try(local.stack.app_stack_name, null), local.stack_name)
    vmid                = module.lxc.container_id
    pve_host            = local.effective_pve_host
    ssh_access_mode     = local.effective_network_access_path
    use_proxyjump       = local.use_proxyjump
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
      ANSIBLE_CONFIG               = local.ansible_cfg
      ANSIBLE_ROLES_PATH           = local.ansible_roles_path
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
      ANSIBLE_CONFIG               = local.ansible_cfg
      ANSIBLE_ROLES_PATH           = local.ansible_roles_path
      ANSIBLE_LOCAL_TEMP           = "/tmp/.ansible/tmp"
      ANSIBLE_SSH_CONTROL_PATH_DIR = "/tmp/.ansible/cp"
    }
  }

  depends_on = [
    local_file.ansible_inventory,
    local_file.network_firewall_vars,
    null_resource.configure_keyctl,
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
      ANSIBLE_CONFIG            = local.ansible_cfg
      ANSIBLE_ROLES_PATH        = local.ansible_roles_path
    }
  }

  depends_on = [
    local_file.network_vnet_firewall_vars,
    null_resource.configure_keyctl,
  ]
}

# ---------------------------------------------------------------------------
# Legacy Portainer cleanup resource kept only for state retirement.
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

  depends_on = [module.lxc]
}
