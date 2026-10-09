# MCP Stack

Status: **proposed — no MCP server is installed or trusted for infrastructure
control yet.**

**Status refresh, 2026-09-28:** the "proposed" status applies only to the
*infrastructure-control* tier (Proxmox/MikroTik discovery and control),
which is still unbuilt. The **external-utility tier is live**:
`mcp-utility-stack` (`192.168.50.10`, `ai_seg`) runs `cve-mcp-server`,
which answered an MCP `initialize` at `http://192.168.50.10:8000/mcp`
(`serverInfo.name: cve-mcp`, `1.30.0`) on 2026-09-28, plus `docs-rag-mcp`
(port `8001` listening). The CT is stopped on `pve` because it moved to
`pve-tiny` (`docs/ai-stacks-pve-tiny/`).

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
