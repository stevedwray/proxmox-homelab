"""pgvector storage layer -- this stack's own instance, not shared with
PentAGI's (that's a different concern, its own private task memory).
See docs/coding-stack/plan.md Phase 2 "Storage schema"."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://docs_rag:docs_rag@pgvector:5432/docs_rag"
)

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def get_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=8)


async def ensure_schema(pool: asyncpg.Pool) -> None:
    # asyncpg's execute() runs a whole multi-statement script when called
    # with no bind arguments (confirmed against the installed asyncpg's
    # own docstring) -- no manual statement-splitting needed.
    sql = _SCHEMA_PATH.read_text()
    async with pool.acquire() as conn:
        await conn.execute(sql)


async def get_file_hash(pool: asyncpg.Pool, file_path: str) -> str | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT content_hash FROM file_index WHERE file_path = $1", file_path
        )
        return row["content_hash"] if row else None


async def replace_file_chunks(
    pool: asyncpg.Pool,
    file_path: str,
    stack_name: str | None,
    file_hash: str,
    file_mtime: dt.datetime,
    chunks: list[dict],
) -> None:
    """Delete this file's existing chunks and insert the freshly-embedded
    set, plus update file_index -- one transaction so a reindex run can't
    leave a file half-updated if it's interrupted midway."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM doc_chunks WHERE file_path = $1", file_path)
        for c in chunks:
            await conn.execute(
                """
                INSERT INTO doc_chunks
                    (file_path, stack_name, heading_path, chunk_text,
                     chunk_tokens, content_hash, file_mtime, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
                """,
                file_path,
                stack_name,
                c["heading_path"],
                c["chunk_text"],
                c["chunk_tokens"],
                c["content_hash"],
                file_mtime,
                str(c["embedding"]),
            )
        await conn.execute(
            """
            INSERT INTO file_index (file_path, content_hash, last_indexed)
            VALUES ($1, $2, now())
            ON CONFLICT (file_path) DO UPDATE
                SET content_hash = EXCLUDED.content_hash,
                    last_indexed = EXCLUDED.last_indexed
            """,
            file_path,
            file_hash,
        )


async def delete_file(pool: asyncpg.Pool, file_path: str) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM doc_chunks WHERE file_path = $1", file_path)
        await conn.execute("DELETE FROM file_index WHERE file_path = $1", file_path)


async def known_files(pool: asyncpg.Pool) -> set[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT file_path FROM file_index")
        return {r["file_path"] for r in rows}


async def search(
    pool: asyncpg.Pool, query_embedding: list[float], k: int, stack: str | None
) -> list[dict]:
    async with pool.acquire() as conn:
        if stack:
            rows = await conn.fetch(
                """
                SELECT file_path, heading_path, stack_name, chunk_text,
                       indexed_at,
                       1 - (embedding <=> $1::vector) AS score
                FROM doc_chunks
                WHERE stack_name = $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                str(query_embedding),
                stack,
                k,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT file_path, heading_path, stack_name, chunk_text,
                       indexed_at,
                       1 - (embedding <=> $1::vector) AS score
                FROM doc_chunks
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                str(query_embedding),
                k,
            )
        return [dict(r) for r in rows]


async def list_stacks(pool: asyncpg.Pool) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT stack_name FROM doc_chunks "
            "WHERE stack_name IS NOT NULL ORDER BY stack_name"
        )
        return [r["stack_name"] for r in rows]


async def rebuild_ivfflat_index(pool: asyncpg.Pool) -> None:
    """Re-create the ivfflat index after a full corpus load so the planner
    has real statistics to size `lists` against -- cheap at this corpus's
    scale (hundreds to low thousands of rows), and only run once per
    reindex pass, not per chunk."""
    async with pool.acquire() as conn:
        await conn.execute("DROP INDEX IF EXISTS doc_chunks_embedding_idx")
        await conn.execute(
            """
            CREATE INDEX doc_chunks_embedding_idx
                ON doc_chunks USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """
        )
