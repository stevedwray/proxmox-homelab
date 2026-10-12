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
        # Found 2026-10-02: left unset, ClientSession's read_timeout_seconds
        # is None (see agent_framework._mcp's _connect_on_owner), so a
        # stalled/dropped connection leaves the tool-call await unbounded --
        # a real 52+ minute silent hang in a live run, invisible at the TCP
        # layer by the time it was inspected (socket already gone, nothing
        # to time it out). 60s was sized when osint-mcp's only tool was
        # investigate_domain, which does complete in seconds.
        #
        # Found live 2026-10-10 (first real multi-angle run exercising the
        # new find_username_deep/Sherlock-under-concurrency path): BOTH
        # concurrent find_username calls in one run genuinely succeeded on
        # osint-mcp's own side (confirmed via its per-request logs: 65.3s
        # and 128.6s respectively) but were reported to this agent as
        # "Error: Function failed." -- the client-side 60s timeout fired
        # first every time, discarding correct results. This isn't a rare
        # edge case: Sherlock/Maigret (Phase 4/6) are serialized in-process
        # on osint-mcp's side specifically BECAUSE concurrent full scans
        # contend for the same CPU/network (2026-10-03 finding), so a
        # second or third concurrent find_username call queuing behind
        # earlier ones is the expected outcome under this agent's own
        # max_concurrent_tasks: 3, not a malfunction -- the old 60s budget
        # just never accounted for it. Raised to 240s: comfortably covers
        # a worst-case 2-3-deep Sherlock/Maigret queue while staying a
        # small, bounded fraction of the original 52-minute silent-hang
        # problem this timeout exists to catch in the first place.
        request_timeout=240,
    )
    if _OSINT_MCP_URL and _OSINT_MCP_TOKEN
    else None
)
