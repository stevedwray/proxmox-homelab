-- docs-rag-mcp schema. Applied idempotently (IF NOT EXISTS) on every
-- container startup by db.ensure_schema() -- see docs/coding-stack/plan.md
-- Phase 2 "Storage schema" for the design this implements.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS doc_chunks (
    id            SERIAL PRIMARY KEY,
    file_path     TEXT NOT NULL,
    stack_name    TEXT,
    heading_path  TEXT NOT NULL,
    chunk_text    TEXT NOT NULL,
    chunk_tokens  INT NOT NULL,
    content_hash  TEXT NOT NULL,
    file_mtime    TIMESTAMPTZ NOT NULL,
    embedding     VECTOR(768) NOT NULL,
    indexed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ivfflat needs at least some rows to build a meaningful index; created
-- with a small `lists` value appropriate for this corpus's size (a few
-- hundred to low thousands of chunks, not millions). Rebuilt by reindex.py
-- after a full corpus load so the planner has real statistics.
CREATE INDEX IF NOT EXISTS doc_chunks_embedding_idx
    ON doc_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS doc_chunks_file_path_idx ON doc_chunks (file_path);
CREATE INDEX IF NOT EXISTS doc_chunks_stack_name_idx ON doc_chunks (stack_name);

CREATE TABLE IF NOT EXISTS file_index (
    file_path     TEXT PRIMARY KEY,
    content_hash  TEXT NOT NULL,
    last_indexed  TIMESTAMPTZ NOT NULL
);
