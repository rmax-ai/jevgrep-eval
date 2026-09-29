from pathlib import Path

from jevgrep_eval.harnesses.codex import CodexHarness
from jevgrep_eval.harnesses.mock import MockHarness


def test_mock_is_fixture_driven(tmp_path: Path):
    result = MockHarness([{"command": "cat src/a.py"}]).run("prompt", tmp_path)
    assert result.simulated
    assert result.events[0]["command"] == "cat src/a.py"


def test_codex_invocation_argv():
    invocation = CodexHarness(config={"command": ["fake-codex"]}).assemble_invocation(
        "prompt", model="m", effort="low", env={"PATH": "/bin"}
    )
    assert invocation.argv == (
        "fake-codex",
        "--json",
        "--skip-git-repo-check",
        "-s",
        "workspace-write",
        "--model",
        "m",
        "-c",
        "model_reasoning_effort=low",
        "prompt",
    )
    assert invocation.invocation_digest
