# Human administrators: Authentik group homelab-admins via OIDC (auth/oidc,
# role homelab-admin), and break-glass tokens from generate-root.
# Never attached to any machine identity.
path "*" {
  capabilities = ["create", "read", "update", "patch", "delete", "list", "sudo"]
}
