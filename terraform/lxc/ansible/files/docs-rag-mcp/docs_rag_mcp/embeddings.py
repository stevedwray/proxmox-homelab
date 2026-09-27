"""Embedding client -- nomic-embed-text via framework's llama.cpp
embeddings server (Nathanw llama.cpp fork, nathanw-llamacpp-embed.service,
OpenAI-compatible /v1/embeddings on :8085).

Replaced framework's Ollama (/api/embed) in 2026-09 when Ollama was removed
from framework -- see docs/framework-ip-and-port/plan.md. Same model family
(nomic-embed-text v1.5, 768 dims), but vectors from the two runtimes are not
guaranteed identical, so switching runtimes requires a full corpus re-embed
(the plan's operator steps truncate the tables before the first reindex).
Reached by name, never by IP; ai_seg -> framework:8085 is allowed by
ansible/00-initial-setup/mikrotik-firewall-framework-fqdn.yml.
"""
from __future__ import annotations

import os

import httpx

EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "http://framework.gibbsgreatly.xyz:8085")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 768


class EmbeddingError(RuntimeError):
    pass


async def _embed_batch(
    client: httpx.AsyncClient, texts: list[str], timeout: float
) -> list[list[float]]:
    resp = await client.post(
        f"{EMBED_BASE_URL}/v1/embeddings",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    items = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
    vectors = [item.get("embedding") for item in items]
    if len(vectors) != len(texts) or any(
        not v or len(v) != EMBED_DIM for v in vectors
    ):
        raise EmbeddingError(
            f"unexpected embedding response shape from {EMBED_BASE_URL}: {data!r}"
        )
    return vectors


async def embed(client: httpx.AsyncClient, text: str) -> list[float]:
    return (await _embed_batch(client, [text], timeout=60.0))[0]


async def embed_many(
    client: httpx.AsyncClient, texts: list[str], batch_size: int = 16
) -> list[list[float]]:
    """Embed a list of texts, batching requests. The embeddings server runs
    a single 2048-token slot, so a batch is processed sequentially on the
    server side; batching here only bounds request size and timeout."""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        out.extend(await _embed_batch(client, texts[i : i + batch_size], timeout=120.0))
    return out
