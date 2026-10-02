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


def test_from_root_skips_workspace_scaffolding(tmp_path: Path):
    """Live regression (a3 smoke): the prepared workspace carries a .venv and
    pytest caches from the environment recipe; those must not enter the indexed
    corpus or ranked results (rg-based arms skip hidden dirs by default)."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text("needle lives here\n", encoding="utf-8")
    for name in (".venv", "__pycache__", "node_modules", ".pytest_cache"):
        directory = tmp_path / name / "lib"
        directory.mkdir(parents=True)
        (directory / "decoy.py").write_text("needle decoy\n", encoding="utf-8")
    index = BM25Index.from_root(tmp_path)
    result = index.query("needle", k=10)
    paths = [hit.path for hit in result.hits]
    assert "src/mod.py" in paths
    assert all(
        ".venv" not in path
        and "__pycache__" not in path
        and "node_modules" not in path
        and ".pytest_cache" not in path
        for path in paths
    )
    # A decoy-free twin tree must fingerprint identically: scaffolding content
    # must not contribute to the corpus digest.
    clean = tmp_path / "clean"
    (clean / "src").mkdir(parents=True)
    (clean / "src" / "mod.py").write_text("needle lives here\n", encoding="utf-8")
    assert BM25Index.from_root(clean).fingerprint == index.fingerprint
