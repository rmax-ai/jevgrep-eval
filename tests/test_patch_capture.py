from pathlib import Path

import pytest

from jevgrep_eval.materialize import snapshot
from jevgrep_eval.runner import MalformedPatchError, capture_patch, replay_patch


def test_patch_capture_replays_binary_add_delete(mini_tree: Path, tmp_path: Path):
    after = tmp_path / "after"
    import shutil

    shutil.copytree(mini_tree, after)
    (after / "src" / "app.py").write_bytes(b"\x00\xff\n")
    (after / "README.md").unlink()
    (after / "new.bin").write_bytes(b"\x01\x02")
    captured = capture_patch(mini_tree, after)
    replay = tmp_path / "replay"
    replayed = replay_patch(mini_tree, captured.patch, replay)
    assert captured.replay_equal
    assert replayed.workspace_digest == snapshot(after).workspace_digest


def test_empty_patch_is_valid(mini_tree: Path):
    captured = capture_patch(mini_tree, mini_tree)
    assert captured.empty
    assert captured.replay_equal


def test_escape_symlink_is_rejected(mini_tree: Path, tmp_path: Path):
    (mini_tree / "escape").symlink_to(tmp_path)
    with pytest.raises(MalformedPatchError):
        capture_patch(mini_tree, mini_tree)


def test_patch_capture_ignores_tool_generated_artifacts(mini_tree: Path, tmp_path: Path):
    """Live regression: agents exercising test tooling populate gitignored caches.

    The post-run tree contained ``src/__pycache__`` and ``.pytest_cache`` while the
    captured patch did not (the project's .gitignore hid them from ``git add``), so
    patch replay diverged from the post-run tree (observed live as
    ``terminal_status=malformed_patch`` on the click-3533 a0 smoke).
    """
    import shutil

    gitignore = "__pycache__/\n.pytest_cache/\n.venv/\n"
    (mini_tree / ".gitignore").write_text(gitignore, encoding="utf-8")
    after = tmp_path / "after"
    shutil.copytree(mini_tree, after, symlinks=True)
    # The agent edits source ...
    (after / "src" / "app.py").write_text("def answer():\n    return 2\n", encoding="utf-8")
    # ... and exercising the project's tooling leaves populated caches behind.
    pycache = after / "src" / "__pycache__"
    pycache.mkdir()
    (pycache / "app.cpython-312.pyc").write_bytes(b"\x00binarycache")
    pytest_cache = after / ".pytest_cache" / "v" / "cache"
    pytest_cache.mkdir(parents=True)
    (pytest_cache / "nodeids").write_text("[]\n", encoding="utf-8")
    venv_bin = after / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(tmp_path / "outside" / "python")

    captured = capture_patch(mini_tree, after)
    assert captured.replay_equal
    assert b"return 2" in captured.patch
    assert b"__pycache__" not in captured.patch
    assert b".pytest_cache" not in captured.patch
    assert b".venv" not in captured.patch
    replay = tmp_path / "replay"
    replayed = replay_patch(mini_tree, captured.patch, replay)
    assert replayed.workspace_digest == snapshot(after).workspace_digest


def test_project_ignored_changes_still_capture(mini_tree: Path, tmp_path: Path):
    """Scratch capture is scoped by WORKSPACE_EXCLUDED_NAMES, not the project .gitignore.

    A file ignored only by the project (here ``dist/``) that changed during the run must
    still appear in the patch -- otherwise replay would diverge from the post-run tree.
    """
    import shutil

    (mini_tree / ".gitignore").write_text("dist/\n", encoding="utf-8")
    after = tmp_path / "after"
    shutil.copytree(mini_tree, after, symlinks=True)
    (after / "dist").mkdir()
    (after / "dist" / "out.txt").write_text("built by agent\n", encoding="utf-8")

    captured = capture_patch(mini_tree, after)
    assert captured.replay_equal
    assert b"built by agent" in captured.patch
