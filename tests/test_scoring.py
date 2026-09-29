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
