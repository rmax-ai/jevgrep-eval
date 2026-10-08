"""Named cost columns and a fail-closed reservation ledger."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml

from .models import PricingConfig, PricingEntry, SpendEntry, UsageCost

STAGE_ALLOCATIONS = {
    "stage_0_5": Decimal(2),
    "stage_1_retrieval": Decimal(3),
    "stage_2_pilot": Decimal(10),
    "stage_3_holdout": Decimal(30),
    "contingency": Decimal(5),
}
NAMED_COLUMNS = (
    "jev_cash_usd",
    "codex_quota_tokens",
    "codex_listprice_modeled_usd",
    "local_compute_wall_s",
    "combined_variable_modeled_usd",
)


class SpendGateError(RuntimeError):
    """A call cannot be authorized under the fail-closed spend policy."""


class PricingError(ValueError):
    """Pricing provenance or rate data is incomplete."""


@dataclass(frozen=True)
class CostPerSuccess:
    column: str
    value: Decimal | str
    attempted_tasks: int
    successful_tasks: int


def load_pricing(path: Path) -> PricingConfig:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise PricingError(f"cannot load pricing: {exc}") from exc
    rows = payload.get("entries", payload.get("pricing", [])) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise PricingError("pricing config must contain entries")
    try:
        entries = [PricingEntry.model_validate(row) for row in rows]
        config = PricingConfig(
            entries=entries,
            currency=str(payload.get("currency", "USD")) if isinstance(payload, dict) else "USD",
            cap_usd=Decimal(str(payload.get("cap_usd", "50"))) if isinstance(payload, dict) else Decimal(50),
        )
    except (TypeError, ValueError) as exc:
        raise PricingError(f"invalid pricing config: {exc}") from exc
    for entry in config.entries:
        if not entry.effective_date or not entry.source or not entry.retrieved_at:
            raise PricingError(f"missing provenance for {entry.component}")
    return config


def _money(value: Decimal | str | None) -> Decimal | Literal["unknown"] | None:
    if value is None:
        return None
    if value == "unknown":
        return "unknown"
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if result < 0 or not result.is_finite():
        raise ValueError("money must be finite and non-negative")
    return result


def usage_cost(
    *,
    jev_cash_usd: Decimal | str | None = None,
    codex_quota_tokens: int | None = None,
    codex_listprice_modeled_usd: Decimal | str | None = None,
    local_compute_wall_s: float | str | None = None,
) -> UsageCost:
    """Construct named columns and propagate unknown dollar inputs."""
    jev = _money(jev_cash_usd)
    modeled = _money(codex_listprice_modeled_usd)
    if jev == "unknown" or modeled == "unknown":
        combined: Decimal | Literal["unknown"] = "unknown"
    elif jev is None and modeled is None:
        combined = None
    elif jev is None or modeled is None:
        combined = "unknown"
    else:
        combined = jev + modeled
    return UsageCost(
        jev_cash_usd=jev,
        codex_quota_tokens=codex_quota_tokens,
        codex_listprice_modeled_usd=modeled,
        local_compute_wall_s=local_compute_wall_s,
        combined_variable_modeled_usd=combined,
        unknown_reason=(
            "missing or unmetered dollar receipt"
            if combined == "unknown"
            else None
        ),
    )


def cost_per_success(
    rows: Iterable[tuple[bool, UsageCost]],
    column: str,
) -> CostPerSuccess:
    if column not in NAMED_COLUMNS:
        raise ValueError(f"unknown named cost column: {column}")
    values: list[Decimal] = []
    incomplete = False
    attempted = 0
    successful = 0
    for success, cost in rows:
        attempted += 1
        successful += int(success)
        value = getattr(cost, column)
        if value in (None, "unknown"):
            incomplete = True
            continue
        values.append(Decimal(str(value)))
    if successful == 0:
        return CostPerSuccess(column, "NA", attempted, successful)
    if incomplete or not values:
        return CostPerSuccess(column, "unknown", attempted, successful)
    return CostPerSuccess(column, sum(values, Decimal(0)) / successful, attempted, successful)


class SpendLedger:
    """A reservation ledger whose cap enforcement point is the ledger itself."""

    def __init__(
        self,
        cap_usd: Decimal = Decimal(50),
        *,
        stage_allocations: dict[str, Decimal] | None = None,
    ) -> None:
        if cap_usd < 0:
            raise ValueError("cap must be non-negative")
        self.cap_usd = cap_usd
        self.stage_allocations = dict(stage_allocations or STAGE_ALLOCATIONS)
        self.entries: list[SpendEntry] = []
        self._reserved = Decimal(0)
        self._stopped = False
        self._stage_reserved: dict[str, Decimal] = {}
        self._stage_committed: dict[str, Decimal] = {}
        self._stage_by_call: dict[str, str] = {}

    @property
    def committed_cash_usd(self) -> Decimal:
        return sum(
            (entry.estimate_usd for entry in self.entries if isinstance(entry.estimate_usd, Decimal)),
            Decimal(0),
        )

    @property
    def spent_usd(self) -> Decimal:
        return self.committed_cash_usd

    @property
    def reserved_cash_usd(self) -> Decimal:
        return self._reserved

    @property
    def available_usd(self) -> Decimal:
        return self.cap_usd - self.committed_cash_usd - self._reserved

    def reserve(
        self,
        call_id: str,
        component: str,
        worst_case_usd: Decimal | None = None,
        rate_source: str | None = None,
        *,
        max_source_bytes: int | None = None,
        rate_per_byte: Decimal | None = None,
        stage: str | None = None,
    ) -> SpendEntry:
        """Reserve before a call, optionally deriving a byte-only MODEL bound."""
        if self._stopped:
            raise SpendGateError("ledger is stopped")
        if any(entry.call_id == call_id for entry in self.entries):
            raise SpendGateError(f"call is already reserved: {call_id}")
        if worst_case_usd is None:
            if max_source_bytes is None or rate_per_byte is None:
                raise SpendGateError("ambiguous rate or missing source-byte bound")
            worst_case_usd = Decimal(max_source_bytes) * rate_per_byte
            rate_source = rate_source or "MODEL: byte-only upper bound"
        if component not in {"jev", "codex", "bm25", "evaluator"}:
            raise SpendGateError(f"unknown spend component: {component}")
        if not rate_source:
            raise SpendGateError("rate source is required")
        if worst_case_usd < 0:
            raise ValueError("reservation must be nonnegative")
        if stage and stage in self.stage_allocations:
            stage_reserved = self._stage_reserved.get(stage, Decimal(0))
            stage_committed = self._stage_committed.get(stage, Decimal(0))
            if (
                stage_reserved + stage_committed + worst_case_usd
                > self.stage_allocations[stage]
            ):
                raise SpendGateError("reservation exceeds stage allocation")
        if worst_case_usd > self.available_usd:
            raise SpendGateError("insufficient spend headroom")
        self._reserved += worst_case_usd
        if stage:
            self._stage_reserved[stage] = (
                self._stage_reserved.get(stage, Decimal(0)) + worst_case_usd
            )
            self._stage_by_call[call_id] = stage
        entry = SpendEntry(
            call_id=call_id,
            component=component,  # pydantic validates the closed component set
            rate_source=rate_source,
            reserved_usd=worst_case_usd,
            cumulative_usd=self.committed_cash_usd,
        )
        self.entries.append(entry)
        return entry

    def reconcile(
        self,
        call_id: str,
        *,
        actual_usd: Decimal | None,
        tokens: int | None = None,
        rate_source: str | None = None,
        receipt_id: str | None = None,
    ) -> SpendEntry:
        if self._stopped:
            raise SpendGateError("ledger is stopped")
        candidates = [entry for entry in self.entries if entry.call_id == call_id]
        if not candidates:
            raise SpendGateError(f"unknown reservation: {call_id}")
        previous = candidates[-1]
        if actual_usd is None or not rate_source:
            previous_updated = previous.model_copy(update={"status": "stopped"})
            self.entries[self.entries.index(previous)] = previous_updated
            self._reserved -= previous.reserved_usd
            stage = self._stage_by_call.get(call_id)
            if stage:
                self._stage_reserved[stage] -= previous.reserved_usd
            self._stopped = True
            raise SpendGateError("missing receipt or rate source; ledger stopped")
        if actual_usd < 0:
            raise SpendGateError("receipt is negative")
        stage = self._stage_by_call.get(call_id)
        if stage and stage in self.stage_allocations:
            remaining_stage_reserved = (
                self._stage_reserved.get(stage, Decimal(0)) - previous.reserved_usd
            )
            stage_committed = self._stage_committed.get(stage, Decimal(0))
            if (
                stage_committed + remaining_stage_reserved + actual_usd
                > self.stage_allocations[stage]
            ):
                raise SpendGateError("receipt exceeds stage allocation")
        self._reserved -= previous.reserved_usd
        if stage:
            self._stage_reserved[stage] -= previous.reserved_usd
            self._stage_committed[stage] = (
                self._stage_committed.get(stage, Decimal(0)) + actual_usd
            )
        if actual_usd > self.available_usd:
            self._reserved += previous.reserved_usd
            raise SpendGateError("receipt exceeds remaining cap")
        updated = previous.model_copy(
            update={
                "estimate_usd": actual_usd,
                "tokens": tokens,
                "rate_source": rate_source,
                "receipt_id": receipt_id,
                "reserved_usd": Decimal(0),
                "status": "reconciled",
                "cumulative_usd": self.committed_cash_usd + actual_usd,
            }
        )
        self.entries[self.entries.index(previous)] = updated
        return updated

    def check(self) -> None:
        if self.available_usd < 0:
            raise SpendGateError("ledger cap exceeded")

    def snapshot(self) -> dict[str, Any]:
        return {
            "cap_usd": str(self.cap_usd),
            "committed_cash_usd": str(self.committed_cash_usd),
            "reserved_cash_usd": str(self.reserved_cash_usd),
            "available_cash_usd": str(self.available_usd),
            "entries": [entry.model_dump(mode="json") for entry in self.entries],
        }


PricingLoader = load_pricing
CostLedger = SpendLedger
compute_usage_cost = usage_cost
