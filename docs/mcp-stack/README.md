# MCP Stack

Status: **proposed — no MCP server is installed or trusted for infrastructure
control yet.**

This workspace plans a safe Model Context Protocol (MCP) layer for local AI
and agent-assisted operations in this homelab. It turns the MCP direction in
[the agent implementation plan](../agent-design/implementation-plan.md) and
[local AI plan](../framework-ubuntu/local-ai-development.md) into a concrete
hosting, trust, and validation design.

The starting point is intentionally modest:

- local, per-agent tools for GitHub and a scoped worktree;
- read-only-first discovery of Proxmox and MikroTik state;
- existing repository scripts and production wrappers remain the only path for
  infrastructure mutations.

The target state, if the local evaluations prove useful, is a dedicated
`mcp-stack` in its own automation/control-plane segment. It is not part of
the Framework AI host, OpenWebUI/SearXNG, `mgmt_seg`, or the existing
`ai-stack` rebuild.

See [plan.md](plan.md) for the proposed architecture, evaluated servers,
security requirements, and staged delivery plan. Temporary test transcripts,
tool listings, and captures belong in the ignored `artifacts/` directory.
