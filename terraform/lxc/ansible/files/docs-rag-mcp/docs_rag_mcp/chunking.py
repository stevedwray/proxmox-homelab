"""Markdown heading-based chunking.

By heading/section, not fixed-size -- see docs/coding-stack/plan.md
Phase 2 "Chunking strategy". Every STACK_CONTRACT.md in this repo shares
the same Purpose/Network/Inputs/Provides/Dependencies/Persistent State/
"What Must Not Be Edited Casually"/Playbook shape, and losing that
structure by chunking blindly would make retrieval worse than grep, not
better.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Rough chars-per-token estimate for English/markdown prose -- good enough
# for chunk sizing, not a real tokenizer. Calibrated loosely against this
# project's own observed prompt_eval_count-vs-byte-count ratios during
# Phase 1 validation (see docs/coding-stack/plan.md).
_CHARS_PER_TOKEN = 4
MAX_CHUNK_TOKENS = 1500
MAX_CHUNK_CHARS = MAX_CHUNK_TOKENS * _CHARS_PER_TOKEN

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass
class Chunk:
    heading_path: str
    text: str

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.text) // _CHARS_PER_TOKEN)


def _split_oversized(heading_path: str, body: str) -> list[Chunk]:
    """Sub-chunk a too-large section by paragraph, re-prefixing the
    heading breadcrumb onto every sub-chunk so it's never returned
    without its structural context."""
    if len(body) <= MAX_CHUNK_CHARS:
        return [Chunk(heading_path, body)]

    paragraphs = re.split(r"\n\s*\n", body)
    chunks: list[Chunk] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        para_len = len(para) + 2
        if current and current_len + para_len > MAX_CHUNK_CHARS:
            chunks.append(Chunk(heading_path, "\n\n".join(current)))
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len
    if current:
        chunks.append(Chunk(heading_path, "\n\n".join(current)))
    return chunks


def chunk_markdown(text: str, doc_title: str) -> list[Chunk]:
    """Split one markdown file's text into heading-scoped chunks.

    `doc_title` seeds the top of every breadcrumb (e.g. the file's
    relative path or, for a STACK_CONTRACT.md, "<stack-name>") so a chunk
    is never ambiguous about which document it came from once returned on
    its own.
    """
    lines = text.splitlines()

    # stack of (level, title) currently open
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = []  # (heading_path, body lines)
    current_body: list[str] = []

    def breadcrumb() -> str:
        parts = [doc_title] + [t for _, t in stack]
        return " > ".join(parts)

    # Content before the first heading, if any, is its own chunk under
    # just the doc title.
    sections.append((doc_title, current_body))

    for line in lines:
        m = _HEADING_RE.match(line)
        if not m:
            current_body.append(line)
            continue

        level = len(m.group(1))
        title = m.group(2)

        # close any open headings at this level or deeper
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))

        current_body = []
        sections.append((breadcrumb(), current_body))

    chunks: list[Chunk] = []
    for heading_path, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        chunks.extend(_split_oversized(heading_path, body))

    return chunks
