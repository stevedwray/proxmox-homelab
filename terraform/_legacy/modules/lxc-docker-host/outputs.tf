# terraform/modules/lxc-docker-host/outputs.tf

output "ip_address" {
  description = "IP address of the created LXC container"
  value       = proxmox_lxc.docker_host.network[0].ip
}

output "hostname" {
  description = "Hostname of the created LXC container"
  value       = proxmox_lxc.docker_host.hostname
}

output "container_id" {
  description = "Proxmox container ID"
  value       = proxmox_lxc.docker_host.vmid
}

output "target_node" {
  description = "Proxmox node where the container was created"
  value       = proxmox_lxc.docker_host.target_node
}
