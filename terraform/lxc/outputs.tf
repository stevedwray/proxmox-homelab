output "stack" {
  description = "Summary of the deployed LXC stack"
  value = {
    hostname     = module.lxc.hostname
    ip_address   = module.lxc.ip_address
    container_id = module.lxc.container_id
    target_node  = module.lxc.target_node
    pve_host     = local.effective_pve_host
    network = {
      zone            = local.stack_network_zone
      attachment_name = local.resolved_zone_attachment_name
      attachment_type = local.resolved_attachment_type
      bridge          = local.effective_network_bridge
      vlan_tag        = local.effective_vlan_tag
      firewall        = local.effective_firewall
      sdn_vnet        = local.resolved_attachment_type == "sdn_vnet" ? try(local.resolved_sdn_attachment.vnet, null) : null
      intent          = local.stack_network_zone != null ? local.effective_network_intent_path : null
    }
  }
}
