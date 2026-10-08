from pathlib import Path

import pytest

from jevgrep_eval.scoring import (
    ScoringError,
    evaluate,
    load_metric_registry,
    patch_similarity,
    verify_emitted_metrics,
)


def test_similarity_is_diagnostic_only():
    assert patch_similarity(b"a", b"a") == 1


def test_metric_registry_rejects_uncovered(tmp_path: Path):
    path = tmp_path / "metrics.yaml"
    path.write_text(
        "metrics:\n"
        "  - name: x\n"
        "    population: p\n"
        "    numerator: n\n"
        "    denominator: d\n"
        "    source: s\n"
        "    missing_data_rule: m\n"
        "    interpretation: i\n",
        encoding="utf-8",
    )
    registry = load_metric_registry(path)
    with pytest.raises(ScoringError):
        verify_emitted_metrics({}, registry)


def test_evaluate_uses_distinct_hidden_test_command(
    task_case,
    mini_tree: Path,
    tmp_path: Path,
):
    task = task_case.model_copy(
        update={
            "hidden_test_command": [
                "python3",
                "-c",
                "from pathlib import Path; Path('hidden-ran').write_text('ok')",
            ]
        }
    )
    destination = tmp_path / "evaluation"
    result = evaluate(task, mini_tree, b"", destination, timeout_s=5)

    assert result.task_success
    assert result.upstream_passed
    assert result.hidden_passed
    assert (destination / "hidden-ran").read_text(encoding="utf-8") == "ok"


def test_hidden_patch_resets_agent_edits_to_patch_owned_files(
    task_case,
    mini_tree: Path,
    tmp_path: Path,
):
    """Live regression: an agent edit to a file the hidden patch touches made the
    patch unappliable -> ``tests_not_run`` (click-3533 smoke). Patch-owned files
    must be reset to base before applying the oracle tests."""
    import shutil

    from jevgrep_eval.runner import capture_patch

    tests_dir = mini_tree / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_oracle.py").write_text(
        "def test_base():\n    assert True\n", encoding="utf-8"
    )

    hidden_patch = tmp_path / "hidden_tests.patch"
    hidden_patch.write_text(
        "diff --git a/tests/test_oracle.py b/tests/test_oracle.py\n"
        "--- a/tests/test_oracle.py\n"
        "+++ b/tests/test_oracle.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def test_base():\n"
        "     assert True\n"
        "+ORACLE_MARKER = True\n",
        encoding="utf-8",
    )

    # The agent rewrites the same test file during its run.
    after = tmp_path / "after"
    shutil.copytree(mini_tree, after)
    (after / "tests" / "test_oracle.py").write_text(
        "def test_base():\n    assert False\n", encoding="utf-8"
    )
    agent_patch = capture_patch(mini_tree, after).patch

    task = task_case.model_copy(
        update={
            "hidden_test_command": [
                "python3",
                "-c",
                (
                    "from pathlib import Path;"
                    "text=Path('tests/test_oracle.py').read_text();"
                    "Path('hidden-ran').write_text("
                    "'oracle' if 'ORACLE_MARKER' in text else 'agent')"
                ),
            ],
        }
    )
    destination = tmp_path / "evaluation"
    result = evaluate(
        task,
        mini_tree,
        agent_patch,
        destination,
        hidden_test_patch=hidden_patch,
        timeout_s=10,
    )

    assert result.failure_class is None
    assert result.hidden_passed
    assert (destination / "hidden-ran").read_text(encoding="utf-8") == "oracle"
