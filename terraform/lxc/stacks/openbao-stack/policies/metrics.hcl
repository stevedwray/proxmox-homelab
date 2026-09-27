# Dashboard inventory exporter (AppRole "metrics", credentials only on the
# OpenBao LXC). KV v2 metadata only: entry names, version numbers and
# timestamps. Secret values are served solely from kv/data/*, which this
# policy does not grant, so every read of a value is denied (403).
path "kv/metadata/*" {
  capabilities = ["list", "read"]
}
