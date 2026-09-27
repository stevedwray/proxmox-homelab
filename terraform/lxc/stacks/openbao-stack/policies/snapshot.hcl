# Raft snapshot download only (AppRole "snapshot", credentials on the OpenBao LXC).
path "sys/storage/raft/snapshot" {
  capabilities = ["read", "sudo"]
}
