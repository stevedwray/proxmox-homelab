output "stacks" {
  description = "Summary of all deployed LXC stacks"
  value = {
    for k, v in module.lxc : k => {
      hostname     = v.hostname
      ip_address   = v.ip_address
      container_id = v.container_id
      target_node  = v.target_node
    }
  }
}
