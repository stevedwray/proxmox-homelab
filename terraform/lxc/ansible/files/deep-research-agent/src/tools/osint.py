import os
from agent_framework import MCPStreamableHTTPTool

# Phase 3 (docs/maltego-integration/README.md): a real MCP client, not a
# plain HTTP tool -- the first MCPTool this codebase has ever used.
# agent_framework's ChatAgent (engine/orchestrator.py's client.as_agent())
# detects MCPTool instances in a tools list and manages their connection
# lifecycle automatically (confirmed by reading agent_framework/_agents.py
# directly: it uses its own AsyncExitStack, no manual `async with` needed
# here). osint-mcp lives in a different container (mcp-utility-stack) on
# the same pve-tiny LXC host -- unreachable via stdio, which is why
# osint-mcp is a Streamable HTTP server in the first place.
#
# engine/sdk.py's SubAgentConfig.tools was widened from List[Callable] to
# List[Any] to admit this -- MCPTool has no __call__, so the old type
# rejected it outright.
_OSINT_MCP_URL = os.environ.get("OSINT_MCP_URL", "")
_OSINT_MCP_TOKEN = os.environ.get("OSINT_MCP_TOKEN", "")

# None (not a tool list entry at all) when unconfigured, rather than a
# tool that always errors -- same "degrade, don't crash" convention as
# every Tier 1/2 lookup in osint-mcp itself. app.py checks for None
# before adding it to any sub-agent's tools list.
osint_investigate = (
    MCPStreamableHTTPTool(
        name="osint_investigate",
        url=_OSINT_MCP_URL,
        description=(
            "Investigate a domain: DNS resolution, WHOIS, certificate transparency, "
            "ASN/hosting info, and threat-intel enrichment (VirusTotal, Shodan, "
            "GreyNoise, AlienVault OTX). Exposes one remote tool, investigate_domain."
        ),
        static_headers={"Authorization": f"Bearer {_OSINT_MCP_TOKEN}"},
    )
    if _OSINT_MCP_URL and _OSINT_MCP_TOKEN
    else None
)
