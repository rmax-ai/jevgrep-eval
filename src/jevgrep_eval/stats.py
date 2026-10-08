"""Pre-registered task-clustered paired statistics."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BootstrapInterval:
    estimate: float
    low: float
    high: float
    reps: int
    seed: int
    caveat: str | None = None
    method: str = (
        "task-clustered paired percentile bootstrap; task ids resampled "
        "with replacement; all repetitions carried together"
    )

    @property
    def observed_effect(self) -> float:
        return self.estimate

    @property
    def confidence_interval(self) -> tuple[float, float]:
        return self.low, self.high

    @property
    def method_line(self) -> str:
        return self.method


@dataclass(frozen=True)
class McNemarResult:
    p_value: float
    discordant_left: int
    discordant_right: int
    method: str = "exact two-sided McNemar test on the first complete paired run"


@dataclass(frozen=True)
class StratumCounts:
    stratum: str
    left_successes: int
    right_successes: int
    paired_tasks: int


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot calculate a quantile of no values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _task_differences(table: Sequence[Any]) -> list[list[float]]:
    """Normalize legacy differences and task tables into clusters."""
    if not table:
        return []
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in table):
        return [[float(value)] for value in table]
    clusters: list[list[float]] = []
    for row in table:
        if isinstance(row, Mapping):
            raw = row.get("differences", row.get("difference"))
            if raw is None:
                left = row.get("left", row.get("a"))
                right = row.get("right", row.get("b"))
                if left is None or right is None:
                    raise ValueError("task row needs differences or paired values")
                raw = [float(left) - float(right)]
            if isinstance(raw, (int, float)):
                raw = [raw]
            clusters.append([float(value) for value in raw])
        elif isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
            clusters.append([float(value) for value in row])
        else:
            raise TypeError("unsupported task-cluster row")
    return clusters


def clustered_bootstrap(
    differences: Sequence[Any],
    *,
    reps: int = 10_000,
    seed: int = 0,
) -> BootstrapInterval:
    """Resample task clusters, carrying all repetitions within each task."""
    if reps <= 0:
        raise ValueError("reps must be positive")
    clusters = _task_differences(differences)
    if not clusters:
        raise ValueError("at least one task is required")
    per_task = [sum(cluster) / len(cluster) for cluster in clusters]
    estimate = sum(per_task) / len(per_task)
    if all(value == 0 for value in per_task):
        return BootstrapInterval(estimate, 0.0, 0.0, reps, seed, "no discordant observations")
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(reps):
        sampled = [per_task[rng.randrange(len(per_task))] for _ in per_task]
        samples.append(sum(sampled) / len(sampled))
    return BootstrapInterval(
        estimate,
        _quantile(samples, 0.025),
        _quantile(samples, 0.975),
        reps,
        seed,
    )


def exact_mcnemar(left: Sequence[bool], right: Sequence[bool]) -> McNemarResult:
    """Compute the exact two-sided binomial p-value for paired outcomes."""
    if len(left) != len(right):
        raise ValueError("paired inputs must have equal length")
    discordant_left = sum(bool(a) and not bool(b) for a, b in zip(left, right))
    discordant_right = sum(bool(b) and not bool(a) for a, b in zip(left, right))
    discordant = discordant_left + discordant_right
    if discordant == 0:
        return McNemarResult(1.0, 0, 0)
    smaller = min(discordant_left, discordant_right)
    lower_tail = sum(math.comb(discordant, index) for index in range(smaller + 1))
    p_value = min(1.0, 2 * lower_tail / (2**discordant))
    return McNemarResult(p_value, discordant_left, discordant_right)


def mcnemar_exact(left: Sequence[bool], right: Sequence[bool]) -> float:
    """Compatibility helper returning only the exact p-value."""
    return exact_mcnemar(left, right).p_value


def paired_deltas(left: Sequence[float], right: Sequence[float]) -> list[float]:
    if len(left) != len(right):
        raise ValueError("paired inputs must have equal length")
    return [float(a) - float(b) for a, b in zip(left, right)]


def strata_counts(
    rows: Sequence[Mapping[str, Any]],
    *,
    stratum_key: str = "stratum",
    left_key: str = "left_success",
    right_key: str = "right_success",
) -> list[StratumCounts]:
    """Return descriptive counts only, sorted by stratum label."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(stratum_key, "unclassified")), []).append(row)
    return [
        StratumCounts(
            stratum=stratum,
            left_successes=sum(bool(row.get(left_key)) for row in values),
            right_successes=sum(bool(row.get(right_key)) for row in values),
            paired_tasks=len(values),
        )
        for stratum, values in sorted(grouped.items())
    ]


bootstrap_paired = clustered_bootstrap
