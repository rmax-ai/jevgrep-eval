"""Retrieval-only metrics with explicit denominator and missing-data rules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..models import RetrievalHit, RetrievalResult
from ..util import normalize_path


@dataclass(frozen=True)
class MetricValue:
    value: float | None
    reason: str | None = None


@dataclass(frozen=True)
class RetrievalMetrics:
    hit_at_k: float | None
    recall_at_k: float | None
    mrr: float | None
    evidence_recall_at_k: float | None
    reference_count: int
    reasons: dict[str, str] | None = None
    returned_context_tokens: int | None = None
    returned_context_bytes: int = 0

    @property
    def hit(self) -> float | None:
        return self.hit_at_k

    @property
    def recall(self) -> float | None:
        return self.recall_at_k


def _unique_paths(hits: Iterable[RetrievalHit]) -> list[tuple[str, int]]:
    seen: set[str] = set()
    result: list[tuple[str, int]] = []
    for hit in sorted(hits, key=lambda value: value.rank):
        path = normalize_path(hit.path)
        if path not in seen:
            seen.add(path)
            result.append((path, hit.rank))
    return result


def calculate_metrics(
    result: RetrievalResult,
    reference_files: Iterable[str],
    *,
    evidence_files: Iterable[str] = (),
    base_present: Iterable[str] | None = None,
) -> RetrievalMetrics:
    """Calculate first-unique-file Hit@K, Recall@K, and MRR.

    Reference paths are deduplicated by canonical path and optionally reduced
    to paths in the base-present eligible manifest.  An empty denominator is
    ``NA`` rather than zero.
    """
    eligible = {normalize_path(path) for path in base_present} if base_present is not None else None
    reference = {normalize_path(path) for path in reference_files}
    if eligible is not None:
        reference &= eligible
    evidence = {normalize_path(path) for path in evidence_files}
    ranked = _unique_paths(result.hits)
    returned = {path for path, _ in ranked}
    if not reference:
        return RetrievalMetrics(
            None,
            None,
            None,
            None,
            0,
            {
                "hit_at_k": "empty or base-absent reference set",
                "recall_at_k": "empty or base-absent reference set",
                "mrr": "empty or base-absent reference set",
                "evidence_recall_at_k": "empty or base-absent evidence set",
            },
            result.context_tokens,
            result.returned_context_bytes,
        )
    ranks = [index + 1 for index, (path, _) in enumerate(ranked) if path in reference]
    return RetrievalMetrics(
        1.0 if ranks else 0.0,
        len(returned & reference) / len(reference),
        1.0 / min(ranks) if ranks else 0.0,
        len(returned & evidence) / len(evidence) if evidence else None,
        len(reference),
        {"evidence_recall_at_k": "empty evidence set"} if not evidence else {},
        result.context_tokens,
        result.returned_context_bytes,
    )


def hit_at_k(result: RetrievalResult, reference_files: Iterable[str]) -> float | None:
    return calculate_metrics(result, reference_files).hit_at_k


def recall_at_k(result: RetrievalResult, reference_files: Iterable[str]) -> float | None:
    return calculate_metrics(result, reference_files).recall_at_k


def mrr(result: RetrievalResult, reference_files: Iterable[str]) -> float | None:
    return calculate_metrics(result, reference_files).mrr


compute_metrics = calculate_metrics
RetrievalMetricResult = RetrievalMetrics
