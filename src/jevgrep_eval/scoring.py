"""Evaluator and metric-registry scoring.

Correctness is determined only by replay-verified patches and frozen tests.
Patch similarity is retained as a diagnostic and is never a success input.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import EvaluationRecord, FailureClass, RetrievalResult, TaskCase
from .retrieval.metrics import RetrievalMetrics, calculate_metrics
from .runner import MalformedPatchError, RunnerError, replay_patch
from .util import canonical_json, digest, digest_bytes, now


class ScoringError(ValueError):
    """An evaluation or metric registry is invalid."""


@dataclass(frozen=True)
class TestExecution:
    passed: bool
    ran: bool
    timed_out: bool = False
    output: bytes = b""


def _command_or_default(command: list[str] | None, default: list[str]) -> list[str]:
    """Use an explicit command when non-empty, preserving legacy defaults."""
    return command if command else default


def build_evaluator_input(
    task: TaskCase,
    patch: bytes,
    hidden_test_patch: Path | None,
    *,
    upstream_command: list[str] | None = None,
    hidden_test_command: list[str] | None = None,
) -> dict[str, Any]:
    """Build the exact evaluator input payload retained by run envelopes."""
    upstream = _command_or_default(upstream_command, task.test_command)
    hidden = _command_or_default(hidden_test_command, task.hidden_test_command or upstream)
    return {
        "base_sha": task.base_sha,
        "patch": patch,
        "hidden_test_digest": (
            digest(hidden_test_patch.read_bytes()) if hidden_test_patch else ""
        ),
        "upstream_slice": upstream,
        "hidden_test_command": hidden,
    }


def _run_tests(argv: list[str], cwd: Path, *, timeout_s: float) -> TestExecution:
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or b""
        if isinstance(output, str):
            output = output.encode()
        return TestExecution(False, True, True, output)
    except OSError as exc:
        return TestExecution(False, False, False, str(exc).encode())
    try:
        output, _ = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        # Reap the direct child and drain both pipe ends after descendants are
        # terminated.  Returning the partial ``TimeoutExpired`` buffer leaves
        # writers alive and makes repeated evaluator runs non-deterministic.
        drained, _ = process.communicate()
        output = drained or exc.stdout or b""
        if isinstance(output, str):
            output = output.encode()
        return TestExecution(False, True, True, output)
    return TestExecution(process.returncode == 0, True, False, output or b"")


def _apply_hidden_patch(workspace: Path, hidden_patch: Path | None) -> None:
    if hidden_patch is None:
        return
    if not hidden_patch.is_file():
        raise ScoringError(f"hidden test patch is missing: {hidden_patch}")
    try:
        environment = os.environ.copy()
        environment["GIT_CEILING_DIRECTORIES"] = str(workspace.parent.resolve())
        completed = subprocess.run(
            ["git", "apply", "--binary", "--whitespace=nowarn", str(hidden_patch)],
            cwd=workspace,
            capture_output=True,
            check=False,
            env=environment,
        )
    except OSError as exc:
        raise ScoringError(f"cannot apply hidden test patch: {exc}") from exc
    if completed.returncode:
        raise ScoringError(
            f"hidden test patch rejected: {completed.stderr.decode('utf-8', errors='replace')}"
        )


def evaluate(
    task: TaskCase,
    base_workspace: Path,
    patch: bytes,
    destination: Path,
    *,
    run_id: str | None = None,
    hidden_test_patch: Path | None = None,
    upstream_command: list[str] | None = None,
    hidden_test_command: list[str] | None = None,
    timeout_s: float | None = None,
    run_timeout: bool = False,
) -> EvaluationRecord:
    """Evaluate a patch in a fresh evaluator workspace."""
    if destination.exists():
        raise ScoringError(f"evaluation destination already exists: {destination}")
    try:
        replay_patch(base_workspace, patch, destination)
    except (MalformedPatchError, RunnerError, OSError, ValueError) as exc:
        return EvaluationRecord(
            run_id=run_id or task.task_id,
            task_success=False,
            failure_class=FailureClass.MALFORMED_PATCH,
            hidden_passed=False,
            upstream_passed=False,
            replay_equal=False,
            patch_digest=digest_bytes(patch),
            evaluator_input_digest="",
            tested_at=now(),
            stdout_digest=digest_bytes(str(exc).encode()),
        )
    evaluator_payload = build_evaluator_input(
        task,
        patch,
        hidden_test_patch,
        upstream_command=upstream_command,
        hidden_test_command=hidden_test_command,
    )
    # Keep the digest equal to the bytes retained in the run envelope.  The
    # payload itself carries the schema/version through canonical_json.
    evaluator_input_digest = digest_bytes(canonical_json(evaluator_payload))
    upstream = evaluator_payload["upstream_slice"]
    hidden = evaluator_payload["hidden_test_command"]
    if not upstream and not hidden:
        return EvaluationRecord(
            run_id=run_id or task.task_id,
            task_success=False,
            failure_class=FailureClass.TESTS_NOT_RUN,
            hidden_passed=False,
            upstream_passed=False,
            replay_equal=True,
            patch_digest=digest_bytes(patch),
            evaluator_input_digest=evaluator_input_digest,
            tested_at=now(),
        )
    timeout = timeout_s or max(task.expected_test_seconds * 2, 30.0)
    with tempfile.TemporaryDirectory(
        prefix="jevgrep-evaluator-upstream-",
        dir=str(destination.parent),
    ) as upstream_name:
        upstream_destination = Path(upstream_name) / "workspace"
        try:
            replay_patch(base_workspace, patch, upstream_destination)
        except (MalformedPatchError, RunnerError, OSError, ValueError) as exc:
            return EvaluationRecord(
                run_id=run_id or task.task_id,
                task_success=False,
                failure_class=FailureClass.MALFORMED_PATCH,
                hidden_passed=False,
                upstream_passed=False,
                replay_equal=False,
                patch_digest=digest_bytes(patch),
                evaluator_input_digest=evaluator_input_digest,
                tested_at=now(),
                stdout_digest=digest_bytes(str(exc).encode()),
            )
        upstream_result = (
            _run_tests(upstream, upstream_destination, timeout_s=timeout)
            if upstream
            else TestExecution(False, False, output=b"upstream command not configured")
        )
    try:
        _apply_hidden_patch(destination, hidden_test_patch)
    except ScoringError as exc:
        return EvaluationRecord(
            run_id=run_id or task.task_id,
            task_success=False,
            failure_class=FailureClass.TESTS_NOT_RUN,
            hidden_passed=False,
            upstream_passed=upstream_result.passed,
            replay_equal=True,
            patch_digest=digest_bytes(patch),
            evaluator_input_digest=evaluator_input_digest,
            tested_at=now(),
            stdout_digest=digest_bytes(str(exc).encode()),
        )
    hidden_result = (
        _run_tests(hidden, destination, timeout_s=timeout)
        if hidden
        else TestExecution(False, False, output=b"hidden test command not configured")
    )
    failure: FailureClass | None = None
    if run_timeout or upstream_result.timed_out or hidden_result.timed_out:
        failure = FailureClass.TIMEOUT
    elif not upstream_result.ran or not hidden_result.ran:
        failure = FailureClass.ENV_FAILURE
    elif not upstream_result.passed:
        failure = FailureClass.REGRESSION
    elif not hidden_result.passed:
        failure = (
            FailureClass.LOCALIZATION
            if not patch
            else FailureClass.INCORRECT_IMPLEMENTATION
        )
    success = (
        upstream_result.ran
        and upstream_result.passed
        and hidden_result.ran
        and hidden_result.passed
        and failure is None
    )
    output = upstream_result.output + b"\n" + hidden_result.output
    return EvaluationRecord(
        run_id=run_id or task.task_id,
        task_success=success,
        failure_class=failure,
        hidden_passed=hidden_result.passed,
        upstream_passed=upstream_result.passed,
        replay_equal=True,
        patch_digest=digest_bytes(patch),
        evaluator_input_digest=evaluator_input_digest,
        tested_at=now(),
        stdout_digest=digest_bytes(output),
    )


def task_success(
    hidden_passed: bool,
    upstream_passed: bool,
    *,
    replay_equal: bool,
) -> bool:
    return bool(hidden_passed and upstream_passed and replay_equal)


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    population: str
    numerator: str
    denominator: str
    source: str
    missing_data_rule: str
    interpretation: str


@dataclass(frozen=True)
class MetricRegistry:
    definitions: tuple[MetricDefinition, ...]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(item.name for item in self.definitions)


def load_metric_registry(path: Path) -> MetricRegistry:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ScoringError(f"cannot load metric registry: {exc}") from exc
    rows = payload.get("metrics", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ScoringError("metric registry must contain a metrics list")
    definitions: list[MetricDefinition] = []
    required = (
        "name",
        "population",
        "numerator",
        "denominator",
        "source",
        "missing_data_rule",
        "interpretation",
    )
    for row in rows:
        if not isinstance(row, dict):
            raise ScoringError("metric registry entry must be a mapping")
        missing = [field for field in required if not row.get(field)]
        if missing:
            raise ScoringError(f"metric registry entry missing: {', '.join(missing)}")
        definitions.append(
            MetricDefinition(**{field: str(row[field]) for field in required})
        )
    return MetricRegistry(tuple(definitions))


def verify_emitted_metrics(emitted: dict[str, Any], registry: MetricRegistry) -> None:
    unknown = set(emitted) - registry.names
    uncovered = registry.names - set(emitted)
    if unknown:
        raise ScoringError(f"unknown emitted metrics: {sorted(unknown)}")
    if uncovered:
        raise ScoringError(f"registry entries not emitted: {sorted(uncovered)}")


def score_retrieval(
    result: RetrievalResult,
    reference_files: Iterable[str],
    *,
    evidence_files: Iterable[str] = (),
    base_present: Iterable[str] | None = None,
) -> RetrievalMetrics:
    return calculate_metrics(
        result,
        reference_files,
        evidence_files=evidence_files,
        base_present=base_present,
    )


def retrieval_metrics(
    result: RetrievalResult,
    reference_files: Iterable[str],
    evidence_files: Iterable[str] = (),
) -> RetrievalMetrics:
    """Compatibility name for the retrieval-only scorer."""
    return score_retrieval(result, reference_files, evidence_files=evidence_files)


def patch_similarity(patch: bytes, gold_patch: bytes) -> float:
    """Return a diagnostic byte similarity; never used by ``evaluate``."""
    if not patch and not gold_patch:
        return 1.0
    if not patch or not gold_patch:
        return 0.0
    same = sum(left == right for left, right in zip(patch, gold_patch))
    return same / max(len(patch), len(gold_patch))


class Evaluator:
    """Facade for evaluator-side patch replay and frozen-test execution."""

    def __init__(self, *, timeout_s: float = 120) -> None:
        self.timeout_s = timeout_s

    def evaluate(
        self,
        task: TaskCase,
        base_workspace: Path,
        patch: bytes,
        destination: Path,
        *,
        hidden_test_patch: Path | None = None,
        hidden_test_command: list[str] | None = None,
        upstream_command: list[str] | None = None,
        run_id: str | None = None,
    ) -> EvaluationRecord:
        return evaluate(
            task,
            base_workspace,
            patch,
            destination,
            run_id=run_id,
            hidden_test_patch=hidden_test_patch,
            hidden_test_command=hidden_test_command,
            upstream_command=upstream_command,
            timeout_s=self.timeout_s,
        )


evaluate_patch = evaluate
