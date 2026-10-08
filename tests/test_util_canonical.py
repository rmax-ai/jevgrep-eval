from decimal import Decimal

import pytest

from jevgrep_eval.util import canonical_json, digest, normalize_path


def test_canonical_json_and_paths():
    assert canonical_json({"b": 2, "a": Decimal("1.20")}) == b'{"a":"1.20","b":2}\n'
    assert normalize_path("a\\b") == "a/b"
    with pytest.raises(ValueError):
        normalize_path("../escape")


def test_nonfinite_is_rejected():
    with pytest.raises(ValueError):
        canonical_json(float("nan"))


def test_one_byte_decision_change_changes_digest():
    assert digest({"field": "a"}) != digest({"field": "b"})
