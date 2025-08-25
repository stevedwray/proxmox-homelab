output "container_info" {
  description = "Information about created containers"
  value = {
    for container in proxmox_lxc.test_containers :
    container.hostname => {
      id       = container.vmid
      hostname = container.hostname
      node     = container.target_node
      memory   = container.memory
      cores    = container.cores
      tags     = container.tags
    }
  }
}
