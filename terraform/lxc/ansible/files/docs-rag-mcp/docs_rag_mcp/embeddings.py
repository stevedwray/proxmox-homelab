"""Embedding client -- nomic-embed-text via framework's existing Ollama.

Reuses the exact pattern PentAGI already runs in production (see
docs/pentagi-stack/README.md, upstream-control.md): same model, same
endpoint, no new egress rule (ai_seg -> framework:11434 already exists for
ai-services-stack's own Ollama use).
"""
from __future__ import annotations

import os

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://framework.gibbsgreatly.xyz:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 768


class EmbeddingError(RuntimeError):
    pass


async def embed(client: httpx.AsyncClient, text: str) -> list[float]:
    resp = await client.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": text},
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    vectors = data.get("embeddings")
    if not vectors or len(vectors[0]) != EMBED_DIM:
        raise EmbeddingError(
            f"unexpected embedding response shape from {OLLAMA_URL}: {data!r}"
        )
    return vectors[0]


async def embed_many(
    client: httpx.AsyncClient, texts: list[str], batch_size: int = 16
) -> list[list[float]]:
    """Embed a list of texts, batching requests. Ollama's /api/embed
    accepts a list under "input", but batching conservatively here keeps
    any single request well inside Phase 1's validated reliable range
    (see docs/coding-stack/plan.md) rather than assuming an unbounded
    batch is safe."""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = await client.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": batch},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        vectors = data.get("embeddings")
        if not vectors or len(vectors) != len(batch):
            raise EmbeddingError(
                f"unexpected batch embedding response shape from {OLLAMA_URL}: {data!r}"
            )
        out.extend(vectors)
    return out
