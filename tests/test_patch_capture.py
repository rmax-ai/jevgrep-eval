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
