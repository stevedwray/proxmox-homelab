"""Unit tests for docs_rag_mcp.embeddings against a mocked llama.cpp
/v1/embeddings endpoint (no network). Run from the docs-rag-mcp directory:
    python3 -m unittest discover -s tests -p 'test_*.py'
"""
from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from docs_rag_mcp import embeddings


def _handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v1/embeddings"
    body = json.loads(request.content)
    assert body["model"] == embeddings.EMBED_MODEL
    n = len(body["input"])
    # Deliberately out of order: the client must sort by "index".
    data = [{"index": i, "embedding": [float(i)] * embeddings.EMBED_DIM} for i in reversed(range(n))]
    return httpx.Response(200, json={"data": data})


def _bad_dim_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * 3}]})


class EmbeddingsTest(unittest.TestCase):
    def _run(self, handler, coro_factory):
        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await coro_factory(client)
        return asyncio.run(go())

    def test_embed_single(self):
        vec = self._run(_handler, lambda c: embeddings.embed(c, "query"))
        self.assertEqual(len(vec), embeddings.EMBED_DIM)

    def test_embed_many_preserves_order_across_batches(self):
        vecs = self._run(_handler, lambda c: embeddings.embed_many(c, [str(i) for i in range(20)]))
        self.assertEqual(len(vecs), 20)
        # batch_size 16: items 16..19 are indexes 0..3 of the second batch
        self.assertEqual([v[0] for v in vecs], [float(i) for i in range(16)] + [0.0, 1.0, 2.0, 3.0])

    def test_wrong_dimension_raises(self):
        with self.assertRaises(embeddings.EmbeddingError):
            self._run(_bad_dim_handler, lambda c: embeddings.embed(c, "query"))


if __name__ == "__main__":
    unittest.main()
