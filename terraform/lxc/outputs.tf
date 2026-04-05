output "stack" {
  description = "Summary of the deployed LXC stack"
  value = {
    hostname     = module.lxc.hostname
    ip_address   = module.lxc.ip_address
    container_id = module.lxc.container_id
    target_node  = module.lxc.target_node
  }
}
