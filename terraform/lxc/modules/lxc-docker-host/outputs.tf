output "ip_address" {
  description = "IP address of the created LXC container"
  value       = proxmox_virtual_environment_container.docker_host.initialization[0].ip_config[0].ipv4[0].address
}

output "hostname" {
  description = "Hostname of the created LXC container"
  value       = proxmox_virtual_environment_container.docker_host.initialization[0].hostname
}

output "container_id" {
  description = "Proxmox container ID"
  value       = proxmox_virtual_environment_container.docker_host.vm_id
}

output "target_node" {
  description = "Proxmox node where the container was created"
  value       = proxmox_virtual_environment_container.docker_host.node_name
}
