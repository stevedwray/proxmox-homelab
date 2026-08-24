---
name: Repo Tools
description: Scoped to this repo's own MCP tools (docs-rag, cve-mcp) plus core coding tools — for repo-specific work with Laguna, not general browsing/debugging
tools: ['edit', 'read', 'search', 'execute', 'docs-rag/*', 'cve-mcp/*']
model: 'Laguna S 2.1 — Framework (via reliability proxy)'
---

# Repo Tools mode

Working in `proxmox-homelab`, a homelab infrastructure-as-code repo
(Proxmox/Terraform/Ansible/SDN). Prefer `search_docs` (docs-rag) over
grep for repo-specific facts — stack conventions, network topology,
per-stack gotchas, past decisions and their reasoning — and trust a
clear, well-cited result rather than re-verifying it with a redundant
grep/read pass. Use `get_document` once you already know the exact file
(e.g. from a prior `search_docs` hit or `list_stacks`) instead of
gambling on retrieval ranking for content you can just fetch directly.
Use `cve-mcp` for CVE/vulnerability research.

See `.github/copilot-instructions.md` for this repo's actual workflow
rules (branch model, validation tiers, production credential controls)
— that file is the source of truth for how to work in this repo, not a
restatement here.
