"""Entrypoint. Schema-ensure and the full startup reindex happen inside
server.py's `lifespan`, before the server accepts connections -- nothing
extra to orchestrate here.
"""
from __future__ import annotations

import logging
import os

from mcp.server.transport_security import TransportSecuritySettings

from .server import mcp

logger = logging.getLogger("docs_rag_mcp.main")


def _allowed_hosts() -> list[str]:
    # Same requirement as this LXC's existing cve-mcp-server service: both
    # the direct IP:port path (lan/pentest_seg -> :8001 directly, if ever
    # opened) and the Traefik hostname path need to be allowed, or every
    # request routed through a hostname gets rejected as an invalid Host
    # header (confirmed live for cve-mcp-server 2026-08-01, same fix
    # needed here). Comma-separated env var, no default -- must be set
    # explicitly rather than silently falling back to "allow everything".
    raw = os.environ.get("DOCS_RAG_ALLOWED_HOSTS")
    if not raw:
        raise RuntimeError("DOCS_RAG_ALLOWED_HOSTS env var is required")
    return [h.strip() for h in raw.split(",") if h.strip()]


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")  # nosec B104 — container-internal MCP listener; exposure is controlled by Docker port mapping / Traefik, not this bind address
    port = int(os.environ.get("PORT", "8001"))
    transport_security = TransportSecuritySettings(allowed_hosts=_allowed_hosts())
    logger.info("starting docs-rag-mcp on %s:%s", host, port)
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        transport_security=transport_security,
    )


if __name__ == "__main__":
    main()
