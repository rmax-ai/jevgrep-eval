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
