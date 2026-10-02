"""Regressions for the bm25 arm staging (live-path bugs caught by the a3 smoke)."""

from pathlib import Path

from jevgrep_eval.live import stage_bm25


def test_stage_bm25_shim_contract(tmp_path: Path):
    """Live regressions (a3 smoke):
    - the shim shebang must be a shell that exists in the sandbox (/bin/sh is
      NOT mounted there — only bash; executing /bin/sh failed with ENOENT);
    - the exec'd interpreter must be the venv python, not the bare uv build
      (the resolved bare interpreter fails with ModuleNotFoundError for
      jevgrep_eval);
    - results are keyed to the sandbox index bind path /bm25.index;
    - "$@" forwards arguments so `bm25 -k N query` reaches argparse intact.
    """
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "mod.py").write_text(
        "def answer():\n    return 42\n", encoding="utf-8"
    )
    run_dir = tmp_path / "run"
    engine_venv = tmp_path / "engine-venv"

    tool, index = stage_bm25(
        workspace=workspace,
        run_dir=run_dir,
        engine_repo=tmp_path / "engine",
        engine_venv=engine_venv,
    )

    assert tool == run_dir / "tools" / "bm25"
    assert index == run_dir / "bm25.index"
    assert index.is_file()
    text = tool.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/bash\n")
    assert f"exec {engine_venv / 'bin' / 'python'}" in text
    assert "/bm25.index" in text
    assert '"$@"' in text
    assert tool.stat().st_mode & 0o111
