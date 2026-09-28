# Read-only deploy access to service and shared entries (every deploy-* AppRole).
# No create/update/patch/delete: a deploy can never change a secret value.
path "kv/data/services/*" {
  capabilities = ["read"]
}

path "kv/data/shared/*" {
  capabilities = ["read"]
}
