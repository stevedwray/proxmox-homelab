# Break-glass (design doc 19): lets the "breakglass" AppRole drive root-token
# generation and nothing else. Minting a root token still needs the recovery
# key from the bootstrap kit; this policy alone cannot read or write any
# secret. Needed because OpenBao >= 2.5.3 disables the unauthenticated
# sys/generate-root endpoints (disable_unauthed_generate_root_endpoints).
path "sys/generate-root-token/attempt" {
  capabilities = ["create", "read", "update", "delete", "sudo"]
}

path "sys/generate-root-token/update" {
  capabilities = ["create", "update", "sudo"]
}
