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


FIXTURES = Path(__file__).parent / "fixtures" / "jg"


def test_argv_matches_pinned_jg_cli_contract():
    adapter = JevgrepAdapter()
    assert adapter.argv("find the bug") == ["jg", "--no-cache", "find the bug"]
    assert adapter.argv("find the bug", no_cache=False) == ["jg", "find the bug"]
    with pytest.raises(ValueError):
        adapter.argv("find the bug", k=0)


def test_parse_pinned_text_small_sample(tmp_path: Path):
    parsed = parse_output((FIXTURES / "text-small.txt").read_bytes(), root=tmp_path)
    assert parsed.ranked_files == (
        "tests/test_context.py",
        "tests/test_utils.py",
        "src/click/_utils.py",
    )
    assert [hit.rank for hit in parsed.result.hits] == [1, 2, 3]
    assert parsed.rank_semantics == "verified"
    assert parsed.result.coverage == "full"
    assert not parsed.result.malformed_output
    assert parsed.summary.startswith("Jevgrep: 3 relevant files.")


def test_parse_pinned_text_large_sample(tmp_path: Path):
    parsed = parse_output((FIXTURES / "text-large.txt").read_bytes(), root=tmp_path, k=25)
    assert len(parsed.ranked_files) == 20
    assert parsed.ranked_files[0] == "src/click/parser.py"
    assert parsed.ranked_files[1] == "src/click/core.py"
    assert [hit.rank for hit in parsed.result.hits] == list(range(1, 21))
    assert parsed.result.coverage == "full"


def test_parse_text_k_bounds_the_list(tmp_path: Path):
    parsed = parse_output((FIXTURES / "text-large.txt").read_bytes(), root=tmp_path, k=5)
    assert len(parsed.result.hits) == 5
    assert parsed.ranked_files[:2] == ("src/click/parser.py", "src/click/core.py")


def test_parse_text_malformed_item_flags_partial(tmp_path: Path):
    text = 'Jevgrep: 2 relevant files.\n- "ok.py" — helper\n- "broken item\nEnd file list.\n'
    parsed = parse_output(text, root=tmp_path)
    assert parsed.ranked_files == ("ok.py",)
    assert parsed.result.malformed_count == 2  # broken item + declared-count mismatch
    assert parsed.result.coverage == "partial"


def test_parse_text_missing_terminator_flags_partial(tmp_path: Path):
    text = 'Jevgrep: 1 relevant files.\n- "ok.py" — helper\n'
    parsed = parse_output(text, root=tmp_path)
    assert parsed.ranked_files == ("ok.py",)
    assert parsed.result.coverage == "partial"


def test_query_exit_2_is_partial_not_a_failure(tmp_path: Path):
    adapter = JevgrepAdapter(executable="python3")
    adapter.argv = lambda statement, k=10, no_cache=True: [
        "python3",
        "-c",
        "import sys; sys.stdout.write('Jevgrep: 1 relevant files.\\n- \"a.py\" \u2014 helper\\nEnd file list.\\n'); sys.exit(2)",
    ]
    result = adapter.query("bug", tmp_path)
    assert result.coverage == "partial"
    assert "exit 2" in (result.error or "")


def test_parse_text_invalid_header_flags_partial(tmp_path: Path):
    text = 'Jevgrep: five relevant files.\n- "ok.py" — helper\nEnd file list.\n'
    parsed = parse_output(text, root=tmp_path)
    assert parsed.ranked_files == ("ok.py",)
    assert parsed.result.coverage == "partial"


def test_parse_text_empty_missing_terminator_flags_partial(tmp_path: Path):
    text = "Jevgrep: 5 relevant files.\nSymbols use name@start-end.\n"
    parsed = parse_output(text, root=tmp_path)
    assert parsed.ranked_files == ()
    assert parsed.result.coverage == "partial"


def test_parse_text_bullet_shaped_junk_flags_partial(tmp_path: Path):
    text = 'Jevgrep: 2 relevant files.\n* "a.py" — helper\n- "b.py" — helper\nEnd file list.\n'
    parsed = parse_output(text, root=tmp_path)
    assert parsed.ranked_files == ("b.py",)
    assert parsed.result.coverage == "partial"


def test_parse_text_declared_count_mismatch_flags_partial(tmp_path: Path):
    text = 'Jevgrep: 3 relevant files.\n- "a.py" — x\n- "b.py" — y\nEnd file list.\n'
    parsed = parse_output(text, root=tmp_path)
    assert parsed.ranked_files == ("a.py", "b.py")
    assert parsed.result.coverage == "partial"


def test_parse_text_wellformed_zero_hit_stays_full(tmp_path: Path):
    text = "Jevgrep: 0 relevant files.\nEnd file list.\n"
    parsed = parse_output(text, root=tmp_path)
    assert parsed.ranked_files == ()
    assert parsed.result.coverage == "full"
