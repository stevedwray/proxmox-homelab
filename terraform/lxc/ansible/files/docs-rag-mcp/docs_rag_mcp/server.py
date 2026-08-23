"""docs-rag-mcp: one MCP tool (plus a cheap discovery helper) exposing
semantic search over this repo's documentation. See
docs/coding-stack/plan.md Phase 2 "Tool surface" for the design this
implements -- deliberately narrow: one real search tool with a filter
param, not a separate tool per use case.

No authentication -- access control is network-level only (the same
MikroTik-rule posture already used for cve-mcp-server in this same LXC).
This tool holds no credentials and only serves the operator's own
already-public-within-the-LAN repo docs, so that posture carries over
unchanged.

Startup (schema + full reindex) happens inside `lifespan`, before the
server accepts any connections -- not lazily on first tool call. This
runs in the same event loop `MCPServer.run()` drives, so the DB pool
created here is never handed across an event-loop boundary.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import asyncpg
import httpx
from mcp.server.mcpserver import Context, MCPServer

from . import db
from .embeddings import embed
from .reindex import reindex_all

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("docs_rag_mcp.server")


@dataclass
class AppContext:
    pool: asyncpg.Pool
    http_client: httpx.AsyncClient


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    pool = await db.get_pool()
    await db.ensure_schema(pool)

    summary = await reindex_all(pool)
    if summary["failed"]:
        logger.warning(
            "startup reindex completed with %d failed file(s): %s",
            len(summary["failed"]),
            summary["failed"],
        )

    http_client = httpx.AsyncClient()
    try:
        yield AppContext(pool=pool, http_client=http_client)
    finally:
        await http_client.aclose()
        await pool.close()


mcp = MCPServer("docs-rag-mcp", lifespan=lifespan)


@mcp.tool()
async def search_docs(
    ctx: Context, query: str, k: int = 8, stack: str | None = None
) -> list[dict]:
    """Semantic search over this repo's documentation (docs/**/*.md,
    every STACK_CONTRACT.md, CLAUDE.md).

    Use this instead of guessing grep terms when you need conceptually
    related past decisions, gotchas, or cross-stack context -- e.g. "how
    does this project handle SDN firewall rules for a new zone" or "has
    something like this failure happened before". For an exact known
    filename or literal string, plain grep is still faster and more
    precise than this tool.

    Args:
        query: natural-language question or description of what you need.
        k: max number of chunks to return (default 8).
        stack: optional exact stack name (see list_stacks) to narrow the
            search to one stack's STACK_CONTRACT.md and related docs.

    Returns a list of {file_path, heading_path, stack_name, chunk_text,
    score, indexed_at} ordered by relevance. `indexed_at` tells you how
    fresh a hit is -- it can predate a very recent edit that hasn't been
    (re)provisioned into this index yet.
    """
    app = ctx.request_context.lifespan_context
    query_embedding = await embed(app.http_client, query)
    results = await db.search(app.pool, query_embedding, k=k, stack=stack)
    for r in results:
        r["indexed_at"] = r["indexed_at"].isoformat()
        r["score"] = round(float(r["score"]), 4)
    return results


@mcp.tool()
async def list_stacks(ctx: Context) -> list[str]:
    """List every stack name currently indexed (i.e. every stack with a
    STACK_CONTRACT.md in this repo) -- use this to discover valid values
    for search_docs's `stack` filter rather than guessing spellings."""
    app = ctx.request_context.lifespan_context
    return await db.list_stacks(app.pool)
