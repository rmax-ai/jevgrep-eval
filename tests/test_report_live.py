"""Live report builder tests — paired pilot evidence with frozen analysis rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from jevgrep_eval.cli import main
from jevgrep_eval.report import ReportRefusal, build_live_report


def _write_task(corpus: Path, task: str, status: str = "admitted") -> None:
    directory = corpus / "tasks" / task
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "task.yaml").write_text(
        yaml.safe_dump({"task_id": task, "admission_status": status}), encoding="utf-8"
    )


def _write_run(
    runs: Path,
    task: str,
    arm: str,
    *,
    status: str = "completed",
    success: bool | None = None,
    coverage: str = "full",
    flags: tuple[str, ...] = (),
    rep: int = 0,
    costs: dict | None = None,
    jg_events: int = 0,
) -> Path:
    run_id = f"{task}-{arm}-r{rep}"
    directory = runs / run_id
    directory.mkdir(parents=True, exist_ok=True)
    events = [
        {"kind": "other_shell", "result": {"summary": "Jevgrep: 3 hits"}}
        for _ in range(jg_events)
    ]
    record = {
        "run_id": run_id,
        "task_id": task,
        "condition_id": arm,
        "repetition": rep,
        "terminal_status": status,
        "flags": list(flags),
        "trace_coverage": coverage,
        "patch_digest": "0" * 64,
        "protocol_id": "v1",
        "state": "RECORDED",
        "events": events,
    }
    (directory / "run-record.json").write_text(json.dumps(record), encoding="utf-8")
    if success is not None:
        (directory / "evaluation-result.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "task_success": success,
                    "failure_class": None if success else "incorrect_implementation",
                    "replay_equal": True,
                }
            ),
            encoding="utf-8",
        )
    if costs is not None:
        (directory / "costs.json").write_text(json.dumps(costs), encoding="utf-8")
    return directory


def _build(runs: Path, corpus: Path, tmp_path: Path, **kwargs) -> dict:
    destination = tmp_path / "report.json"
    content = build_live_report(runs, destination, corpus_dir=corpus, **kwargs)
    assert destination.read_bytes() == content
    return json.loads(content)


def test_live_report_matrix_statistics_and_claims(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    for task in ("t1", "t2"):
        _write_task(corpus, task)
    for task, outcomes in {"t1": (False, True, False), "t2": (False, True, True)}.items():
        for arm, success in zip(("a0", "a1", "a3"), outcomes):
            costs = {"jev_cash_usd": "0.1", "codex_quota_tokens": 100, "local_compute_wall_s": 1.5}
            _write_run(runs, task, arm, success=success, costs=costs if arm == "a1" else None)

    report = _build(runs, corpus, tmp_path)
    primary = report["analysis_sets"]["primary"]
    assert primary["tasks"] == ["t1", "t2"]
    a1 = primary["comparisons"]["a1_minus_a0"]
    assert a1["estimate"] == 1.0 and (a1["ci_low"], a1["ci_high"]) == (1.0, 1.0)
    assert a1["mcnemar_p"] == 0.5 and a1["discordant_left"] == 2 and a1["discordant_right"] == 0
    a3 = primary["comparisons"]["a3_minus_a0"]
    assert a3["estimate"] == 0.5 and a3["mcnemar_p"] == 1.0
    assert report["spend"]["run_totals"]["jev_cash_usd_total"] == "0.200"
    statuses = {claim["claim"]: claim["status"] for claim in report["claim_map"]}
    assert statuses["paired A0/A1/A3 pilot executed on the frozen dev corpus"] == "supported"
    assert statuses["retrieval-only metrics"] == "withheld"
    assert report["report_digest"]


def test_live_report_refuses_simulated(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    _write_task(corpus, "t1")
    _write_run(runs, "t1", "a0", success=True, flags=("simulated-fixture",))
    with pytest.raises(ReportRefusal):
        build_live_report(runs, tmp_path / "report.json", corpus_dir=corpus)


def test_live_report_excludes_rejected_and_missing_admission(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    _write_task(corpus, "good")
    _write_task(corpus, "bad", status="rejected")
    for arm in ("a0", "a1", "a3"):
        _write_run(runs, "good", arm, success=True)
        _write_run(runs, "bad", arm, success=True)
        _write_run(runs, "ghost", arm, success=True)

    report = _build(runs, corpus, tmp_path)
    reasons = sorted(entry["reason"] for entry in report["exclusions"])
    assert reasons == ["admission_status=rejected"] * 3 + ["missing-admission-record"] * 3
    assert report["analysis_sets"]["primary"]["tasks"] == ["good"]
    assert {cell["task_id"] for cell in report["runs"]} == {"good"}


def test_live_report_timeout_counts_as_failure_and_partial_suppresses(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    _write_task(corpus, "t1")
    _write_run(runs, "t1", "a0", success=True)
    _write_run(runs, "t1", "a1", status="timeout", success=True, coverage="partial", jg_events=2)
    _write_run(runs, "t1", "a3", status="timeout", success=None)

    report = _build(runs, corpus, tmp_path)
    cells = {cell["arm"]: cell for cell in report["runs"]}
    assert cells["a1"]["task_success_raw"] is True
    assert cells["a1"]["effective_success"] is False
    assert cells["a1"]["jev_executed_searches"] is None
    assert any("time budget" in note for note in cells["a1"]["notes"])
    assert any("partial trace coverage" in note for note in cells["a1"]["notes"])
    assert cells["a3"]["effective_success"] is False
    assert any("timeout-without-evaluation" in note for note in cells["a3"]["notes"])
    assert cells["a3"]["analysis_eligible"] is True
    assert report["analysis_sets"]["primary"]["tasks"] == ["t1"]


def test_live_report_missing_evaluation_invalidates_completed_run(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    _write_task(corpus, "t1")
    _write_run(runs, "t1", "a0", success=None)
    report = _build(runs, corpus, tmp_path)
    cell = report["runs"][0]
    assert cell["analysis_eligible"] is False
    assert cell["invalid_reasons"] == ["missing-evaluation"]


def test_live_report_is_byte_stable(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    _write_task(corpus, "t1")
    for arm, success in (("a0", True), ("a1", False), ("a3", True)):
        _write_run(runs, "t1", arm, success=success)
    left = build_live_report(runs, tmp_path / "left.json", corpus_dir=corpus)
    right = build_live_report(runs, tmp_path / "right.json", corpus_dir=corpus)
    assert left == right
    assert json.loads(left)["report_digest"] == json.loads(right)["report_digest"]


def test_cli_builds_live_report_with_ledger(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    _write_task(corpus, "t1")
    for arm, success in (("a0", False), ("a1", True), ("a3", False)):
        _write_run(runs, "t1", arm, success=success)
    ledger = runs / "ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "cap_usd": 50,
                "committed_cash_usd": 0.768,
                "reserved_cash_usd": 0,
                "available_cash_usd": 49.232,
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    assert main(["report", "build", "--runs", str(runs), "--out", str(out), "--corpus", str(corpus)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["spend"]["ledger"]["committed_cash_usd"] == 0.768
    assert report["spend"]["run_totals"]["runs_with_costs"] == 0


def _write_envelope(runs: Path, task: str, arm: str, *, rep: int = 0, evaluation_digest: str = "") -> None:
    run_id = f"{task}-{arm}-r{rep}"
    envelope = {
        "run_id": run_id,
        "task_id": task,
        "condition_id": arm,
        "arm": arm,
        "evaluation_result_digest": evaluation_digest,
    }
    (runs / run_id / "run-envelope.json").write_text(json.dumps(envelope), encoding="utf-8")


def test_live_report_binds_evaluation_to_envelope(tmp_path: Path) -> None:
    import hashlib

    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    _write_task(corpus, "t1")
    run_dir = _write_run(runs, "t1", "a0", success=True)
    digest = hashlib.sha256((run_dir / "evaluation-result.json").read_bytes()).hexdigest()
    _write_envelope(runs, "t1", "a0", evaluation_digest=digest)

    report = _build(runs, corpus, tmp_path)
    cell = report["runs"][0]
    assert cell["evaluation_digest_checked"] is True
    assert cell["evaluation_digest_match"] is True
    assert cell["analysis_eligible"] is True
    assert report["artifact_integrity"]["evaluation_binding_failures"] == []

    (run_dir / "evaluation-result.json").write_text(
        json.dumps(
            {
                "run_id": "t1-a0-r0",
                "task_success": False,
                "failure_class": "incorrect_implementation",
                "replay_equal": True,
            }
        ),
        encoding="utf-8",
    )
    tampered = _build(runs, corpus, tmp_path)
    cell2 = tampered["runs"][0]
    assert cell2["evaluation_digest_match"] is False
    assert "evaluation-digest-mismatch" in cell2["invalid_reasons"]
    assert cell2["analysis_eligible"] is False
    assert tampered["artifact_integrity"]["evaluation_binding_failures"] == ["t1-a0-r0"]
    statuses = {claim["claim"]: claim["status"] for claim in tampered["claim_map"]}
    assert statuses["retained evaluation artifacts bind to their run envelopes (sha256)"] == "withheld"


def test_live_report_refuses_mock_run_ids(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    _write_task(corpus, "t1")
    _write_run(runs, "t1", "a0", success=True)
    (runs / "t1-a0-r0").rename(runs / "mock-t1-a0-r0")
    (runs / "mock-t1-a0-r0" / "run-record.json").write_text(
        json.dumps(
            {
                "run_id": "mock-t1-a0-r0",
                "task_id": "t1",
                "condition_id": "a0",
                "repetition": 0,
                "terminal_status": "completed",
                "flags": [],
                "trace_coverage": "full",
                "protocol_id": "v1",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ReportRefusal):
        build_live_report(runs, tmp_path / "report.json", corpus_dir=corpus)


def test_live_report_sensitivity_counts_failed_assignments(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus = tmp_path / "corpus"
    _write_task(corpus, "t1")
    _write_run(runs, "t1", "a0", success=True)
    _write_run(runs, "t1", "a1", status="env_failure", success=True)  # leftover passing eval
    _write_run(runs, "t1", "a3", success=True)

    report = _build(runs, corpus, tmp_path)
    assert report["analysis_sets"]["primary"]["tasks"] == []
    sensitivity = report["analysis_sets"]["sensitivity_all_assigned"]
    assert sensitivity["tasks"] == ["t1"]
    a1 = sensitivity["comparisons"]["a1_minus_a0"]
    assert a1["n_tasks"] == 1
    assert a1["ineligible_counted"] == 1
    assert a1["estimate"] == -1.0
    a1_cell = next(cell for cell in report["runs"] if cell["arm"] == "a1")
    assert a1_cell["analysis_eligible"] is False
    assert "terminal_status:env_failure" in a1_cell["invalid_reasons"]
