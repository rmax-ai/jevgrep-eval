import json
from decimal import Decimal
from pathlib import Path

from jevgrep_eval.costing import SpendLedger
from jevgrep_eval.live import (
    JG_RATE,
    _dep_cache,
    _source_repo,
    build_prompt,
    load_task,
    plan_run,
    reconcile_for_run,
    run_live,
    save_ledger,
)


def _task(root: Path, task_id: str = "tiny") -> None:
    task_dir = root / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text(
        f"""task_id: {task_id}
repo_id: tiny__repo
base_sha: deadbeef
gold_sha: cafebabe
task_class: test
statement: Fix the tiny bug.
hidden_test_patch: tasks/{task_id}/hidden_tests.patch
test_runner: pytest
test_command: [python, -m, pytest]
setup_commands: []
""",
        encoding="utf-8",
    )
    (task_dir / "hidden_tests.patch").write_text("", encoding="utf-8")
    (task_dir / "admission.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "base_hidden": {
                    "repetitions": [{"argv": ["python", "-m", "pytest", "hidden.py"]}]
                },
            }
        ),
        encoding="utf-8",
    )
    (task_dir / "gold-evidence.json").write_text(
        json.dumps({"task_id": task_id, "files": ["src/tiny.py"]}),
        encoding="utf-8",
    )


def _inputs(tmp_path: Path, *, arm: str = "a1") -> tuple[Path, Path, Path, Path, Path]:
    corpus = tmp_path / "corpus"
    _task(corpus)
    bindings = tmp_path / "bindings.yaml"
    bindings.write_text(
        "\n".join(
            [
                f"home: {tmp_path / 'home'}",
                f"tools: {tmp_path / 'tools'}",
                f"uv: {tmp_path / 'uv'}",
                f"node: {tmp_path / 'node'}",
                f"codex_home_source: {tmp_path / 'codex-source'}",
                f"provider_credentials: {tmp_path / 'credentials'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    experiment = tmp_path / "experiment.yaml"
    experiment.write_text(
        "agent:\n  model: test-model\n  effort: low\n"
        "budget:\n  stage: stage_2_pilot\n",
        encoding="utf-8",
    )
    condition = tmp_path / f"{arm}.yaml"
    tools = "[jg]" if arm == "a1" else "[]"
    condition.write_text(
        f"id: {arm}\nlabel: test\nretrieval_tools: {tools}\n"
        "prompt_fragment: use the available tool\n",
        encoding="utf-8",
    )
    runs = tmp_path / "runs"
    ledger = runs / "ledger.json"
    return corpus, bindings, experiment, condition, ledger


def test_dry_run_is_pure_and_contains_complete_plan(tmp_path: Path, capsys):
    corpus, bindings, experiment, condition, ledger = _inputs(tmp_path)
    runs = tmp_path / "runs"

    assert (
        run_live(
            runs_root=runs,
            ledger_path=ledger,
            experiment_path=experiment,
            condition_path=condition,
            corpus_root=corpus,
            task_id="tiny",
            arm="a1",
            rep=0,
            dry_run=True,
            bindings_path=bindings,
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan["run_id"] == "tiny-a1-r0"
    assert plan["budget_reservation_preview"] == "0.288"
    assert "--setenv" in plan["bwrap_argv"]
    path_index = plan["bwrap_argv"].index("PATH")
    assert plan["bwrap_argv"][path_index + 1].startswith(
        f"{tmp_path / 'node'}/bin:"
    )
    assert Path(plan["executor_argv_tail"][0]).is_absolute()
    assert not runs.exists()

    a0_corpus, a0_bindings, a0_experiment, _, a0_ledger = _inputs(
        tmp_path / "a0", arm="a0"
    )
    a0_plan = plan_run(
        runs_root=tmp_path / "a0" / "runs",
        ledger_path=a0_ledger,
        experiment_path=a0_experiment,
        condition_path=tmp_path / "a0" / "a0.yaml",
        corpus_root=a0_corpus,
        task_id="tiny",
        arm="a0",
        bindings_path=a0_bindings,
    )
    assert a0_plan["budget_reservation_preview"] == "0"


def test_budget_failure_happens_before_materialization(tmp_path: Path):
    corpus, bindings, experiment, condition, ledger_path = _inputs(tmp_path)
    runs = tmp_path / "runs"
    ledger = SpendLedger()
    ledger.reserve(
        "already-reserved",
        "jev",
        Decimal("9.9"),
        "fixture",
        stage="stage_2_pilot",
    )
    save_ledger(ledger, ledger_path)

    assert (
        run_live(
            runs_root=runs,
            ledger_path=ledger_path,
            experiment_path=experiment,
            condition_path=condition,
            corpus_root=corpus,
            task_id="tiny",
            arm="a1",
            rep=0,
            dry_run=False,
            bindings_path=bindings,
        )
        == 4
    )
    assert not (runs / "tiny-a1-r0" / "workspace").exists()


def test_prompt_builder():
    assert build_prompt("statement", "") == "statement"
    assert build_prompt(" statement ", " fragment ") == "statement\n\nfragment"


def test_task_loading_includes_evaluator_artifacts(tmp_path: Path):
    corpus = tmp_path / "corpus"
    _task(corpus, "case")
    loaded = load_task(corpus, "case")
    assert loaded["hidden_test_patch"] == corpus / "tasks" / "case" / "hidden_tests.patch"
    assert loaded["hidden_test_command"] == ["python", "-m", "pytest", "hidden.py"]
    assert loaded["gold_evidence_files"] == ["src/tiny.py"]


def test_reconcile_counts_only_jg_events():
    ledger = SpendLedger()
    ledger.reserve("run", "jev", Decimal("0.288"), "fixture")
    reconcile_for_run(
        ledger,
        "run",
        [{"kind": "search_jg"}, {"kind": "search_jg"}, {"kind": "search_jg"}],
        JG_RATE,
    )
    assert ledger.entries[0].estimate_usd == Decimal("0.144")


def test_staged_layout_resolution(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    repo = tmp_path / ".staging" / "corpus-inputs" / "repo-cache" / "tiny__repo"
    repo.mkdir(parents=True)
    dep = tmp_path / ".staging" / "corpus-inputs" / "dep-cache" / "tiny__repo" / "uv"
    dep.mkdir(parents=True)
    task = {"repo_id": "tiny__repo"}
    assert _source_repo(corpus, task) == repo
    assert _dep_cache(corpus, task) == dep
