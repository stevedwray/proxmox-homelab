# File: management-stack/outputs.tf

output "management_stack_ip" {
  description = "IP address of the management stack container"
  value       = "192.168.1.70"
}

output "portainer_url" {
  description = "Portainer Server URL"
  value       = "http://192.168.1.70:9000"
}

output "portainer_https_url" {
  description = "Portainer Server HTTPS URL"
  value       = "https://192.168.1.70:9443"
}