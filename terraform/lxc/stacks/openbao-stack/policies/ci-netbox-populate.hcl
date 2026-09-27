# GitHub Actions netbox-populate workflow (auth/jwt-github). Exactly the
# entries in the manifest's ci-netbox-populate profile, read-only.
path "kv/data/services/mikrotik" {
  capabilities = ["read"]
}

path "kv/data/services/netbox" {
  capabilities = ["read"]
}

path "kv/data/services/portainer" {
  capabilities = ["read"]
}

path "kv/data/hosts/pve" {
  capabilities = ["read"]
}
