from pathlib import Path

from jevgrep_eval.isolation import (
    arm_isolation_probe_script,
    bwrap_argv,
    probe_artifacts,
)


def test_tier_argv_and_probe_artifacts(tmp_path: Path):
    tier_a = bwrap_argv(tmp_path.resolve(), tier="A")
    tier_b = bwrap_argv(tmp_path.resolve(), tier="B")
    assert "--unshare-all" in tier_a
    assert "--unshare-all" not in tier_b
    assert any(item.name == "negative-connectivity" for item in probe_artifacts("A"))
    assert not any(item.name == "negative-connectivity" for item in probe_artifacts("B"))


def test_arm_isolation_probe_scripts_pin_both_variants():
    no_jg = arm_isolation_probe_script(jg_enabled=False)
    assert "command -v jg" in no_jg
    assert "FAIL jg resolvable" in no_jg
    assert "credentials.json" in no_jg
    assert "OK jg unresolved; credentials absent" in no_jg

    with_jg = arm_isolation_probe_script(jg_enabled=True)
    assert "command -v jg" in with_jg
    assert "FAIL jg not resolvable" in with_jg
    assert "credentials.json" in with_jg
    assert "OK jg resolvable; credentials present" in with_jg

    assert no_jg != with_jg
