"""Adapters for the frozen codex-cli 0.157.1 trace formats."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from .models import EventKind
from .traces import (
    TraceParse,
    normalize_event,
    parse_jsonl,
    unwrap_shell_call,
)

_STREAM_TYPES = {"thread.started", "turn.started", "turn.completed"}
_ROLLOUT_TYPES = {
    "session_meta",
    "turn_context",
    "world_state",
    "event_msg",
    "response_item",
    "token_usage_record",
}
_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
_KNOWN_ROLLOUT_ITEM_TYPES = {"UserMessage", "Reasoning", "AgentMessage", "CommandExecution"}
_KNOWN_RESPONSE_ITEM_TYPES = {
    "message",
    "reasoning",
    "custom_tool_call",
    "custom_tool_call_output",
    "function_call",
    "function_call_output",
}


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return default if value is None else int(value)
    except (TypeError, ValueError):
        return default


_FINISHED_STATUSES = {"completed", "failed"}


def _finished(status: Any) -> bool:
    """A status is finished when the execution ended, successfully or not."""
    return status in _FINISHED_STATUSES


def _timestamp_ms(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0, int(value))
    if not isinstance(value, str):
        return 0
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return 0
    return max(0, int(timestamp.timestamp() * 1000))


def _usage_values(usage: Any) -> dict[str, int]:
    usage = usage if isinstance(usage, dict) else {}
    values = {field: _int_value(usage.get(field)) for field in _USAGE_FIELDS}
    values["total_tokens"] = _int_value(
        usage.get("total_tokens"),
        values["input_tokens"] + values["output_tokens"],
    )
    return values


def _usage_row(usage: Any, timestamp_ms: int) -> dict[str, int]:
    values = _usage_values(usage)
    return {
        "token_count": values["input_tokens"] + values["output_tokens"],
        "ts_offset_ms": timestamp_ms,
        "input_tokens": values["input_tokens"],
        "cached_input_tokens": values["cached_input_tokens"],
        "output_tokens": values["output_tokens"],
        "reasoning_output_tokens": values["reasoning_output_tokens"],
        "total_tokens": values["total_tokens"],
    }


def _provider_usage(usage: Any, *, recompute_total: bool = False) -> dict[str, int]:
    values = _usage_values(usage)
    return {
        "input_tokens": values["input_tokens"],
        "cached_input_tokens": values["cached_input_tokens"],
        "output_tokens": values["output_tokens"],
        "reasoning_output_tokens": values["reasoning_output_tokens"],
        "total_tokens": (
            values["input_tokens"] + values["output_tokens"]
            if recompute_total
            else values["total_tokens"]
        ),
    }


def _blank_provider_usage() -> dict[str, int]:
    return _provider_usage({})


def _load_line(
    line: str,
    index: int,
    errors: list[str],
    missing: set[str],
) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, TypeError) as exc:
        errors.append(f"line {index + 1}: line-parse failure: {exc}")
        missing.add("line_parse")
        return None
    if not isinstance(value, dict):
        errors.append(f"line {index + 1}: top-level event is not an object")
        missing.add("event_type")
        return None
    return value


def _unknown(
    errors: list[str],
    missing: set[str],
    index: int,
    message: str,
) -> None:
    errors.append(f"line {index + 1}: {message}")
    missing.add("known_event_types")


def _command_event(
    *,
    command: str,
    index: int,
    workspace: str | None,
    timestamp_ms: int = 0,
    exit_code: int | None = None,
    summary: Any = "",
    started: bool = True,
    completed: bool = True,
    kind: EventKind | None = None,
) -> Any:
    raw: dict[str, Any] = {
        "seq": index,
        "started": started,
        "completed": completed,
        "ts_offset_ms": max(0, timestamp_ms),
        "exit_code": exit_code,
    }
    if kind is not None:
        raw["kind"] = kind.value
    return normalize_event(
        raw,
        seq=index,
        workspace=workspace,
        command_override=command,
        result_override={"summary": str(summary) if summary is not None else ""},
    )


def _stream_item(value: dict[str, Any]) -> dict[str, Any] | None:
    item = value.get("item")
    return item if isinstance(item, dict) else None


def _file_change_event(
    item: dict[str, Any],
    index: int,
    workspace: str | None,
    *,
    started: bool,
) -> Any:
    """Normalize a codex ``file_change`` item into an edit-kind tool event."""
    files: list[str] = []
    changes = item.get("changes")
    if isinstance(changes, list):
        for change in changes:
            if isinstance(change, dict) and change.get("path"):
                path = str(change["path"])
                if workspace:
                    path = path.removeprefix(workspace.rstrip("/") + "/")
                files.append(path)
    command = "file_change: " + ", ".join(files) if files else "file_change"
    raw: dict[str, Any] = {
        "seq": index,
        "started": started,
        "completed": True,
        "ts_offset_ms": 0,
        "kind": EventKind.EDIT.value,
        "files_touched": files,
    }
    return normalize_event(
        raw,
        seq=index,
        workspace=workspace,
        command_override=command,
        result_override={"summary": ""},
    )


def parse_codex_stream(
    lines: Iterable[str],
    workspace: str | None = None,
) -> TraceParse:
    """Parse the one-object-per-line ``codex exec --json`` stream."""
    events: list[Any] = []
    errors: list[str] = []
    missing: set[str] = set()
    token_records: list[dict[str, Any]] = []
    pending: dict[str, tuple[int, dict[str, Any]]] = {}
    file_change_starts: set[str] = set()
    session_id: str | None = None
    terminal_seen = False
    provider_usage = _blank_provider_usage()

    for index, line in enumerate(lines):
        value = _load_line(line, index, errors, missing)
        if value is None:
            continue
        event_type = value.get("type")
        if event_type == "thread.started":
            thread_id = value.get("thread_id")
            if thread_id:
                session_id = str(thread_id)
            else:
                missing.add("session_association")
            continue
        if event_type == "turn.started":
            continue
        if event_type == "item.started":
            item = _stream_item(value)
            item_type = item.get("type") if item else None
            if item_type == "agent_message":
                continue
            if item_type == "file_change":
                file_change_starts.add(str(item.get("id", "")) if item else "")
                continue
            if item_type != "command_execution":
                _unknown(
                    errors,
                    missing,
                    index,
                    f"unknown stream item type {item_type!r}",
                )
                continue
            item_id = str(item.get("id", "")) if item else ""
            key = item_id or f"line-{index}"
            if key in pending:
                missing.add("start_end_pairing")
            else:
                pending[key] = (index, item)
            continue
        if event_type == "item.completed":
            item = _stream_item(value)
            item_type = item.get("type") if item else None
            if item_type == "agent_message":
                continue
            if item_type == "file_change":
                item_id = str(item.get("id", "")) if item else ""
                started = item_id in file_change_starts
                file_change_starts.discard(item_id)
                if not started:
                    missing.add("start_end_pairing")
                events.append(
                    _file_change_event(
                        item if item is not None else {},
                        index,
                        workspace,
                        started=started,
                    )
                )
                continue
            if item_type != "command_execution":
                _unknown(
                    errors,
                    missing,
                    index,
                    f"unknown stream item type {item_type!r}",
                )
                continue
            item_id = str(item.get("id", "")) if item else ""
            start_key = item_id
            started = pending.pop(start_key, None) if start_key else None
            if started is None:
                missing.add("start_end_pairing")
            fallback = str(started[1].get("command", "")) if started is not None else ""
            command = str(item.get("command") or fallback) if item is not None else fallback
            status = item.get("status") if item else None
            events.append(
                _command_event(
                    command=unwrap_shell_call(command),
                    index=index,
                    workspace=workspace,
                    exit_code=(
                        _int_value(item.get("exit_code"))
                        if item and item.get("exit_code") is not None
                        else None
                    ),
                    summary=item.get("aggregated_output", "") if item else "",
                    started=started is not None,
                    completed=_finished(status),
                )
            )
            continue
        if event_type == "turn.completed":
            terminal_seen = True
            usage = value.get("usage")
            if isinstance(usage, dict):
                provider_usage = _provider_usage(usage, recompute_total=True)
                token_records.append(_usage_row(usage, _timestamp_ms(value.get("timestamp"))))
            else:
                missing.add("token_basis")
            continue
        _unknown(errors, missing, index, f"unknown top-level event type {event_type!r}")

    for start_index, item in pending.values():
        command = str(item.get("command", ""))
        events.append(
            _command_event(
                command=unwrap_shell_call(command),
                index=start_index,
                workspace=workspace,
                exit_code=(
                    _int_value(item.get("exit_code"))
                    if item.get("exit_code") is not None
                    else None
                ),
                summary=item.get("aggregated_output", ""),
                completed=item.get("status") == "completed",
            )
        )
        missing.add("start_end_pairing")

    if not session_id:
        missing.add("session_association")
    if not terminal_seen:
        missing.add("terminal_marker")
    if not token_records:
        missing.add("token_basis")
    if any(not event.completed for event in events):
        missing.add("start_end_pairing")
    ordered = sorted(events, key=lambda event: (event.ts_offset_ms, event.seq))
    return TraceParse(
        tuple(ordered),
        "full" if not errors and not missing else "partial",
        tuple(sorted(missing)),
        tuple(errors),
        tuple(token_records),
        {
            "source": "codex-stream",
            "session_id": session_id,
            "cli_version": None,
            "model_provider": None,
            "model": {"resolved": None, "effort": None},
            "usage": provider_usage,
            "rate_limits": None,
        },
    )


def _rollout_payload(value: dict[str, Any]) -> dict[str, Any]:
    payload = value.get("payload")
    return payload if isinstance(payload, dict) else {}


def _command_from_exec_input(input_text: str) -> str | None:
    match = re.search(
        r"\bcmd\s*:\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')",
        input_text,
    )
    if not match:
        return None
    literal = match.group(1)
    try:
        value = json.loads(literal) if literal.startswith('"') else ast.literal_eval(literal)
    except (json.JSONDecodeError, SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) else None


def _response_output(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for entry in output:
        if isinstance(entry, dict):
            text = entry.get("text")
            if text is not None:
                parts.append(str(text))
        elif entry is not None:
            parts.append(str(entry))
    return "".join(parts)


def _response_exit_code(output: str) -> int | None:
    match = re.search(r"\bexit_code\s*=\s*(-?\d+)", output)
    return int(match.group(1)) if match else None


def parse_codex_rollout(
    lines: Iterable[str],
    workspace: str | None = None,
) -> TraceParse:
    """Parse a codex-cli session rollout file."""
    events: list[Any] = []
    errors: list[str] = []
    missing: set[str] = set()
    token_records: list[dict[str, Any]] = []
    session_id: str | None = None
    cli_version: str | None = None
    model_provider: str | None = None
    model: dict[str, str | None] = {"resolved": None, "effort": None}
    provider_usage = _blank_provider_usage()
    rate_limits: dict[str, Any] | None = None
    terminal_seen = False
    command_execution_seen = False
    fallback_calls: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    fallback_outputs: dict[str, str] = {}

    for index, line in enumerate(lines):
        value = _load_line(line, index, errors, missing)
        if value is None:
            continue
        event_type = value.get("type")
        if event_type == "session_meta":
            payload = _rollout_payload(value)
            candidate = payload.get("session_id", payload.get("id", ""))
            if candidate:
                session_id = str(candidate)
            else:
                missing.add("session_association")
            cli_version = (
                str(payload["cli_version"]) if payload.get("cli_version") is not None else None
            )
            model_provider = (
                str(payload["model_provider"])
                if payload.get("model_provider") is not None
                else None
            )
            continue
        if event_type == "turn_context":
            payload = _rollout_payload(value)
            resolved = payload.get("model")
            if isinstance(resolved, dict):
                resolved = resolved.get("resolved", resolved.get("name"))
            model["resolved"] = str(resolved) if resolved is not None else None
            effort = payload.get("effort")
            if effort is None:
                collaboration = payload.get("collaboration_mode")
                if isinstance(collaboration, dict):
                    settings = collaboration.get("settings")
                    if isinstance(settings, dict):
                        effort = settings.get("reasoning_effort")
            model["effort"] = str(effort) if effort is not None else None
            continue
        if event_type == "world_state":
            continue
        if event_type == "event_msg":
            payload = _rollout_payload(value)
            payload_type = payload.get("type")
            if payload_type == "task_started":
                continue
            if payload_type == "task_complete":
                terminal_seen = True
                continue
            if payload_type == "token_count":
                info = payload.get("info")
                info = info if isinstance(info, dict) else {}
                total_usage = info.get("total_token_usage")
                last_usage = info.get("last_token_usage", total_usage)
                if isinstance(last_usage, dict) or isinstance(total_usage, dict):
                    token_records.append(
                        _usage_row(
                            last_usage if isinstance(last_usage, dict) else total_usage,
                            _timestamp_ms(value.get("timestamp")),
                        )
                    )
                else:
                    missing.add("token_basis")
                if isinstance(total_usage, dict):
                    provider_usage = _provider_usage(total_usage)
                else:
                    missing.add("token_basis")
                if "rate_limits" in payload:
                    candidate_limits = payload.get("rate_limits")
                    rate_limits = (
                        candidate_limits if isinstance(candidate_limits, dict) else None
                    )
                continue
            if payload_type == "item_completed":
                item = payload.get("item")
                item_type = item.get("type") if isinstance(item, dict) else None
                if item_type in {"UserMessage", "Reasoning", "AgentMessage"}:
                    continue
                if item_type != "CommandExecution":
                    _unknown(
                        errors,
                        missing,
                        index,
                        f"unknown rollout item type {item_type!r}",
                    )
                    continue
                command_execution_seen = True
                command_argv = item.get("command", []) if isinstance(item, dict) else []
                command = (
                    str(command_argv[-1])
                    if isinstance(command_argv, list) and command_argv
                    else ""
                )
                summary = (
                    item.get("aggregated_output") or item.get("stdout", "")
                    if isinstance(item, dict)
                    else ""
                )
                status = item.get("status") if isinstance(item, dict) else None
                events.append(
                    _command_event(
                        command=command,
                        index=index,
                        workspace=workspace,
                        timestamp_ms=_int_value(payload.get("started_at_ms")),
                        exit_code=(
                            _int_value(item.get("exit_code"))
                            if isinstance(item, dict) and item.get("exit_code") is not None
                            else None
                        ),
                        summary=summary,
                        completed=_finished(status),
                    )
                )
                if not _finished(status):
                    missing.add("start_end_pairing")
                continue
            _unknown(errors, missing, index, f"unknown rollout payload type {payload_type!r}")
            continue
        if event_type == "response_item":
            payload = _rollout_payload(value)
            payload_type = payload.get("type")
            if payload_type in {"message", "reasoning", "function_call", "function_call_output"}:
                continue
            if payload_type == "custom_tool_call":
                name = payload.get("name")
                if name == "apply_patch":
                    events.append(
                        _command_event(
                            command=str(payload.get("input", "")),
                            index=index,
                            workspace=workspace,
                            exit_code=None,
                            summary="",
                            completed=payload.get("status") == "completed",
                            kind=EventKind.EDIT,
                        )
                    )
                elif name == "exec":
                    fallback_calls.append((index, value, payload))
                else:
                    _unknown(
                        errors,
                        missing,
                        index,
                        f"unknown custom tool name {name!r}",
                    )
                continue
            if payload_type == "custom_tool_call_output":
                call_id = payload.get("call_id")
                if call_id:
                    fallback_outputs[str(call_id)] = _response_output(payload)
                continue
            _unknown(errors, missing, index, f"unknown rollout response type {payload_type!r}")
            continue
        if event_type == "token_usage_record":
            usage = _rollout_payload(value).get("usage")
            if isinstance(usage, dict):
                token_records.append(
                    _usage_row(usage, _timestamp_ms(value.get("timestamp")))
                )
            else:
                missing.add("token_basis")
            continue
        _unknown(errors, missing, index, f"unknown top-level event type {event_type!r}")

    if not command_execution_seen:
        for index, value, payload in fallback_calls:
            command = _command_from_exec_input(str(payload.get("input", "")))
            if command is None:
                errors.append(f"line {index + 1}: exec custom tool call has no cmd")
                missing.add("known_event_types")
                continue
            call_id = str(payload.get("call_id", ""))
            output = fallback_outputs.get(call_id, "")
            events.append(
                _command_event(
                    command=command,
                    index=index,
                    workspace=workspace,
                    timestamp_ms=_timestamp_ms(value.get("timestamp")),
                    exit_code=_response_exit_code(output),
                    summary=output,
                    completed=payload.get("status") == "completed",
                )
            )

    if not session_id:
        missing.add("session_association")
    if not terminal_seen:
        missing.add("terminal_marker")
    if not token_records:
        missing.add("token_basis")
    if any(not event.completed for event in events):
        missing.add("start_end_pairing")
    ordered = sorted(events, key=lambda event: (event.ts_offset_ms, event.seq))
    return TraceParse(
        tuple(ordered),
        "full" if not errors and not missing else "partial",
        tuple(sorted(missing)),
        tuple(errors),
        tuple(token_records),
        {
            "source": "codex-rollout",
            "session_id": session_id,
            "cli_version": cli_version,
            "model_provider": model_provider,
            "model": model,
            "usage": provider_usage,
            "rate_limits": rate_limits,
        },
    )


def parse_trace(
    lines: Iterable[str],
    workspace: str | None = None,
) -> TraceParse:
    """Detect a trace format from its first parseable JSON object."""
    materialized = list(lines)
    detected_type: Any = None
    for line in materialized:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            detected_type = value.get("type")
            break
    if detected_type in _STREAM_TYPES or (
        isinstance(detected_type, str) and detected_type.startswith("item.")
    ):
        return parse_codex_stream(materialized, workspace)
    if detected_type in _ROLLOUT_TYPES:
        return parse_codex_rollout(materialized, workspace)
    return parse_jsonl(materialized, workspace)
