from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from jevgrep_eval.corpus import Corpus, validate_manifest
from jevgrep_eval.materialize import leak_scan, materialize
from jevgrep_eval.models import FailureClass, TaskCase, TerminalStatus
from jevgrep_eval.retrieval.bm25 import BM25Index
from jevgrep_eval.runner import Runner, capture_patch
from jevgrep_eval.scoring import evaluate


def _write_git_state(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=root, check=True)


def _task() -> TaskCase:
    return TaskCase(
        task_id="integration-task",
        repo_id="synthetic",
        base_sha="base",
        gold_sha="gold",
        task_class="synthetic-regression",
        statement="make the answer return the expected value",
        changed_files=["src/app.py"],
        gold_evidence_files=["src/app.py"],
        hidden_test_patch="hidden.patch",
        test_runner="pytest",
        test_command=[sys.executable, "-m", "pytest", "-q", "tests/test_base.py"],
        hidden_test_command=[
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_hidden.py",
        ],
        expected_test_seconds=1.0,
        stratum="synthetic",
    )


def _evaluation_fixtures(tmp_path: Path) -> tuple[TaskCase, Path, bytes, Path]:
    base = tmp_path / "base"
    (base / "src").mkdir(parents=True)
    (base / "tests").mkdir()
    (base / "src" / "app.py").write_text("def answer():\n    return 0\n", encoding="utf-8")
    (base / "tests" / "test_base.py").write_text(
        "def test_base():\n    assert True\n", encoding="utf-8"
    )
    _write_git_state(base)

    clean_base = tmp_path / "base-workspace"
    materialize(base, clean_base)
    after = tmp_path / "after"
    materialize(base, after)
    (after / "src" / "app.py").write_text(
        "def answer():\n    return 1\n", encoding="utf-8"
    )
    patch = capture_patch(clean_base, after).patch

    hidden_source = base / "tests" / "test_hidden.py"
    hidden_source.write_text(
        "from src.app import answer\n\n\ndef test_answer():\n    assert answer() == 1\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "--intent-to-add", "tests/test_hidden.py"],
        cwd=base,
        check=True,
    )
    hidden_patch = subprocess.run(
        ["git", "diff", "--binary", "--", "tests/test_hidden.py"],
        cwd=base,
        capture_output=True,
        check=True,
    ).stdout
    subprocess.run(["git", "reset", "--", "tests/test_hidden.py"], cwd=base, check=True)
    hidden_source.unlink()
    hidden_path = tmp_path / "hidden.patch"
    hidden_path.write_bytes(hidden_patch)
    return _task(), clean_base, patch, hidden_path


def test_frozen_corpus_manifest_and_admission_counts():
    root = Path(__file__).parents[1] / "corpus"
    validate_manifest(root)
    corpus = Corpus.load(root)
    assert len(corpus.tasks) == 56
    assert len(corpus.admitted_tasks("dev")) == 12
    assert len(corpus.admitted_tasks("holdout")) == 10
    assert {task.repo_id for task in corpus.admitted_tasks("holdout")} >= {
        "colinhacks__zod",
        "immerjs__immer",
    }


@pytest.mark.parametrize(
    ("source_name", "source_text"),
    [
        ("app.js", "export function answer() { return 1; }\n"),
        ("app.ts", "export const answer: number = 1;\n"),
    ],
)
def test_agent_workspace_is_leak_free_for_js_and_ts(
    tmp_path: Path, source_name: str, source_text: str
):
    source = tmp_path / source_name.split(".")[1]
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / source_name).write_text(source_text, encoding="utf-8")
    (source / "corpus" / "gold").mkdir(parents=True)
    (source / "corpus" / "gold" / "patch.diff").write_text("private", encoding="utf-8")
    (source / "corpus" / "hidden").mkdir()
    (source / "corpus" / "hidden" / "test.js").write_text("private", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("private", encoding="utf-8")

    workspace = tmp_path / "workspace"
    manifest = materialize(source, workspace)
    paths = {entry.path for entry in manifest.files}
    assert f"src/{source_name}" in paths
    assert not any("corpus/gold" in path or "corpus/hidden" in path for path in paths)
    assert not any(path.startswith(".git/") for path in paths)
    assert leak_scan(workspace, ("gold", "hidden", ".git")) == []


def test_gold_swap_invariance_and_deterministic_bm25(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "a.py").write_text("def answer():\n    return 1\n", encoding="utf-8")
    (source / "corpus").mkdir()
    (source / "corpus" / "gold").write_text("one", encoding="utf-8")
    first = materialize(source, tmp_path / "one")
    index_one = BM25Index.from_root(tmp_path / "one")
    (source / "corpus" / "gold").write_text("two", encoding="utf-8")
    second = materialize(source, tmp_path / "two")
    index_two = BM25Index.from_root(tmp_path / "two")
    assert first.workspace_digest == second.workspace_digest
    assert index_one.artifact() == index_two.artifact()


def test_e2e_mock_runner_replay_evaluate_and_verify(tmp_path: Path):
    task, base, _, hidden_patch = _evaluation_fixtures(tmp_path)
    workspace = tmp_path / "agent"
    materialize(base, workspace)
    agent = tmp_path / "mock-agent.py"
    agent.write_text(
        "from pathlib import Path\n"
        "Path('src/app.py').write_text('def answer():\\n    return 1\\n')\n"
        "print('{\"type\":\"session_start\",\"session_id\":\"s\"}')\n"
        "print('{\"type\":\"tool_call\",\"session_id\":\"s\",\"command\":\"edit src/app.py\","
        "\"result\":{},\"completed\":true}')\n"
        "print('{\"type\":\"session_end\",\"session_id\":\"s\"}')\n",
        encoding="utf-8",
    )
    record = Runner(timeout_s=10).run(
        run_id="mock-integration",
        task_id=task.task_id,
        condition_id="a0",
        workspace=workspace,
        argv=[sys.executable, str(agent)],
        env={"PATH": str(Path(sys.executable).parent), "JEVGREP_EVAL_SIMULATED": "1"},
        artifact_dir=tmp_path / "run",
        task=task,
        statement=task.statement,
        hidden_test_patch=hidden_patch,
    )
    assert record.task_success is True
    assert "simulated-fixture" in record.flags
    assert record.trace_coverage == "full"
    assert record.stage_records[-1].terminal_status is TerminalStatus.COMPLETED
    from jevgrep_eval.envelope import verify_run

    assert verify_run(tmp_path / "run").valid


def test_evaluator_failure_classes_and_hidden_command_separation(tmp_path: Path):
    task, base, patch, hidden_patch = _evaluation_fixtures(tmp_path)
    correct = evaluate(
        task,
        base,
        patch,
        tmp_path / "correct",
        hidden_test_patch=hidden_patch,
    )
    assert correct.task_success
    assert correct.failure_class is None

    localized = evaluate(
        task,
        base,
        b"",
        tmp_path / "localized",
        hidden_test_patch=hidden_patch,
    )
    assert localized.failure_class is FailureClass.LOCALIZATION

    incorrect_patch = patch.replace(b"return 1", b"return 2")
    incorrect = evaluate(
        task,
        base,
        incorrect_patch,
        tmp_path / "incorrect",
        hidden_test_patch=hidden_patch,
    )
    assert incorrect.failure_class is FailureClass.INCORRECT_IMPLEMENTATION

    malformed = evaluate(
        task,
        base,
        b"not a patch",
        tmp_path / "malformed",
        hidden_test_patch=hidden_patch,
    )
    assert malformed.failure_class is FailureClass.MALFORMED_PATCH

    env_failure = evaluate(
        task,
        base,
        patch,
        tmp_path / "env-failure",
        hidden_test_patch=hidden_patch,
        hidden_test_command=[str(tmp_path / "missing-command")],
    )
    assert env_failure.failure_class is FailureClass.ENV_FAILURE

    regression = evaluate(
        task,
        base,
        patch,
        tmp_path / "regression",
        hidden_test_patch=hidden_patch,
        upstream_command=[sys.executable, "-c", "raise SystemExit(3)"],
    )
    assert regression.failure_class is FailureClass.REGRESSION

    timeout = evaluate(
        task,
        base,
        patch,
        tmp_path / "timeout",
        hidden_test_patch=hidden_patch,
        upstream_command=[sys.executable, "-c", "import time; time.sleep(1)"],
        timeout_s=0.01,
    )
    assert timeout.failure_class is FailureClass.TIMEOUT


def test_ledger_dry_run_is_fail_closed(tmp_path: Path):
    del tmp_path
    from decimal import Decimal

    from jevgrep_eval.costing import SpendGateError, SpendLedger

    ledger = SpendLedger(cap_usd=Decimal(2))
    ledger.reserve("mock-call", "evaluator", Decimal(1), "fixture-rate", stage="stage_0_5")
    ledger.reconcile(
        "mock-call",
        actual_usd=Decimal(0),
        rate_source="fixture-receipt",
        receipt_id="mock-receipt",
    )
    assert ledger.available_usd == Decimal(2)
    ledger.reserve("missing-receipt", "evaluator", Decimal(1), "fixture-rate")
    with pytest.raises(SpendGateError):
        ledger.reconcile("missing-receipt", actual_usd=None)


def test_runner_records_crash_retry_and_resume(mini_tree: Path, tmp_path: Path):
    failed_dir = tmp_path / "failed"
    retry = Runner(timeout_s=10).run(
        run_id="crash",
        task_id="synthetic",
        condition_id="a0",
        workspace=mini_tree,
        argv=[sys.executable, "-c", "raise SystemExit(3)"],
        artifact_dir=failed_dir,
        retry_on_env_failure=True,
    )
    assert retry.run_id == "crash.retry1"
    assert retry.terminal_status is TerminalStatus.ENV_FAILURE
    assert (failed_dir / "run-record.json").is_file()
    assert (tmp_path / "crash.retry1" / "run-record.json").is_file()

    successful_dir = tmp_path / "successful"
    first = Runner(timeout_s=10).run(
        run_id="resume",
        task_id="synthetic",
        condition_id="a0",
        workspace=mini_tree,
        argv=[sys.executable, "-c", "pass"],
        artifact_dir=successful_dir,
    )
    resumed = Runner(timeout_s=10).run(
        run_id="resume",
        task_id="synthetic",
        condition_id="a0",
        workspace=mini_tree,
        argv=[sys.executable, "-c", "raise SystemExit(9)"],
        artifact_dir=successful_dir,
        resume=True,
    )
    assert resumed == first
