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
