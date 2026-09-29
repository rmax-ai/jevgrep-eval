from pathlib import Path

from jevgrep_eval.isolation import bwrap_argv, probe_artifacts


def test_tier_argv_and_probe_artifacts(tmp_path: Path):
    tier_a = bwrap_argv(tmp_path.resolve(), tier="A")
    tier_b = bwrap_argv(tmp_path.resolve(), tier="B")
    assert "--unshare-all" in tier_a
    assert "--unshare-all" not in tier_b
    assert any(item.name == "negative-connectivity" for item in probe_artifacts("A"))
    assert not any(item.name == "negative-connectivity" for item in probe_artifacts("B"))
