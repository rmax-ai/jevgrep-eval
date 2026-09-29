from pathlib import Path

from jevgrep_eval.retrieval.bm25 import BM25Index, corpus_fingerprint
from jevgrep_eval.retrieval.chunking import chunk_text


def test_chunking_and_bm25_are_deterministic(tmp_path: Path):
    (tmp_path / "b.py").write_text("unrelated text\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("parse request safely\n", encoding="utf-8")
    assert chunk_text("one two three", size=2, overlap=1) == ["one two", "two three"]
    left = BM25Index.from_root(tmp_path)
    right = BM25Index.from_root(tmp_path)
    assert left.fingerprint == right.fingerprint == corpus_fingerprint(tmp_path)
    result = left.query("parse request", k=2, max_context_tokens=3)
    assert result.hits[0].path == "a.py"
    assert result.context_tokens <= 3


def test_path_filter(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("needle\n", encoding="utf-8")
    result = BM25Index.from_root(tmp_path).query("needle", path_filter="src")
    assert [hit.path for hit in result.hits] == ["src/a.py"]
