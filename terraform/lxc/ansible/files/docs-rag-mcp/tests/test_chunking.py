"""Chunk-size bounds for docs_rag_mcp.chunking.

The llama.cpp embeddings server rejects any input over 2048 tokens, so
every chunk must stay within MAX_CHUNK_CHARS -- including sections whose
single paragraph (a long code block or table) exceeds it on its own.
"""
from __future__ import annotations

import unittest

from docs_rag_mcp.chunking import MAX_CHUNK_CHARS, chunk_markdown


class ChunkSizeTest(unittest.TestCase):
    def assert_bounded(self, chunks):
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), MAX_CHUNK_CHARS)

    def test_cap_fits_embeddings_limit_at_observed_density(self):
        # 2677 tokens were observed for a 6000-char chunk (~2.2 chars/token);
        # the cap must stay under 2048 tokens at that density.
        self.assertLess(MAX_CHUNK_CHARS / 2.2, 2048)

    def test_many_paragraphs_are_split(self):
        body = "\n\n".join("para %d " % i + "x" * 500 for i in range(30))
        chunks = chunk_markdown("# Title\n\n" + body, "doc.md")
        self.assert_bounded(chunks)
        self.assertGreater(len(chunks), 1)

    def test_single_oversized_paragraph_is_hard_split_by_lines(self):
        block = "\n".join("key_%d: value-%s" % (i, "y" * 60) for i in range(200))
        chunks = chunk_markdown("# Config\n\n```yaml\n" + block + "\n```", "doc.md")
        self.assert_bounded(chunks)
        joined = "".join(c.text for c in chunks)
        self.assertIn("key_0:", joined)
        self.assertIn("key_199:", joined)

    def test_single_oversized_line_is_split_by_chars(self):
        chunks = chunk_markdown("# Blob\n\n" + "z" * (MAX_CHUNK_CHARS * 3 + 7), "doc.md")
        self.assert_bounded(chunks)
        self.assertEqual(sum(len(c.text) for c in chunks), MAX_CHUNK_CHARS * 3 + 7)

    def test_heading_breadcrumb_kept_on_every_sub_chunk(self):
        chunks = chunk_markdown("# A\n\n## B\n\n" + "w" * (MAX_CHUNK_CHARS * 2), "doc.md")
        self.assertTrue(all(c.heading_path == "doc.md > A > B" for c in chunks))


if __name__ == "__main__":
    unittest.main()
