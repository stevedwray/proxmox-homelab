# docs-rag-mcp

MCP server exposing semantic search (`search_docs`, `list_stacks`) over
this repo's documentation, backed by `pgvector` + `nomic-embed-text` via
the existing Ollama endpoint on `framework.gibbsgreatly.xyz`.

Design: `docs/coding-stack/plan.md` in the main repo. Deployed as an
additional Compose service inside the existing `mcp-utility-stack` LXC —
see `terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml` and
`terraform/lxc/stacks/mcp-utility-stack/STACK_CONTRACT.md`.

This directory's source is copied into the LXC and built there by
Ansible, the same pattern already used for this LXC's `cve-mcp-server`
service — not a standalone deployable project on its own.
