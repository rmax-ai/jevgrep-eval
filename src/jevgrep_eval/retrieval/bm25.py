"""Deterministic in-repository BM25 retrieval.

This is a mechanics driver for the benchmark, not a production retrieval
policy.  Index artifacts are written outside agent workspaces.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from ..models import RetrievalHit, RetrievalResult
from ..util import canonical_json, digest, digest_bytes, normalize_path
from .chunking import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, chunk_document, tokenize

DEFAULT_K1 = 1.2
DEFAULT_B = 0.75
DEFAULT_EPSILON = 0.25


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    path: str
    text: str
    tokens: tuple[str, ...]
    line_start: int = 1
    line_end: int = 1


def corpus_fingerprint(root: Path, *, eligible_paths: Iterable[str] | None = None) -> str:
    """Hash the eligible file bytes and canonical relative paths."""
    allowed = {normalize_path(path) for path in eligible_paths} if eligible_paths else None
    rows: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(root).parts:
            continue
        relative = normalize_path(path.relative_to(root).as_posix())
        if allowed is not None and relative not in allowed:
            continue
        rows.append({"path": relative, "sha256": digest_bytes(path.read_bytes())})
    return digest(rows, component="corpus-fingerprint")


class BM25Index:
    def __init__(
        self,
        chunks: list[Chunk],
        *,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
        epsilon: float = DEFAULT_EPSILON,
        fingerprint: str = "",
    ) -> None:
        if k1 <= 0 or b < 0 or b > 1 or epsilon < 0:
            raise ValueError("invalid BM25 parameters")
        self.chunks = list(chunks)
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon
        self.fingerprint = fingerprint
        self._postings: dict[str, dict[int, int]] = {}
        for index, chunk in enumerate(self.chunks):
            for token, count in Counter(chunk.tokens).items():
                self._postings.setdefault(token, {})[index] = count
        self._average_length = (
            sum(len(chunk.tokens) for chunk in self.chunks) / len(self.chunks)
            if self.chunks
            else 0.0
        )

    @classmethod
    def from_root(
        cls,
        root: Path,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
        epsilon: float = DEFAULT_EPSILON,
        eligible_paths: Iterable[str] | None = None,
    ) -> BM25Index:
        allowed = {normalize_path(path) for path in eligible_paths} if eligible_paths else None
        chunks: list[Chunk] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or ".git" in path.relative_to(root).parts:
                continue
            relative = normalize_path(path.relative_to(root).as_posix())
            if allowed is not None and relative not in allowed:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            chunks.extend(
                chunk_document(relative, text, size=chunk_size, overlap=overlap)
            )
        return cls(
            chunks,
            k1=k1,
            b=b,
            epsilon=epsilon,
            fingerprint=corpus_fingerprint(root, eligible_paths=allowed),
        )

    def query(
        self,
        statement: str,
        *,
        k: int = 10,
        task_id: str = "",
        path_filter: str | Iterable[str] | None = None,
        max_context_tokens: int = 400,
    ) -> RetrievalResult:
        if k <= 0 or max_context_tokens <= 0:
            raise ValueError("k and max_context_tokens must be positive")
        started = time.perf_counter()
        query_tokens = sorted(set(tokenize(statement)))
        total = len(self.chunks)
        allowed_paths = (
            {normalize_path(path) for path in path_filter}
            if path_filter is not None and not isinstance(path_filter, str)
            else None
        )
        scored: list[tuple[float, str, str, Chunk]] = []
        for index, chunk in enumerate(self.chunks):
            if path_filter is not None:
                if isinstance(path_filter, str):
                    prefix = normalize_path(path_filter)
                    if chunk.path != prefix and not chunk.path.startswith(f"{prefix}/"):
                        continue
                elif allowed_paths is not None and chunk.path not in allowed_paths:
                    continue
            counts = Counter(chunk.tokens)
            score = 0.0
            for token in query_tokens:
                posting = self._postings.get(token, {})
                if not posting:
                    continue
                idf = max(self.epsilon, math.log(
                    1
                    + (
                        total
                        - len(posting)
                        + 0.5
                    )
                    / (len(posting) + 0.5)
                ))
                frequency = counts[token]
                length_factor = (
                    1 - self.b + self.b * len(chunk.tokens) / self._average_length
                    if self._average_length
                    else 1
                )
                denominator = frequency + self.k1 * length_factor
                score += idf * frequency * (self.k1 + 1) / denominator
            if score > 0:
                scored.append((score, chunk.path, chunk.chunk_id, chunk))
        scored.sort(key=lambda row: (-row[0], row[1], row[2]))
        hits: list[RetrievalHit] = []
        context_tokens = 0
        seen: set[str] = set()
        for score, path, _, chunk in scored:
            if path in seen:
                continue
            if context_tokens + len(chunk.tokens) > max_context_tokens and hits:
                continue
            seen.add(path)
            available = max_context_tokens - context_tokens
            preview_tokens = chunk.text.split()[:available]
            preview = " ".join(preview_tokens)
            hits.append(
                RetrievalHit(
                    path=path,
                    score=score,
                    rank=len(hits) + 1,
                    chunk_id=chunk.chunk_id,
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                    preview=preview,
                )
            )
            context_tokens += min(len(chunk.tokens), available)
            if len(hits) >= k or context_tokens >= max_context_tokens:
                break
        return RetrievalResult(
            task_id=task_id,
            backend="bm25",
            hits=hits,
            latency_ms=(time.perf_counter() - started) * 1000,
            returned_context_bytes=sum(len(hit.preview.encode("utf-8")) for hit in hits),
            token_estimate=context_tokens,
            context_tokens=context_tokens,
            token_estimator="word-regex-v1",
            ranked_files=[hit.path for hit in hits],
            excerpts=[hit.preview for hit in hits],
            summary=f"{len(hits)} ranked files",
            rank_semantics="verified",
        )

    def artifact(self) -> dict[str, object]:
        return {
            "version": "bm25-v1",
            "fingerprint": self.fingerprint,
            "k1": self.k1,
            "b": self.b,
            "epsilon": self.epsilon,
            "chunks": [asdict(chunk) for chunk in self.chunks],
        }

    def write_artifact(self, destination: Path) -> str:
        content = canonical_json(self.artifact())
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return digest(content)

    @classmethod
    def from_artifact(cls, path: Path) -> BM25Index:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        chunks = [
            Chunk(
                chunk_id=row["chunk_id"],
                path=row["path"],
                text=row["text"],
                tokens=tuple(row["tokens"]),
                line_start=row.get("line_start", 1),
                line_end=row.get("line_end", 1),
            )
            for row in payload["chunks"]
        ]
        return cls(
            chunks,
            k1=payload["k1"],
            b=payload["b"],
            epsilon=payload["epsilon"],
            fingerprint=payload["fingerprint"],
        )


def build_index(root: Path, **kwargs: object) -> BM25Index:
    return BM25Index.from_root(root, **kwargs)


BM25Retriever = BM25Index


def build_index_artifact(root: Path, destination: Path, **kwargs: object) -> str:
    return BM25Index.from_root(root, **kwargs).write_artifact(destination)


def query_index(index: BM25Index, statement: str, **kwargs: object) -> RetrievalResult:
    return index.query(statement, **kwargs)
