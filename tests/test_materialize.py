from pathlib import Path

from jevgrep_eval.materialize import materialize, snapshot


def test_materialize_is_git_free_and_stable(git_fixture: Path, tmp_path: Path):
    first = materialize(git_fixture, tmp_path / "one")
    second = materialize(git_fixture, tmp_path / "two")
    assert first.workspace_digest == second.workspace_digest
    assert not (tmp_path / "one" / ".git").exists()
    assert snapshot(tmp_path / "one").workspace_digest == first.workspace_digest


def test_gold_swap_does_not_change_agent_tree(mini_tree: Path, tmp_path: Path):
    one = materialize(mini_tree, tmp_path / "one")
    (tmp_path / "gold.txt").write_text("gold one", encoding="utf-8")
    two = materialize(mini_tree, tmp_path / "two")
    (tmp_path / "gold.txt").write_text("gold two", encoding="utf-8")
    assert one.workspace_digest == two.workspace_digest


def test_nested_corpus_evaluator_artifacts_are_filtered_without_name_collisions(
    mini_tree: Path,
    tmp_path: Path,
):
    corpus = mini_tree / "corpus"
    (corpus / "gold").mkdir(parents=True)
    (corpus / "nested" / "hidden").mkdir(parents=True)
    (corpus / "evaluator").mkdir()
    (corpus / "notes.py").write_text("SOURCE = True\n", encoding="utf-8")
    (mini_tree / "src" / "gold_parser.py").write_text("def parse(): pass\n", encoding="utf-8")
    (corpus / "gold" / "answer.py").write_text("SECRET = True\n", encoding="utf-8")
    (corpus / "nested" / "hidden" / "test_secret.py").write_text(
        "assert False\n", encoding="utf-8"
    )
    (corpus / "evaluator" / "result.json").write_text("{}", encoding="utf-8")

    destination = tmp_path / "materialized"
    materialize(mini_tree, destination)

    assert (destination / "corpus" / "notes.py").is_file()
    assert (destination / "src" / "gold_parser.py").is_file()
    assert not (destination / "corpus" / "gold").exists()
    assert not (destination / "corpus" / "nested" / "hidden").exists()
    assert not (destination / "corpus" / "evaluator").exists()
    assert snapshot(destination).workspace_digest == materialize(
        mini_tree, tmp_path / "materialized-again"
    ).workspace_digest
