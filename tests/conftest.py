"""Synthetic, offline-only fixtures for the engine test suite."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def mini_tree(tmp_path: Path) -> Path:
    root = tmp_path / "base"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def answer():\n    return 1\n", encoding="utf-8")
    (root / "README.md").write_text("synthetic fixture\n", encoding="utf-8")
    return root


@pytest.fixture
def git_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "fixture"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"],
        check=True,
    )
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "--quiet", "-m", "fixture"], check=True)
    return root


@pytest.fixture
def task_case():
    from jevgrep_eval.models import TaskCase

    return TaskCase(
        task_id="task-1",
        repo_id="repo-1",
        base_sha="base",
        gold_sha="gold",
        task_class="bugfix",
        statement="return the expected value",
        hidden_test_patch="hidden.patch",
        test_runner="pytest",
        test_command=["python3", "-c", "raise SystemExit(0)"],
        stratum="synthetic",
    )
