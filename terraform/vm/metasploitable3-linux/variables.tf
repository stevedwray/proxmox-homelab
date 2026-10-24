variable "proxmox_api_url" {
  description = "Proxmox API URL (e.g., https://pve-test.gibbsgreatly.xyz:8006/api2/json)"
  type        = string
}

variable "pm_api_token_id" {
  description = "Proxmox API token ID (e.g., automation@pve!terraform)"
  type        = string
}

variable "pm_api_token_secret" {
  description = "Proxmox API token secret"
  type        = string
  sensitive   = true
}

variable "pm_tls_insecure" {
  description = "Skip TLS verification for self-signed certs"
  type        = bool
  default     = true
}
