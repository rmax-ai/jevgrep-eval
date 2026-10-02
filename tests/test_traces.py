from jevgrep_eval.traces import derive_metrics, parse_jsonl


def test_trace_partial_and_named_missing_dimensions():
    parsed = parse_jsonl(
        [
            '{"type":"tool_call","command":"jg search bug","ts_offset_ms":1,"result":{"matched":true,"excerpts":["x"]},"files_touched":["src/a.py"]}',
            '{"type":"unknown"}',
            "not json",
        ]
    )
    assert parsed.coverage == "partial"
    assert parsed.errors
    metrics = derive_metrics(parsed.events, {"src/a.py"}, coverage=parsed.coverage, missing_dimensions=parsed.missing_dimensions)
    assert metrics.first_gold_content_exposure == "indeterminate"
    assert "known_event_types" in metrics.missing_dimensions


def test_fallback_and_repeated_searches():
    parsed = parse_jsonl(
        [
            '{"command":"jg search bug","root":"src","result":{"matched":true,"successful":true}}',
            '{"command":"rg bug src","root":"src"}',
            '{"command":"rg bug src","root":"src"}',
        ]
    )
    metrics = derive_metrics(parsed.events, set())
    assert metrics.fallback_calls_after_successful_specialized == 2
    assert metrics.repeated_searches == 1


def test_ambiguous_discovery_is_indeterminate():
    parsed = parse_jsonl(['{"command":"pwd | rg bug","ts_offset_ms":1}'])
    metrics = derive_metrics(parsed.events, set())
    assert metrics.first_discovery_operation == "indeterminate"


def test_classify_command_detects_retrieval_tools_in_compound_commands():
    """Live regression (click-3533 a1 smoke): jg invoked inside compound commands
    classified as other_shell, so retrieval events and metered searches vanished."""
    from jevgrep_eval.models import EventKind
    from jevgrep_eval.traces import classify_command

    assert (
        classify_command("command -v jg || true; jg 'Click GC close' 2>&1 | head -80; ls")
        == EventKind.SEARCH_JG
    )
    assert classify_command("git status --short && jg 'query'") == EventKind.SEARCH_JG
    assert classify_command("rg 'pattern' src | head -20") == EventKind.SEARCH_NATIVE
    assert classify_command("cat a.py; rg b src") == EventKind.READ
    assert classify_command("bm25 'q'") == EventKind.SEARCH_BM25


def test_count_search_invocations_from_result_headers():
    """Count executed searches from output headers; skip dead invocations.

    Live regression: the a1 smoke's ledger reconciled $0.000 against one real
    metered search embedded in a compound command; a short-circuited ``jg`` and a
    missing-binary ``jg --help`` probe must NOT be counted.
    """
    from jevgrep_eval.traces import count_search_invocations

    events = [
        {"kind": "search_jg", "result": {"summary": "/usr/bin/bash: git: command not found\n"}},
        {"kind": "search_jg", "result": {"summary": "Jevgrep: 15 relevant files. ..."}},
        {"kind": "search_jg", "result": {"summary": "timeout: command not found\nstatus:127\n"}},
        {"kind": "search_jg", "result": {"summary": ""}},
        {"kind": "other_shell", "result": {"summary": ""}},
    ]
    assert count_search_invocations(events) == 2  # header + output-lost fallback
    assert count_search_invocations([]) == 0
    multi = [{"kind": "other_shell", "result": {"summary": "Jevgrep: a\nrest\nJevgrep: b\n"}}]
    assert count_search_invocations(multi) == 2
