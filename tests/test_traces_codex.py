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
