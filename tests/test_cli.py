from pathlib import Path

from jevgrep_eval.cli import main


def test_cli_missing_and_policy_codes(tmp_path: Path):
    assert main(["manifest", str(tmp_path / "missing")]) == 5
    assert main(["retrieve", "jg", "--live"]) == 4
    assert main(["report", "build", "--runs", str(tmp_path), "--demo"]) == 0
