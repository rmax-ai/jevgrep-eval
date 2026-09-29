import json
from pathlib import Path

from jevgrep_eval.harnesses.mock import MockHarness
from jevgrep_eval.report import build_demo_report
from jevgrep_eval.util import digest


def test_fixed_clock_mock_report_is_byte_stable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEVGREP_EVAL_NOW", "2026-01-01T00:00:00Z")
    row = {"run_id": "mock-run-1", "simulated": "simulated-fixture"}
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "mock-run-1.json").write_text(json.dumps(row), encoding="utf-8")
    left = build_demo_report(runs, tmp_path / "left.json")
    right = build_demo_report(runs, tmp_path / "right.json")
    assert digest(left) == digest(right)
    assert MockHarness().simulated_marker in "simulated-fixture"
