from decimal import Decimal

import pytest

from jevgrep_eval.costing import SpendGateError, SpendLedger, usage_cost


def test_reserve_reconcile_and_fail_closed():
    ledger = SpendLedger(Decimal(1))
    ledger.reserve("call", "jev", Decimal("0.5"), "fixture")
    row = ledger.reconcile("call", actual_usd=Decimal("0.25"), rate_source="receipt")
    assert row.status == "reconciled"
    ledger.reserve("missing", "jev", Decimal("0.1"), "fixture")
    with pytest.raises(SpendGateError):
        ledger.reconcile("missing", actual_usd=None, rate_source=None)


def test_unknown_propagates():
    assert usage_cost(jev_cash_usd="unknown", codex_listprice_modeled_usd="1").combined_variable_modeled_usd == "unknown"
