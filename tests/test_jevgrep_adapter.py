import json
from pathlib import Path

import pytest

from jevgrep_eval.retrieval.jevgrep import (
    JevgrepAdapter,
    JevgrepTimeout,
    MockJevgrepAdapter,
    parse_output,
)


def test_parse_counts_malformed_rows(tmp_path: Path):
    parsed = parse_output(
        json.dumps({"results": [{"path": "src/a.py"}, {"bad": True}]}),
        root=tmp_path,
    )
    assert parsed.malformed_count == 1
    assert parsed.result.no_cache


def test_parse_preserves_explicit_provider_ranks(tmp_path: Path):
    parsed = parse_output(
        json.dumps(
            {
                "results": [
                    {"path": "src/second.py", "rank": 2, "score": 100},
                    {"path": "src/first.py", "rank": 1, "score": 1},
                ]
            }
        ),
        root=tmp_path,
    )
    assert parsed.ranked_files == ("src/first.py", "src/second.py")
    assert [hit.rank for hit in parsed.result.hits] == [1, 2]
    assert parsed.rank_semantics == "verified"


def test_parse_does_not_invent_order_for_malformed_ranks(tmp_path: Path):
    parsed = parse_output(
        json.dumps(
            {
                "results": [
                    {"path": "src/first.py", "rank": "not-a-rank", "score": 1},
                    {"path": "src/second.py", "rank": 1, "score": 100},
                ]
            }
        ),
        root=tmp_path,
    )
    assert parsed.ranked_files == ("src/second.py",)
    assert parsed.result.malformed_output
    assert parsed.result.malformed_count == 1
    assert parsed.rank_semantics == "unordered"


def test_mock_is_labeled(tmp_path: Path):
    adapter = MockJevgrepAdapter({"bug": '{"results":[{"path":"a.py"}]}'})
    result = adapter.query("bug", tmp_path)
    assert result.error == "protocol demonstration: simulated-fixture"


def test_timeout_kills_process_group(tmp_path: Path):
    adapter = JevgrepAdapter(executable="python3")
    # The fake argv is intentionally not a valid jg invocation; this test
    # exercises argv construction through a sleeping Python stub in isolation
    # only when the executable is explicitly supplied.
    adapter.argv = lambda statement, k=10, no_cache=True: [
        "python3",
        "-c",
        "import time; time.sleep(5)",
    ]
    with pytest.raises(JevgrepTimeout):
        adapter.query("bug", tmp_path, timeout_s=0.01)
