from datetime import UTC, datetime

import pytest

from jevgrep_eval.models import RunState
from jevgrep_eval.runner import RunLifecycle, Runner, RunnerError, run_command


def test_stage_order_and_invalid_transition():
    lifecycle = RunLifecycle("run")
    lifecycle.transition(RunState.PREPARED, datetime.now(UTC), "p")
    lifecycle.transition(RunState.RUNNING, datetime.now(UTC), "p")
    with pytest.raises(RunnerError):
        lifecycle.transition(RunState.RECORDED, datetime.now(UTC), "p")


def test_timeout_reaps_process_group():
    with pytest.raises(TimeoutError):
        run_command(["python3", "-c", "import time; time.sleep(10)"], ".", timeout_s=0.01)


def test_runner_plumbs_task_hidden_test_command(
    task_case,
    mini_tree,
    tmp_path,
):
    task = task_case.model_copy(
        update={
            "hidden_test_command": [
                "python3",
                "-c",
                "raise SystemExit(3)",
            ]
        }
    )
    record = Runner(timeout_s=5).run(
        run_id="hidden-command",
        task_id=task.task_id,
        condition_id="a0",
        workspace=mini_tree,
        argv=["python3", "-c", "raise SystemExit(0)"],
        task=task,
        artifact_dir=tmp_path / "artifacts",
    )

    assert not record.task_success


def test_timeout_retains_partial_stdout(tmp_path):
    """A killed run must not lose its trace: partial stdout is drained and retained."""
    partial = tmp_path / "agent-stdout.jsonl"
    emitter = (
        "import json,time;"
        "print(json.dumps({'type':'item.completed','item':{'id':'i1',"
        "'type':'command_execution','command':'ls','status':'completed','exit_code':0}}), flush=True);"
        "time.sleep(30)"
    )
    with pytest.raises(TimeoutError):
        run_command(
            ["python3", "-c", emitter],
            ".",
            timeout_s=0.8,
            partial_stdout_path=partial,
        )
    assert partial.is_file()
    assert "item.completed" in partial.read_text(encoding="utf-8")


def test_timeout_run_parses_partial_trace(mini_tree, tmp_path):
    """Timeout runs keep their parsed events via the retained partial stream."""
    emitter = (
        "import json,time;"
        "print(json.dumps({'type':'item.completed','item':{'id':'i1',"
        "'type':'command_execution','command':'ls','status':'completed','exit_code':0}}), flush=True);"
        "time.sleep(30)"
    )
    record = Runner(timeout_s=1).run(
        run_id="timeout-trace",
        task_id="click-3533",
        condition_id="a0",
        workspace=mini_tree,
        argv=["python3", "-c", emitter],
        artifact_dir=tmp_path / "artifacts",
    )
    assert record.terminal_status is not None
    assert record.terminal_status.value == "timeout"
    assert len(record.events) >= 1
    assert (tmp_path / "artifacts" / "agent-stdout.jsonl").is_file()


def test_forced_first_none_is_not_a_forced_arm(mini_tree, tmp_path):
    """The condition model default is "none"; it must not trigger discovery flags.

    Live regression: a0 (`forced_first: none`) carried `indeterminate-discovery`
    because the YAML string "none" is truthy in the runner's forced-first block.
    """
    record = Runner(timeout_s=30).run(
        run_id="ff-none",
        task_id="click-3533",
        condition_id="a0",
        workspace=mini_tree,
        argv=["python3", "-c", "print('hello')"],
        forced_first="none",
        artifact_dir=tmp_path / "artifacts",
    )
    assert "indeterminate-discovery" not in record.flags
    assert "noncompliant" not in record.flags


def test_runner_retains_stdout_and_trace_diagnostics(mini_tree, tmp_path):
    """The stdout stream (trace source of truth) and coverage reasons are retained."""
    record = Runner(timeout_s=30).run(
        run_id="stdout-retained",
        task_id="click-3533",
        condition_id="a0",
        workspace=mini_tree,
        argv=["python3", "-c", "print('hello')"],
        artifact_dir=tmp_path / "artifacts",
    )
    assert (tmp_path / "artifacts" / "agent-stdout.jsonl").read_text(encoding="utf-8") == "hello\n"
    assert record.trace_coverage == "partial"
    assert record.trace_missing  # diagnostics retained for coverage decisions
    assert record.trace_errors


def test_timeout_bounded_when_descendant_escapes_process_group(tmp_path):
    """A setsid'd descendant holding stdout must not wedge run_command after the kill."""
    import os
    import signal
    import time

    desc_pid_file = tmp_path / "descendant.pid"
    partial = tmp_path / "agent-stdout.jsonl"
    code = (
        "import subprocess, time\n"
        "subprocess.Popen(['setsid', 'bash', '-c', 'echo $$ > "
        + str(desc_pid_file)
        + "; exec sleep 30'])\n"
        "print('partial-line', flush=True)\n"
        "time.sleep(30)\n"
    )
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run_command(["python3", "-c", code], ".", timeout_s=0.8, partial_stdout_path=partial)
    elapsed = time.monotonic() - started
    assert elapsed < 8.0, f"run_command wedged {elapsed:.1f}s on an escaped pipe holder"
    assert partial.is_file()
    pid = int(desc_pid_file.read_text())
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_timeout_bounded_when_child_ignores_sigterm():
    import time

    code = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run_command(["python3", "-c", code], ".", timeout_s=0.5)
    assert time.monotonic() - started < 8.0
