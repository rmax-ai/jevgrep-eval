"""Codex-style rollout normalization and leakage-aware derivations."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .models import EventKind, ToolEvent, ToolResult
from .util import REDACTION_VERSION, normalize_path

_DISCOVERY = {"rg", "grep", "find", "ls", "tree", "cat", "head", "tail", "sed", "awk", "jg", "jevgrep", "bm25"}
_SEARCH = {"rg", "grep", "find", "jg", "jevgrep", "bm25"}
_READ = {"cat", "head", "tail", "sed", "awk"}
_TEST = {"pytest", "npm", "pnpm", "yarn", "make", "tox"}
_SECRET = re.compile(r"(?i)(token|api[_-]?key|password|secret|cookie)=([^\s&]+)")


class TraceParseError(ValueError):
    """A trace has a structurally invalid line."""


def scrub_command(command: str, workspace: str | None = None) -> str:
    result = command.replace("\x00", "\\0")
    if workspace:
        result = result.replace(workspace, "<WORKSPACE>")
    return _SECRET.sub(r"\1=<REDACTED>", result)


def command_digest(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _commands(command: str) -> list[str]:
    # ``shlex`` is used only for classification, never execution.
    pieces = re.split(r"\s*(?:\||;|&&|\|\||&)\s*", command)
    return [piece.strip() for piece in pieces if piece.strip()]


def _executable(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    return tokens[0].rsplit("/", 1)[-1] if tokens else ""


def unwrap_shell_call(command: str) -> str:
    """Return the script from a simple bash/sh/zsh ``-c`` invocation."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command
    if (
        len(tokens) >= 3
        and tokens[0].rsplit("/", 1)[-1] in {"bash", "sh", "zsh"}
        and tokens[1] in {"-c", "-lc"}
    ):
        return tokens[2]
    return command


def classify_command(command: str) -> EventKind:
    command = unwrap_shell_call(command)
    executables = [_executable(segment) for segment in _commands(command)]
    # Retrieval tools take precedence wherever they appear in a compound command:
    # `command -v jg || true; jg 'query' | head` must read as a Jevgrep search.
    if "jg" in executables or "jevgrep" in executables:
        return EventKind.SEARCH_JG
    if "bm25" in executables or "jevgrep-bm25" in executables:
        return EventKind.SEARCH_BM25
    executable = executables[0] if executables else ""
    if executable in _READ:
        return EventKind.READ
    if executable in {"rg", "grep", "find", "ls", "tree"}:
        return EventKind.SEARCH_NATIVE
    if executable in _TEST:
        return EventKind.TEST
    if executable in {
        "cp",
        "mv",
        "mkdir",
        "touch",
        "rm",
        "python",
        "python3",
        "printf",
        "tee",
        "dd",
        "install",
    } and any(
        word in command for word in ("write", "open(", "replace(", " -i ", ">>", " > ", " <<")
    ):
        return EventKind.EDIT
    return EventKind.OTHER_SHELL


def count_search_invocations(events: Iterable[Any], marker: str = "Jevgrep:") -> int:
    """Count Jevgrep searches that actually ran, from recorded command output.

    A search that executed prints a ``Jevgrep:`` result header. Counting headers
    rather than command kinds survives compound commands that defeat first-token
    classification and skips invocations that never executed (short-circuited
    ``&&`` chains, ``--help`` probes, missing binaries). When a command's output
    was not captured at all (empty summary) it still counts if it classifies as a
    search -- the run paid for it. Live case: the click-3533 a1 smoke reconciled
    $0.000 against one real metered search because the invocation was embedded
    in a compound command.
    """
    count = 0
    for event in events:
        summary = _event_summary(event)
        headers = summary.count(marker)
        if headers:
            count += headers
        elif not summary.strip() and _event_kind_value(event) == EventKind.SEARCH_JG.value:
            count += 1
    return count


def _event_summary(event: Any) -> str:
    result = event.get("result") if isinstance(event, dict) else getattr(event, "result", None)
    if isinstance(result, dict):
        summary = result.get("summary", "")
    else:
        summary = getattr(result, "summary", "")
    return str(summary or "")


def _event_kind_value(event: Any) -> str:
    kind = event.get("kind") if isinstance(event, dict) else getattr(event, "kind", "")
    return str(getattr(kind, "value", kind))


def _result(raw: Any) -> ToolResult:
    if not isinstance(raw, dict):
        return ToolResult(summary=str(raw) if raw is not None else "")
    files_returned = raw.get("files_returned", raw.get("files", []))
    if not isinstance(files_returned, list):
        files_returned = []
    excerpts = raw.get("excerpts", raw.get("chunks", []))
    if not isinstance(excerpts, list):
        excerpts = []
    matched = raw.get("matched")
    if matched is not None:
        matched = bool(matched)
    successful = raw.get("successful", raw.get("ok"))
    if successful is not None:
        successful = bool(successful)
    return ToolResult(
        files_returned=[str(value) for value in files_returned],
        chunk_ids=[str(value) for value in raw.get("chunk_ids", []) if isinstance(raw.get("chunk_ids", []), list)],
        tokens_returned=int(raw["tokens_returned"]) if raw.get("tokens_returned") is not None else None,
        matched=matched,
        summary=str(raw.get("summary", raw.get("stdout", ""))),
        excerpts=[str(value) for value in excerpts],
        successful=successful,
    )


def normalize_event(
    raw: dict[str, Any],
    seq: int | None = None,
    workspace: str | None = None,
    *,
    command_override: str | None = None,
    result_override: Any = None,
) -> ToolEvent:
    command = command_override or str(raw.get("command", raw.get("cmd", raw.get("input", ""))))
    kind_value = raw.get("kind")
    try:
        event_kind = EventKind(kind_value)
    except (TypeError, ValueError):
        event_kind = classify_command(command)
    event_result = _result(result_override if result_override is not None else raw.get("result"))
    files = raw.get("files_touched", raw.get("files", []))
    if not isinstance(files, list):
        files = []
    output = raw.get("stdout", raw.get("output", raw.get("content", "")))
    if output:
        event_result = event_result.model_copy(
            update={
                "summary": f"{event_result.summary}{output}",
                "excerpts": [*event_result.excerpts, str(output)],
            }
        )
    return ToolEvent(
        seq=int(raw.get("seq", seq if seq is not None else 0)),
        kind=event_kind,
        cmd_digest=command_digest(command),
        cmd_scrubbed=scrub_command(command, workspace),
        ts_offset_ms=int(raw.get("ts_offset_ms", raw.get("elapsed_ms", raw.get("timestamp_offset_ms", 0)))),
        files_touched=[normalize_path(str(path)) for path in files],
        result=event_result,
        started=bool(raw.get("started", True)),
        completed=bool(raw.get("completed", True)),
        redaction_version=REDACTION_VERSION,
        root=normalize_path(str(raw.get("root", ""))) if raw.get("root") else "",
        exit_code=int(raw["exit_code"]) if raw.get("exit_code") is not None else None,
        truncated=bool(raw.get("truncated", False)),
    )


@dataclass(frozen=True)
class TraceParse:
    events: tuple[ToolEvent, ...]
    coverage: str
    missing_dimensions: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    token_count_records: tuple[dict[str, Any], ...] = ()
    provider_meta: dict[str, Any] = field(default_factory=dict)

    def __iter__(self):
        # Compatibility with the original three-value parser.
        yield list(self.events)
        yield self.coverage
        yield list(self.errors)

    def __getitem__(self, index: int):
        return (list(self.events), self.coverage, list(self.errors))[index]

    def __len__(self) -> int:
        return 3


def parse_rollout_jsonl(
    lines: Iterable[str],
    workspace: str | None = None,
) -> TraceParse:
    """Parse known rollout records and name every missing dimension."""
    events: list[ToolEvent] = []
    errors: list[str] = []
    missing: set[str] = set()
    token_records: list[dict[str, Any]] = []
    pending: dict[str, tuple[int, str]] = {}
    sessions: set[str] = set()
    terminal_seen = False

    def session_for(value: dict[str, Any]) -> str:
        return str(value.get("session_id", value.get("session", "")))

    def require_session(value: dict[str, Any]) -> str:
        session_id = session_for(value)
        if not session_id or session_id not in sessions:
            missing.add("session_association")
        return session_id

    for index, line in enumerate(lines):
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"line {index + 1}: line-parse failure: {exc}")
            missing.update(("event_type", "session_association"))
            continue
        if not isinstance(value, dict):
            errors.append(f"line {index + 1}: top-level event is not an object")
            missing.add("event_type")
            continue
        event_type = value.get("type", value.get("event_type"))
        if event_type in {"token_count", "usage", "token_counts"}:
            token_records.append(value)
            continue
        if event_type in {"session_start", "rollout_start"}:
            session_id = str(value.get("session_id", value.get("id", "")))
            if not session_id:
                missing.add("session_association")
            else:
                sessions.add(session_id)
            continue
        if event_type in {"session_end", "rollout_end", "turn_end"}:
            session_id = str(value.get("session_id", value.get("id", "")))
            if not session_id or session_id not in sessions:
                missing.add("session_association")
            else:
                terminal_seen = True
            continue
        if event_type in {"tool_call", "command", "tool_start", "tool_use"}:
            event = normalize_event(value, index, workspace)
            events.append(event)
            session_id = require_session(value)
            call_id = str(value.get("call_id", value.get("id", "")))
            is_complete = bool(value.get("completed", False)) and (
                "result" in value or "stdout" in value or "output" in value
            )
            if call_id and not is_complete:
                pending[call_id] = (len(events) - 1, session_id)
            elif not call_id and not is_complete:
                missing.add("start_end_pairing")
            continue
        if event_type in {"tool_result", "command_result", "tool_end"}:
            call_id = str(value.get("call_id", value.get("id", "")))
            if call_id and call_id in pending:
                event_index, start_session = pending.pop(call_id)
                result_session = require_session(value)
                if result_session != start_session or (
                    sessions and result_session not in sessions
                ):
                    missing.add("session_association")
                old_event = events[event_index]
                events[event_index] = old_event.model_copy(
                    update={
                        "result": _result(value.get("result", value)),
                        "completed": True,
                        "exit_code": (
                            int(value["exit_code"])
                            if value.get("exit_code") is not None
                            else old_event.exit_code
                        ),
                    }
                )
            elif call_id:
                missing.add("start_end_pairing")
            # Some fixtures carry command and result in one line.
            if value.get("command") or value.get("cmd"):
                event = normalize_event(value, index, workspace)
                events.append(event)
                require_session(value)
            else:
                if not call_id:
                    missing.add("start_end_pairing")
            continue
        if event_type is None and ("command" in value or "cmd" in value):
            events.append(normalize_event(value, index, workspace))
            require_session(value)
            if not value.get("call_id") and not value.get("result") and not value.get("stdout"):
                missing.add("start_end_pairing")
            continue
        errors.append(f"line {index + 1}: unknown top-level event type {event_type!r}")
        missing.add("known_event_types")
    ordered = sorted(events, key=lambda event: (event.ts_offset_ms, event.seq))
    if pending:
        missing.add("start_end_pairing")
    if any(not event.completed for event in ordered):
        missing.add("start_end_pairing")
    if events and not terminal_seen:
        missing.add("terminal_marker")
    if not ordered and not errors:
        missing.add("tool_events")
    if token_records and any("token_count" not in row and "input_tokens" not in row for row in token_records):
        missing.add("token_basis")
    return TraceParse(
        tuple(ordered),
        "full" if not errors and not missing else "partial",
        tuple(sorted(missing)),
        tuple(errors),
        tuple(token_records),
    )


def parse_jsonl(
    lines: Iterable[str],
    workspace: str | None = None,
) -> TraceParse:
    return parse_rollout_jsonl(lines, workspace)


def _search_key(event: ToolEvent) -> tuple[str, str]:
    command = event.cmd_scrubbed
    tokens = command.split()
    executable = _executable(command)
    query_tokens = [
        token.lower()
        for token in tokens
        if token not in {executable, "--json", "--no-cache"} and not token.startswith("-")
    ]
    return " ".join(query_tokens), normalize_path(event.root or ".")


@dataclass(frozen=True)
class TraceMetrics:
    first_discovery_operation: int | str | None
    first_gold_path_exposure: int | str | None
    first_gold_content_exposure: int | str | None
    first_direct_read: int | str | None
    calls_to_first_gold: int | str | None
    tokens_before_first_edit: int | str | None
    non_reference_files_opened: int | str
    non_reference_file_operations: int | str
    non_reference_unique_files: int | str
    fallback_calls_after_successful_specialized: int | str
    fallback_calls_after_empty_or_error: int | str
    repeated_searches: int | str
    specialized_query_count: int | str
    trace_coverage: str = "full"
    missing_dimensions: tuple[str, ...] = ()

    @property
    def calls_before_first_gold(self) -> int | None:
        return self.calls_to_first_gold

    @property
    def time_to_first_gold_ms(self) -> int | None:
        return None

    @property
    def fallback_search_calls(self) -> int:
        return self.fallback_calls_after_successful_specialized

    @property
    def repeated_search_count(self) -> int:
        return self.repeated_searches


def _is_discovery(event: ToolEvent) -> bool:
    return any(_executable(part) in _DISCOVERY for part in _commands(event.cmd_scrubbed))


def _event_files(event: ToolEvent) -> set[str]:
    return {normalize_path(path) for path in [*event.files_touched, *event.result.files_returned]}


def _content_exposed(event: ToolEvent) -> bool:
    return bool(event.result.excerpts or event.result.summary) and event.completed and not event.truncated


def _successful_specialized(event: ToolEvent) -> bool:
    return event.kind in {EventKind.SEARCH_JG, EventKind.SEARCH_BM25} and (
        event.result.successful is True or event.result.matched is True
    )


def derive_metrics(
    events: Iterable[ToolEvent],
    reference_files: set[str],
    *,
    evidence_files: set[str] | None = None,
    coverage: str = "full",
    missing_dimensions: Iterable[str] = (),
    token_count_records: Iterable[dict[str, Any]] = (),
) -> TraceMetrics:
    ordered = sorted(events, key=lambda event: (event.ts_offset_ms, event.seq))
    reference = {normalize_path(path) for path in reference_files}
    evidence = {normalize_path(path) for path in (evidence_files or reference_files)}
    missing_set = set(missing_dimensions)
    discovery = [event for event in ordered if _is_discovery(event) or event.kind in {EventKind.READ, EventKind.SEARCH_NATIVE, EventKind.SEARCH_JG, EventKind.SEARCH_BM25}]
    discovery_value: int | str | None = None
    if discovery:
        first = discovery[0]
        ambiguous = (
            len(_commands(first.cmd_scrubbed)) > 1
            or "&" in first.cmd_scrubbed
            or sum(event.ts_offset_ms == first.ts_offset_ms for event in discovery) > 1
        )
        discovery_value = "indeterminate" if ambiguous else ordered.index(first)
    path_event = next((event for event in ordered if _event_files(event) & reference), None)
    content_event = next(
        (
            event
            for event in ordered
            if _event_files(event) & evidence and _content_exposed(event)
        ),
        None,
    )
    direct_event = next((event for event in ordered if event.kind == EventKind.READ), None)
    opened_operations = [
        _event_files(event) - reference
        for event in ordered
        if event.kind == EventKind.READ
    ]
    opened_unique = set().union(*opened_operations) if opened_operations else set()
    specialized = [
        index
        for index, event in enumerate(ordered)
        if event.kind in {EventKind.SEARCH_JG, EventKind.SEARCH_BM25}
    ]
    first_success = next((index for index in specialized if _successful_specialized(ordered[index])), None)
    first_failed = next(
        (index for index in specialized if not _successful_specialized(ordered[index])),
        None,
    )
    fallback_success = (
        sum(event.kind == EventKind.SEARCH_NATIVE for event in ordered[first_success + 1 :])
        if first_success is not None
        else 0
    )
    next_specialized = next(
        (index for index in specialized if first_failed is not None and index > first_failed),
        len(ordered),
    )
    fallback_failed = (
        sum(
            event.kind == EventKind.SEARCH_NATIVE
            for event in ordered[first_failed + 1 : next_specialized]
        )
        if first_failed is not None
        else 0
    )
    search_keys = [
        _search_key(event)
        for event in ordered
        if event.kind in {EventKind.SEARCH_NATIVE, EventKind.SEARCH_JG, EventKind.SEARCH_BM25}
    ]
    repetitions = sum(count - 1 for count in Counter(search_keys).values() if count > 1)
    first_edit_timestamp = next(
        (event.ts_offset_ms for event in ordered if event.kind == EventKind.EDIT),
        None,
    )
    tokens = sum(
        int(row.get("token_count", row.get("input_tokens", row.get("tokens", 0))) or 0)
        for row in token_count_records
        if first_edit_timestamp is None
        or int(row.get("ts_offset_ms", row.get("timestamp_offset_ms", 0)) or 0)
        < first_edit_timestamp
    )
    indeterminate = coverage == "partial" and bool(missing_set)
    missing_tokens = "token_basis" in missing_set
    if indeterminate:
        first_path_value: int | str | None = "indeterminate"
        first_content_value: int | str | None = "indeterminate"
        first_direct_value: int | str | None = "indeterminate"
        calls_value: int | str | None = "indeterminate"
    else:
        first_path_value = ordered.index(path_event) if path_event else None
        first_content_value = ordered.index(content_event) if content_event else None
        first_direct_value = ordered.index(direct_event) if direct_event else None
        calls_value = first_path_value
    token_value: int | str | None = (
        "indeterminate"
        if missing_tokens
        else tokens if token_count_records
        else None
    )
    count_value: int | str = "indeterminate" if indeterminate else len(opened_unique)
    operation_value: int | str = (
        "indeterminate"
        if indeterminate
        else sum(bool(paths) for paths in opened_operations)
    )
    unique_value: int | str = "indeterminate" if indeterminate else len(opened_unique)
    success_fallback_value: int | str = "indeterminate" if indeterminate else fallback_success
    failed_fallback_value: int | str = "indeterminate" if indeterminate else fallback_failed
    repeated_value: int | str = "indeterminate" if indeterminate else repetitions
    specialized_value: int | str = "indeterminate" if indeterminate else len(specialized)
    return TraceMetrics(
        first_discovery_operation=discovery_value,
        first_gold_path_exposure=first_path_value,
        first_gold_content_exposure=first_content_value,
        first_direct_read=first_direct_value,
        calls_to_first_gold=calls_value,
        tokens_before_first_edit=token_value,
        non_reference_files_opened=count_value,
        non_reference_file_operations=operation_value,
        non_reference_unique_files=unique_value,
        fallback_calls_after_successful_specialized=success_fallback_value,
        fallback_calls_after_empty_or_error=failed_fallback_value,
        repeated_searches=repeated_value,
        specialized_query_count=specialized_value,
        trace_coverage=coverage,
        missing_dimensions=tuple(sorted(missing_set)),
    )


class TraceNormalizer:
    """Object-oriented facade for the DRAFT trace parser."""

    def parse(self, lines: Iterable[str], workspace: str | None = None) -> TraceParse:
        return parse_rollout_jsonl(lines, workspace)

    normalize = parse


normalize_trace = parse_rollout_jsonl
derive_trace_metrics = derive_metrics
redact_command = scrub_command
