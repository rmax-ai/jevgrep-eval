from decimal import Decimal

import pytest
from pydantic import ValidationError

from jevgrep_eval.models import ConditionConfig, TaskCase, UsageCost


def test_models_are_strict_and_forbid_unknown_keys():
    with pytest.raises(ValidationError):
        TaskCase(
            task_id="t",
            repo_id="r",
            base_sha="b",
            gold_sha="g",
            task_class="x",
            statement="s",
            hidden_test_patch="h",
            test_runner="pytest",
            stratum="x",
            unexpected=True,
        )
    assert ConditionConfig(id="a0", label="native").forced_first == "none"


def test_money_is_decimal_or_explicit_unknown():
    value = UsageCost(jev_cash_usd="1.20")
    assert value.jev_cash_usd == Decimal("1.20")
    assert UsageCost(jev_cash_usd="unknown").jev_cash_usd == "unknown"
    with pytest.raises(ValidationError):
        UsageCost(jev_cash_usd=1.2)
