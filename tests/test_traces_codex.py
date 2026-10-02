import json
from pathlib import Path

import pytest

from jevgrep_eval.models import EventKind
from jevgrep_eval.traces import classify_command, derive_metrics, unwrap_shell_call
from jevgrep_eval.traces_codex import (
    parse_codex_rollout,
    parse_codex_stream,
    parse_trace,
)

FIXTURES = Path(__file__).parent / "fixtures" / "codex-0.157.1"


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def test_stream_fixture_is_fully_normalized():
    parsed = parse_codex_stream(_lines("fixture-exec-stream.jsonl"))

    assert parsed.coverage == "full"
    assert parsed.provider_meta["session_id"] == "01a0edc4-8880-7ec3-b298-67d53f2aa7fb"
    assert len(parsed.events) == 1
    event = parsed.events[0]
    assert event.kind == EventKind.EDIT
    assert event.exit_code == 0
    assert event.cmd_digest == "e16ac21e6a4ec50c4da39c3a6d0fd7f28a265a027d9dfc906f0372478f8f7e10"
    assert parsed.provider_meta["usage"]["total_tokens"] == 37191
    assert parsed.provider_meta["rate_limits"] is None


def test_rollout_fixture_a_is_fully_normalized():
    parsed = parse_codex_rollout(_lines("fixture-route-a.jsonl"))

    assert parsed.coverage == "full"
    assert parsed.missing_dimensions == ()
    assert parsed.provider_meta["session_id"] == "01a0edc1-4601-7430-8ead-14bc3e0f8859"
    assert parsed.provider_meta["cli_version"] == "0.157.1"
    assert parsed.provider_meta["model_provider"] == "openai"
    assert parsed.provider_meta["model"] == {"resolved": "gpt-6-luna", "effort": "max"}
    assert parsed.provider_meta["usage"]["input_tokens"] == 39577
    assert parsed.provider_meta["usage"]["total_tokens"] == 39803
    assert parsed.provider_meta["rate_limits"]["secondary"]["used_percent"] == 15.0
    assert len(parsed.events) == 1
    assert parsed.events[0].kind == EventKind.EDIT
    assert parsed.events[0].exit_code == 0
    assert parsed.events[0].cmd_digest == "7e2aed91f358d2ef606f4db9329b2a55569989faa1d1100514769553e06ca141"
    assert len(parsed.token_count_records) >= 2


def test_rollout_fixture_b_has_the_same_route_schema():
    parsed = parse_codex_rollout(_lines("fixture-route-b.jsonl"))

    assert parsed.coverage == "full"
    assert parsed.missing_dimensions == ()
    assert parsed.provider_meta["session_id"] == "01a0edc2-1809-7891-b67c-1c9d99cf1297"
    assert parsed.provider_meta["usage"]["total_tokens"] == 37067
    assert len(parsed.events) == 1
    assert parsed.events[0].kind == EventKind.EDIT
    assert parsed.events[0].exit_code == 0
    assert parsed.events[0].cmd_digest == "7e2aed91f358d2ef606f4db9329b2a55569989faa1d1100514769553e06ca141"
    assert len(parsed.token_count_records) >= 2


@pytest.mark.parametrize(
    "name",
    ["fixture-route-a.jsonl", "fixture-route-b.jsonl"],
)
def test_known_non_tool_rollout_records_do_not_degrade_coverage(name: str):
    parsed = parse_codex_rollout(_lines(name))

    assert parsed.coverage == "full"
    assert parsed.missing_dimensions == ()


def test_partial_stream_without_terminal_marker():
    parsed = parse_codex_stream(_lines("fixture-exec-stream.jsonl")[:-1])

    assert parsed.coverage == "partial"
    assert "terminal_marker" in parsed.missing_dimensions


def test_partial_rollout_retains_unknown_record():
    lines = [*_lines("fixture-route-a.jsonl"), '{"type":"mystery_thing","payload":{}}']
    parsed = parse_codex_rollout(lines)

    assert parsed.coverage == "partial"
    assert "known_event_types" in parsed.missing_dimensions
    assert any("mystery_thing" in error for error in parsed.errors)


@pytest.mark.parametrize(
    ("parser", "name"),
    [
        (parse_codex_stream, "fixture-exec-stream.jsonl"),
        (parse_codex_rollout, "fixture-route-a.jsonl"),
    ],
)
def test_non_json_lines_are_retained_as_errors(parser, name: str):
    parsed = parser([*_lines(name), "not json"])

    assert parsed.coverage == "partial"
    assert any("line-parse failure" in error for error in parsed.errors)


def test_parse_trace_routes_frozen_and_fixture_shapes():
    stream = parse_trace(_lines("fixture-exec-stream.jsonl"))
    rollout = parse_trace(_lines("fixture-route-a.jsonl"))
    fixture = parse_trace(['{"command":"jg search bug","result":{"matched":true}}'])
    empty = parse_trace([])

    assert stream.provider_meta["source"] == "codex-stream"
    assert rollout.provider_meta["source"] == "codex-rollout"
    assert len(fixture.events) == 1
    assert empty.events == ()


@pytest.mark.parametrize(
    "name",
    [
        "fixture-exec-stream.jsonl",
        "fixture-route-a.jsonl",
        "fixture-route-b.jsonl",
    ],
)
def test_derive_metrics_has_a_token_basis(name: str):
    parsed = parse_trace(_lines(name))
    metrics = derive_metrics(
        parsed.events,
        set(),
        coverage=parsed.coverage,
        missing_dimensions=parsed.missing_dimensions,
        token_count_records=parsed.token_count_records,
    )

    assert metrics.tokens_before_first_edit != "indeterminate"


def test_shell_unwrap_and_edit_classification():
    script = "printf %s three > gamma.txt"

    assert unwrap_shell_call(f"bash -lc '{script}'") == script
    assert unwrap_shell_call(f"/bin/bash -lc '{script}'") == script
    assert unwrap_shell_call("printf %s three > gamma.txt") == script
    assert classify_command(f"bash -lc '{script}'") == EventKind.EDIT


def test_rollout_exec_fallback_is_secondary_to_command_execution():
    lines = [
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "session_id": "session",
                    "cli_version": "0.157.1",
                    "model_provider": "openai",
                },
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "status": "completed",
                    "call_id": "call-1",
                    "name": "exec",
                    "input": 'tools.exec_command({cmd: "printf %s one > alpha.txt"})',
                },
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call-1",
                    "output": [{"type": "input_text", "text": "exit_code=0"}],
                },
            }
        ),
        json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "total_tokens": 2,
                        },
                        "last_token_usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "total_tokens": 2,
                        },
                    },
                },
            }
        ),
        json.dumps({"type": "event_msg", "payload": {"type": "task_complete"}}),
    ]

    parsed = parse_codex_rollout(lines)

    assert parsed.coverage == "full"
    assert len(parsed.events) == 1
    assert parsed.events[0].kind == EventKind.EDIT
    assert parsed.events[0].exit_code == 0


def test_failed_command_is_finished_not_partial():
    lines = [
        '{"type":"thread.started","thread_id":"t1"}',
        (
            '{"type":"item.started","item":{"id":"i1","type":"command_execution",'
            '"command":"/usr/bin/bash -lc \'git status\'","status":"in_progress"}}'
        ),
        (
            '{"type":"item.completed","item":{"id":"i1","type":"command_execution",'
            '"command":"/usr/bin/bash -lc \'git status\'","aggregated_output":"fatal",'
            '"exit_code":1,"status":"failed"}}'
        ),
        (
            '{"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,'
            '"output_tokens":1,"reasoning_output_tokens":0}}'
        ),
    ]
    parsed = parse_codex_stream(lines)
    assert parsed.coverage == "full"
    assert "start_end_pairing" not in parsed.missing_dimensions
    assert parsed.events[0].completed is True
    assert parsed.events[0].exit_code == 1


def test_stream_unpaired_item_completed_is_tolerated():
    """A killed/partial stream can hold item.completed with no paired item.started.

    Live regression: parse crashed on the unpaired-item path (eager evaluation of
    the pending-start fallback), which would have failed whole records for timeout
    runs. The event must be kept, flagged, and the parse must not raise.
    """
    lines = [
        (
            '{"type":"item.completed","item":{"id":"i1","type":"command_execution",'
            '"command":"/usr/bin/bash -lc \'ls -la\'","status":"completed","exit_code":0}}'
        ),
    ]
    parsed = parse_codex_stream(lines)
    assert len(parsed.events) == 1
    assert parsed.events[0].cmd_scrubbed == "ls -la"
    assert "start_end_pairing" in parsed.missing_dimensions
    assert parsed.coverage == "partial"


def test_stream_file_change_becomes_edit_event():
    """codex file_change items must parse as edit events, not poison coverage.

    Live regression (a1 smoke): 'unknown stream item type file_change' entries
    forced trace_coverage=partial on every editing run.
    """
    lines = [
        (
            '{"type":"item.started","item":{"id":"f1","type":"file_change","changes":'
            '[{"path":"/workspace/src/a.py","kind":"update"}],"status":"in_progress"}}'
        ),
        (
            '{"type":"item.completed","item":{"id":"f1","type":"file_change","changes":'
            '[{"path":"/workspace/src/a.py","kind":"update"},'
            '{"path":"/workspace/tests/t.py","kind":"add"}],"status":"completed"}}'
        ),
    ]
    parsed = parse_codex_stream(lines, "/workspace")
    assert len(parsed.events) == 1
    event = parsed.events[0]
    assert event.kind is EventKind.EDIT
    assert event.files_touched == ["src/a.py", "tests/t.py"]
    assert event.started and event.completed
    assert "file_change" in event.cmd_scrubbed
    assert "known_event_types" not in parsed.missing_dimensions


def test_stream_file_change_sandbox_paths_with_host_workspace():
    """Live regression (a3 smoke): the parser receives the HOST workspace path,
    but codex reports file_change paths in the sandbox namespace (/workspace/...).
    Those must map to workspace-relative files instead of raising
    'path is not safely relative' and aborting record assembly."""
    lines = [
        (
            '{"type":"item.started","item":{"id":"f1","type":"file_change","changes":'
            '[{"path":"/workspace/src/a.py","kind":"update"}],"status":"in_progress"}}'
        ),
        (
            '{"type":"item.completed","item":{"id":"f1","type":"file_change","changes":'
            '[{"path":"/workspace/src/a.py","kind":"update"},'
            '{"path":"/workspace/tests/t.py","kind":"add"}],"status":"completed"}}'
        ),
    ]
    parsed = parse_codex_stream(lines, "/home/user/runs/task-a0-r0/workspace")
    assert len(parsed.events) == 1
    event = parsed.events[0]
    assert event.files_touched == ["src/a.py", "tests/t.py"]
    assert not parsed.errors
