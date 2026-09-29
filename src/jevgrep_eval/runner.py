"""Run lifecycle, private patch capture, replay, and process handling."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from .envelope import (
    add_component,
    append_transition,
    create_envelope,
    envelope_digest,
    save_envelope,
)
from .materialize import (
    WORKSPACE_EXCLUDED_NAMES,
    MaterializationError,
    is_benchmark_metadata_path,
    snapshot,
)
from .models import (
    EvaluationRecord,
    FailureClass,
    RunRecord,
    RunState,
    StageRecord,
    TaskCase,
    TerminalStatus,
    WorkspaceManifest,
)
from .traces import derive_metrics
from .traces_codex import parse_trace
from .util import canonical_json, digest, digest_bytes, normalize_path, now


class RunnerError(RuntimeError):
    """A run cannot proceed safely."""


class MalformedPatchError(RunnerError):
    """The post-run tree cannot be represented or safely replayed."""


@dataclass(frozen=True)
class PatchCapture:
    patch: bytes
    digest: str
    before: WorkspaceManifest
    after: WorkspaceManifest
    replay_equal: bool
    empty: bool


def _safe_paths(root: Path, *, allowed_paths: set[str] | None = None) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in WORKSPACE_EXCLUDED_NAMES for part in relative.parts):
            continue
        if is_benchmark_metadata_path(relative):
            raise MalformedPatchError(f"benchmark metadata path: {relative}")
        normalized = normalize_path(relative.as_posix())
        if path.is_symlink() and path.resolve() != root and root not in path.resolve().parents:
            raise MalformedPatchError(f"escaping symlink: {relative}")
        if not path.is_file() and not path.is_symlink():
            if not path.is_dir():
                raise MalformedPatchError(f"special file: {relative}")
            if allowed_paths is not None and not any(
                allowed == normalized or allowed.startswith(f"{normalized}/")
                for allowed in allowed_paths
            ):
                continue
            continue
        if allowed_paths is not None and normalized not in allowed_paths:
            raise MalformedPatchError(f"path is outside policy: {normalized}")
        paths.append(path)
    return paths


def _tree_bytes(root: Path, *, allowed_paths: set[str] | None = None) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in _safe_paths(root, allowed_paths=allowed_paths):
        relative = path.relative_to(root).as_posix()
        result[relative] = path.read_bytes() if not path.is_symlink() else os.readlink(path).encode()
    return result


def _copy_tree(
    source: Path,
    destination: Path,
    *,
    root: Path | None = None,
    excluded: frozenset[str] | None = None,
) -> None:
    root = source if root is None else root
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir(), key=lambda path: path.name):
        relative = item.relative_to(root)
        if is_benchmark_metadata_path(relative):
            continue
        if excluded is not None and any(part in excluded for part in relative.parts):
            continue
        target = destination / item.name
        if item.is_symlink():
            target.symlink_to(os.readlink(item))
        elif item.is_dir():
            _copy_tree(item, target, root=root, excluded=excluded)
            target.chmod(item.stat().st_mode & 0o7777)
        elif item.is_file():
            target.write_bytes(item.read_bytes())
            target.chmod(item.stat().st_mode & 0o7777)
        else:
            raise MalformedPatchError(f"special file: {item}")


def _remove_worktree_contents(root: Path) -> None:
    """Remove only entries in a fresh private worktree, without recursion."""
    files: list[Path] = []
    directories: list[Path] = []
    for path in root.rglob("*"):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_dir() and not path.is_symlink():
            directories.append(path)
        else:
            files.append(path)
    for path in sorted(files, key=lambda value: len(value.parts), reverse=True):
        path.unlink()
    for path in sorted(directories, key=lambda value: len(value.parts), reverse=True):
        path.rmdir()


def _git(
    argv: list[str],
    cwd: Path,
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        environment = os.environ.copy()
        environment["GIT_CEILING_DIRECTORIES"] = str(cwd.parent.resolve())
        return subprocess.run(
            argv,
            cwd=cwd,
            input=input_bytes,
            capture_output=True,
            check=check,
            timeout=120,
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RunnerError(f"git operation failed: {exc}") from exc


def _validate_policy(root: Path, allowed_paths: set[str] | None) -> None:
    _safe_paths(root, allowed_paths=allowed_paths)


def capture_patch(
    before_root: Path,
    after_root: Path,
    *,
    allowed_paths: Iterable[str] | None = None,
) -> PatchCapture:
    """Capture a staged git binary diff in a private scratch repository."""
    allowed = {normalize_path(path) for path in allowed_paths} if allowed_paths is not None else None
    try:
        before = snapshot(before_root)
        after = snapshot(after_root)
    except MaterializationError as exc:
        raise MalformedPatchError(str(exc)) from exc
    _validate_policy(before_root, allowed)
    _validate_policy(after_root, allowed)
    with tempfile.TemporaryDirectory(prefix="jevgrep-patch-", dir=str(after_root.parent)) as scratch_name:
        scratch = Path(scratch_name)
        repo = scratch / "repo"
        repo.mkdir()
        _git(["git", "init", "--quiet"], repo)
        _git(["git", "config", "user.name", "jevgrep-eval"], repo)
        _git(["git", "config", "user.email", "engine@invalid"], repo)
        _copy_tree(before_root, repo, excluded=WORKSPACE_EXCLUDED_NAMES)
        _git(["git", "add", "-A", "-f", "."], repo)
        _git(["git", "commit", "--quiet", "--allow-empty", "-m", "pre-snapshot"], repo)
        _remove_worktree_contents(repo)
        _copy_tree(after_root, repo, excluded=WORKSPACE_EXCLUDED_NAMES)
        # --force: the scratch view is defined by WORKSPACE_EXCLUDED_NAMES, not by the
        # project's own .gitignore. Without it, an ignored file that changed during the
        # run would be present post-run but absent from the patch, and patch replay
        # would diverge from the post-run tree.
        _git(["git", "add", "-A", "-f", "."], repo)
        result = _git(
            ["git", "diff", "--cached", "--binary", "--full-index"],
            repo,
            check=True,
        )
        patch = result.stdout
        replay_dir = scratch / "replay"
        replay = replay_patch(before_root, patch, replay_dir)
        replay_equal = _manifest_files(replay) == _manifest_files(after)
    if not replay_equal:
        raise MalformedPatchError("patch replay does not equal post-run tree")
    return PatchCapture(patch, digest_bytes(patch), before, after, replay_equal, not patch)


def _manifest_files(manifest: WorkspaceManifest) -> list[dict[str, object]]:
    return [
        entry.model_dump(mode="json")
        for entry in manifest.files
        if entry.file_type != "directory"
    ]


def replay_patch(base_root: Path, patch: bytes, destination: Path) -> WorkspaceManifest:
    """Replay a captured patch onto a fresh base tree."""
    if destination.exists():
        raise RunnerError("replay destination already exists")
    _copy_tree(base_root, destination)
    if patch:
        _git(["git", "apply", "--binary", "--whitespace=nowarn", "-"], destination, input_bytes=patch)
    return snapshot(destination)


class RunLifecycle:
    """Enforce the monotonic PREPARED→RECORDED state machine."""

    _order: ClassVar[list[RunState]] = list(RunState)

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.state: RunState | None = None
        self.records: list[StageRecord] = []

    def transition(
        self,
        state: RunState,
        at: object,
        parent_digest: str,
        *,
        jsonl_path: Path | None = None,
        terminal_status: TerminalStatus | None = None,
    ) -> StageRecord:
        if self.state is not None and self._order.index(state) != self._order.index(self.state) + 1:
            raise RunnerError(f"invalid transition {self.state} -> {state}")
        unsigned = StageRecord(
            run_id=self.run_id,
            from_state=self.state,
            to_state=state,
            at=at,
            parent_digest=parent_digest,
            record_digest="pending",
            terminal_status=terminal_status,
        )
        record = unsigned.model_copy(
            update={"record_digest": digest(unsigned.model_dump(mode="json"), component="stage-record")}
        )
        if jsonl_path is not None:
            append_stage_record(jsonl_path, record)
        self.records.append(record)
        self.state = state
        return record

    def complete(
        self,
        terminal: str,
        at: object | None = None,
        *,
        parent_digest: str = "",
        jsonl_path: Path | None = None,
    ) -> str:
        """Record a terminal outcome without pretending it is a state."""
        if terminal not in {"completed", "timeout", "env_failure", "malformed_patch"}:
            raise RunnerError(f"unknown terminal status: {terminal}")
        if self.state != RunState.RECORDED:
            self.transition(
                RunState.RECORDED,
                at or now(),
                parent_digest or (self.records[-1].record_digest if self.records else ""),
                jsonl_path=jsonl_path,
                terminal_status=TerminalStatus(terminal),
            )
        return terminal


def append_stage_record(path: Path, record: StageRecord) -> None:
    """Append one immutable canonical JSONL stage record atomically."""
    payload = canonical_json(record.model_dump(mode="json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def quiescent_snapshot(
    root: Path,
    *,
    settle_s: float = 0.01,
) -> tuple[WorkspaceManifest, WorkspaceManifest, bool]:
    """Hash around a settled snapshot and require repeated stable observations."""
    first = snapshot(root)
    if settle_s > 0:
        time.sleep(settle_s)
    second = snapshot(root)
    if settle_s > 0:
        time.sleep(settle_s)
    settled = snapshot(root)
    return first, settled, (
        first.workspace_digest == second.workspace_digest == settled.workspace_digest
    )


def run_command(
    argv: list[str],
    cwd: Path,
    *,
    timeout_s: float,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a command and kill its process group on timeout."""
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        raise TimeoutError(f"command exceeded {timeout_s}s") from exc
    elapsed = time.monotonic() - started
    del elapsed
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


class Runner:
    """Execute one attempt through the frozen runner state machine."""

    def __init__(self, *, timeout_s: float = 600) -> None:
        self.timeout_s = timeout_s

    def run(
        self,
        *,
        run_id: str,
        task_id: str,
        condition_id: str,
        workspace: Path,
        argv: list[str],
        repetition: int = 0,
        timeout_s: float | None = None,
        allowed_paths: Iterable[str] | None = None,
        stage_log: Path | None = None,
        env: dict[str, str] | None = None,
        artifact_dir: Path | None = None,
        task: Any | None = None,
        fixture_manifest: Any | None = None,
        statement: str = "",
        prompt_common: Any = "",
        prompt_fragment: Any = "",
        skill_bytes: bytes | str = b"",
        invocation: Any | None = None,
        requested_model: str = "",
        resolved_model: str = "",
        effort: str = "",
        forced_first: str | None = None,
        retry_on_env_failure: bool = False,
        resume: bool = False,
        hidden_test_patch: Path | None = None,
        hidden_test_command: list[str] | None = None,
        upstream_command: list[str] | None = None,
    ) -> RunRecord:
        if not workspace.is_dir():
            raise RunnerError(f"workspace is not a directory: {workspace}")
        if artifact_dir is None:
            artifact_dir = workspace.parent / ".jevgrep-runs" / run_id
        if resume and (artifact_dir / "run-record.json").is_file():
            return RunRecord.model_validate_json((artifact_dir / "run-record.json").read_bytes())
        lifecycle = RunLifecycle(run_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        before, _, before_quiescent = quiescent_snapshot(workspace)
        envelope = create_envelope(
            run_id=run_id,
            task_id=task_id,
            condition_id=condition_id,
            task=task if task is not None else {"task_id": task_id},
            fixture_manifest=(
                fixture_manifest
                if fixture_manifest is not None
                else {"workspace_digest": before.workspace_digest}
            ),
            statement=statement,
            prompt_common=prompt_common,
            prompt_fragment=prompt_fragment,
            skill_bytes=skill_bytes,
            invocation=invocation if invocation is not None else {"argv": argv},
            pre_workspace=before.model_dump(mode="json"),
            requested_model=requested_model,
            resolved_model=resolved_model,
            effort=effort,
        )
        envelope = append_transition(envelope, RunState.PREPARED, now())
        envelope = append_transition(envelope, RunState.RUNNING, now())
        with tempfile.TemporaryDirectory(
            prefix="jevgrep-run-base-", dir=str(workspace.parent)
        ) as base_name:
            base = Path(base_name)
            _copy_tree(workspace, base)
            lifecycle.transition(
                RunState.PREPARED,
                now(),
                before.workspace_digest,
                jsonl_path=stage_log,
            )
            timeout = timeout_s or self.timeout_s
            terminal = TerminalStatus.COMPLETED
            failure: FailureClass | None = None
            completed: subprocess.CompletedProcess[str] | None = None
            captured: PatchCapture | None = None
            evaluation: EvaluationRecord | None = None
            try:
                lifecycle.transition(
                    RunState.RUNNING,
                    now(),
                    lifecycle.records[-1].record_digest,
                    jsonl_path=stage_log,
                )
                completed = run_command(argv, workspace, timeout_s=timeout, env=env)
                if completed.returncode != 0:
                    terminal = TerminalStatus.ENV_FAILURE
                    failure = FailureClass.ENV_FAILURE
            except TimeoutError:
                terminal = TerminalStatus.TIMEOUT
                failure = FailureClass.TIMEOUT
            except OSError:
                terminal = TerminalStatus.ENV_FAILURE
                failure = FailureClass.ENV_FAILURE
            lifecycle.transition(
                RunState.SNAPSHOT,
                now(),
                lifecycle.records[-1].record_digest,
                jsonl_path=stage_log,
            )
            try:
                _first, second, quiescent = quiescent_snapshot(workspace)
                if not quiescent and terminal == TerminalStatus.COMPLETED:
                    terminal = TerminalStatus.MALFORMED_PATCH
                    failure = FailureClass.MALFORMED_PATCH
                captured = capture_patch(base, workspace, allowed_paths=allowed_paths)
                if not captured.replay_equal and terminal == TerminalStatus.COMPLETED:
                    terminal = TerminalStatus.MALFORMED_PATCH
                    failure = FailureClass.MALFORMED_PATCH
                post_digest = second.workspace_digest
                patch_digest = captured.digest
                envelope = add_component(
                    envelope,
                    "post_workspace_digest",
                    second.model_dump(mode="json"),
                )
                envelope = add_component(envelope, "patch_digest", captured.patch)
            except (MalformedPatchError, RunnerError):
                if terminal == TerminalStatus.COMPLETED:
                    terminal = TerminalStatus.MALFORMED_PATCH
                    failure = FailureClass.MALFORMED_PATCH
                post_digest = ""
                patch_digest = ""
            if (
                captured is not None
                and isinstance(task, TaskCase)
                and (
                    hidden_test_patch is not None
                    or bool(task.hidden_test_command)
                    or bool(hidden_test_command)
                )
            ):
                from .scoring import build_evaluator_input, evaluate

                evaluation_destination = artifact_dir / "evaluation-workspace"
                evaluation = evaluate(
                    task,
                    base,
                    captured.patch,
                    evaluation_destination,
                    run_id=run_id,
                    hidden_test_patch=hidden_test_patch,
                    hidden_test_command=hidden_test_command,
                    upstream_command=upstream_command,
                    timeout_s=timeout,
                )
                if not evaluation.task_success and terminal == TerminalStatus.COMPLETED:
                    failure = evaluation.failure_class or FailureClass.INCORRECT_IMPLEMENTATION
                envelope = add_component(
                    envelope,
                    "evaluator_input_digest",
                    build_evaluator_input(
                        task,
                        captured.patch,
                        hidden_test_patch,
                        upstream_command=upstream_command,
                        hidden_test_command=hidden_test_command,
                    ),
                )
                envelope = add_component(
                    envelope,
                    "evaluation_result_digest",
                    evaluation.model_dump(mode="json"),
                )
                (artifact_dir / "evaluation-result.json").write_bytes(
                    canonical_json(evaluation.model_dump(mode="json"))
                )
            lifecycle.transition(
                RunState.EVALUATED,
                now(),
                lifecycle.records[-1].record_digest,
                jsonl_path=stage_log,
            )
            lifecycle.complete(
                terminal.value,
                now(),
                parent_digest=lifecycle.records[-1].record_digest,
                jsonl_path=stage_log,
            )
        if completed is not None and completed.stdout:
            # The stdout stream is the trace source of truth for this run; retain it beside
            # the record so coverage can be re-derived or audited without replaying the run.
            (artifact_dir / "agent-stdout.jsonl").write_text(completed.stdout, encoding="utf-8")
        if completed is None:
            trace_parse = parse_trace(())
        else:
            trace_parse = parse_trace(completed.stdout.splitlines(), str(workspace))
        events = list(trace_parse.events)
        flags: list[str] = []
        simulated = (
            (env or {}).get("JEVGREP_EVAL_SIMULATED") == "1"
            or (argv and Path(argv[0]).name in {"mock", "mock-agent", "mock-harness"})
        )
        if simulated:
            flags.append("simulated-fixture")
        if not before_quiescent:
            flags.append("pre-snapshot-mutated")
        if trace_parse.coverage == "partial":
            flags.append("trace-partial")
        if forced_first and forced_first != "none":
            trace_metrics = derive_metrics(
                events,
                set(),
                coverage=trace_parse.coverage,
                missing_dimensions=trace_parse.missing_dimensions,
            )
            if trace_metrics.first_discovery_operation == "indeterminate":
                flags.append("indeterminate-discovery")
            elif trace_metrics.first_discovery_operation is not None:
                first_event = events[int(trace_metrics.first_discovery_operation)]
                expected_kind = {
                    "jg": "search_jg",
                    "bm25": "search_bm25",
                }.get(forced_first)
                if expected_kind and first_event.kind.value != expected_kind:
                    flags.append("noncompliant")
        envelope = append_transition(envelope, RunState.SNAPSHOT, now())
        envelope = append_transition(envelope, RunState.EVALUATED, now())
        envelope = append_transition(
            envelope,
            RunState.RECORDED,
            now(),
            terminal_status=terminal,
        )
        tree_hash = digest(
            {
                "pre_workspace_digest": before.workspace_digest,
                "post_workspace_digest": post_digest,
                "patch_digest": patch_digest,
            },
            component="tree",
        )
        record = RunRecord(
            run_id=run_id,
            task_id=task_id,
            condition_id=condition_id,
            repetition=repetition,
            state=RunState.RECORDED,
            terminal_status=terminal,
            error=failure,
            task_success=(
                evaluation.task_success
                if evaluation is not None and terminal == TerminalStatus.COMPLETED
                else terminal == TerminalStatus.COMPLETED
            ),
            trace_coverage=trace_parse.coverage,
            tree_hash=tree_hash,
            envelope_digest=envelope_digest(envelope),
            pre_workspace_digest=before.workspace_digest,
            post_workspace_digest=post_digest,
            workspace_digest=post_digest,
            patch_digest=patch_digest,
            events=events,
            stage_records=lifecycle.records,
            created_at=now(),
            finished_at=now(),
            flags=flags,
            trace_missing=list(trace_parse.missing_dimensions),
            trace_errors=list(trace_parse.errors),
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)
        save_envelope(envelope, artifact_dir / "run-envelope.json")
        (artifact_dir / "run-record.json").write_bytes(
            canonical_json(record.model_dump(mode="json"))
        )
        if retry_on_env_failure and failure == FailureClass.ENV_FAILURE:
            return self.run(
                run_id=f"{run_id}.retry1",
                task_id=task_id,
                condition_id=condition_id,
                workspace=workspace,
                argv=argv,
                repetition=repetition,
                timeout_s=timeout_s,
                allowed_paths=allowed_paths,
                stage_log=stage_log,
                env=env,
                artifact_dir=artifact_dir.parent / f"{run_id}.retry1",
                task=task,
                fixture_manifest=fixture_manifest,
                statement=statement,
                prompt_common=prompt_common,
                prompt_fragment=prompt_fragment,
                skill_bytes=skill_bytes,
                invocation=invocation,
                requested_model=requested_model,
                resolved_model=resolved_model,
                effort=effort,
                forced_first=forced_first,
                retry_on_env_failure=False,
                resume=False,
                hidden_test_patch=hidden_test_patch,
                hidden_test_command=hidden_test_command,
                upstream_command=upstream_command,
            )
        return record


snapshot_tree = snapshot
execute_command = run_command
quiescence_proof = quiescent_snapshot
RunnerStateMachine = RunLifecycle
