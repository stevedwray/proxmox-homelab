"""Incremental reindex over the corpus Ansible copies into this container
at deploy time (see docs/coding-stack/plan.md Phase 2 "Reindex mechanism"
-- corrected to an Ansible-copied corpus, not an in-container git pull).

Runs once at container startup (main.py calls this before serving), not
on an internal schedule -- the corpus is static between deploys, so a
periodic in-container rescan would find nothing new. Refreshing the index
is a normal `scripts/provision.sh --stack mcp-utility-stack` re-run.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
from pathlib import Path

import asyncpg
import httpx

from . import db
from .chunking import chunk_markdown
from .embeddings import embed_many

logger = logging.getLogger("docs_rag_mcp.reindex")

CORPUS_DIR = Path(os.environ.get("CORPUS_DIR", "/corpus"))

_STACK_CONTRACT_RE = re.compile(
    r"^terraform/lxc/stacks/([^/]+)/STACK_CONTRACT\.md$"
)


def _stack_name_for(rel_path: str) -> str | None:
    m = _STACK_CONTRACT_RE.match(rel_path)
    return m.group(1) if m else None


def _iter_corpus_files() -> list[Path]:
    if not CORPUS_DIR.is_dir():
        logger.warning("corpus dir %s does not exist -- nothing to index", CORPUS_DIR)
        return []
    return sorted(CORPUS_DIR.rglob("*.md"))


async def reindex_all(pool: asyncpg.Pool) -> dict:
    """Returns a small summary dict for logging/diagnostics."""
    files = _iter_corpus_files()
    seen_paths: set[str] = set()
    changed = 0
    unchanged = 0
    failed: list[str] = []

    async with httpx.AsyncClient() as client:
        for path in files:
            rel_path = str(path.relative_to(CORPUS_DIR))
            seen_paths.add(rel_path)

            file_hash = db.sha256_file(path)
            existing_hash = await db.get_file_hash(pool, rel_path)
            if existing_hash == file_hash:
                unchanged += 1
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                stack_name = _stack_name_for(rel_path)
                doc_title = rel_path
                chunks = chunk_markdown(text, doc_title)
                if not chunks:
                    logger.info("no chunks produced for %s (empty file?)", rel_path)
                    continue

                embeddings = await embed_many(client, [c.text for c in chunks])
                mtime = dt.datetime.fromtimestamp(
                    path.stat().st_mtime, tz=dt.timezone.utc
                )

                chunk_rows = [
                    {
                        "heading_path": c.heading_path,
                        "chunk_text": c.text,
                        "chunk_tokens": c.token_estimate,
                        "content_hash": db.sha256_text(c.text),
                        "embedding": emb,
                    }
                    for c, emb in zip(chunks, embeddings)
                ]

                await db.replace_file_chunks(
                    pool, rel_path, stack_name, file_hash, mtime, chunk_rows
                )
                changed += 1
                logger.info(
                    "indexed %s (%d chunks, stack=%s)",
                    rel_path,
                    len(chunk_rows),
                    stack_name,
                )
            except Exception:  # noqa: BLE001 -- one bad file must not abort the whole reindex
                logger.exception("failed to index %s", rel_path)
                failed.append(rel_path)

    # Remove entries for files no longer present in this corpus snapshot
    # (deleted or renamed since the last deploy).
    known = await db.known_files(pool)
    removed = 0
    for stale_path in known - seen_paths:
        await db.delete_file(pool, stale_path)
        removed += 1
        logger.info("removed stale index entry for %s", stale_path)

    if changed:
        await db.rebuild_ivfflat_index(pool)

    summary = {
        "total_files": len(files),
        "changed": changed,
        "unchanged": unchanged,
        "removed": removed,
        "failed": failed,
    }
    logger.info("reindex summary: %s", summary)
    return summary
