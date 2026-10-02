"""Pinned, deterministic line-aware token chunking for retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bm25 import Chunk

WORD_RE = re.compile(r"[^\W_]+(?:['’_-][^\W_]+)*", re.UNICODE)
DEFAULT_CHUNK_SIZE = 180
DEFAULT_OVERLAP = 30


def tokenize(text: str) -> list[str]:
    """Tokenize words and identifiers without locale-dependent behavior."""
    return [match.group(0).lower() for match in WORD_RE.finditer(text)]


@dataclass(frozen=True)
class TokenSpan:
    token: str
    start: int
    end: int
    line: int


def token_spans(text: str) -> list[TokenSpan]:
    offsets: list[TokenSpan] = []
    line = 1
    cursor = 0
    for match in WORD_RE.finditer(text):
        line += text[cursor : match.start()].count("\n")
        offsets.append(TokenSpan(match.group(0).lower(), match.start(), match.end(), line))
        cursor = match.end()
    return offsets


def chunk_text(
    text: str,
    *,
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Return token-window chunks with the pinned size and overlap."""
    _validate_window(size, overlap)
    spans = token_spans(text)
    if not spans:
        return [text] if text else []
    chunks: list[str] = []
    step = size - overlap
    for start in range(0, len(spans), step):
        selected = spans[start : start + size]
        if not selected:
            break
        chunks.append(text[selected[0].start : selected[-1].end])
        if start + size >= len(spans):
            break
    return chunks


def chunk_document(
    path: str,
    text: str,
    *,
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Create chunks with line references and compact verbatim previews."""
    # Import lazily to keep this module usable by index-build tooling.
    from .bm25 import Chunk

    _validate_window(size, overlap)
    spans = token_spans(text)
    if not spans:
        return []
    step = size - overlap
    result: list[Chunk] = []
    for start in range(0, len(spans), step):
        selected = spans[start : start + size]
        if not selected:
            break
        preview = text[selected[0].start : selected[-1].end]
        result.append(
            Chunk(
                chunk_id=f"{path}#{len(result)}",
                path=path,
                text=preview,
                tokens=tuple(span.token for span in selected),
                line_start=selected[0].line,
                line_end=selected[-1].line,
            )
        )
        if start + size >= len(spans):
            break
    return result


def _validate_window(size: int, overlap: int) -> None:
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be between zero and size - 1")


@dataclass(frozen=True)
class DeterministicChunker:
    """Configured wrapper around the pinned chunker."""

    size: int = DEFAULT_CHUNK_SIZE
    overlap: int = DEFAULT_OVERLAP

    def __post_init__(self) -> None:
        if self.size <= 0 or self.overlap < 0 or self.overlap >= self.size:
            raise ValueError("invalid chunker size or overlap")

    def chunk(self, path: str, text: str) -> list[Chunk]:
        return chunk_document(path, text, size=self.size, overlap=self.overlap)
