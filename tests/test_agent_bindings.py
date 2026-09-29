from pathlib import Path

import pytest

from jevgrep_eval.isolation import agent_bwrap_argv, load_host_bindings


def _bindings(tmp_path: Path) -> dict[str, str]:
    return {
        "home": str(tmp_path / "home"),
        "tools": str(tmp_path / "tools"),
        "uv": str(tmp_path / "uv"),
        "node": str(tmp_path / "node"),
        "codex_home_source": str(tmp_path / "codex-source"),
        "provider_credentials": str(tmp_path / "credentials"),
    }


def _bind_targets(argv: list[str]) -> set[tuple[str, str]]:
    return {
        (argv[index + 1], argv[index + 2])
        for index, value in enumerate(argv)
        if value == "--ro-bind"
    }


def test_agent_argv_matches_validated_recipe(tmp_path: Path):
    bindings = _bindings(tmp_path)
    workspace = tmp_path / "workspace"
    codex_home = tmp_path / "codex-home"
    engine_repo = tmp_path / "engine"
    engine_venv = tmp_path / "engine-venv"
    argv = agent_bwrap_argv(
        workspace=workspace,
        codex_home=codex_home,
        bindings=bindings,
        engine_repo=engine_repo,
        engine_venv=engine_venv,
    )
    assert {
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup",
    } <= set(argv)
    assert ("usr/bin", "/bin") not in _bind_targets(argv)
    assert ["--symlink", "usr/bin", "/bin"] == argv[argv.index("--symlink") : argv.index("--symlink") + 3]
    assert ["--symlink", "usr/lib", "/lib"] == argv[
        argv.index("--symlink", argv.index("--symlink") + 1) :
        argv.index("--symlink", argv.index("--symlink") + 1) + 3
    ]
    targets = _bind_targets(argv)
    assert ("/etc/ssl", "/etc/ssl") in targets
    assert (str(workspace.resolve()), "/workspace") in {
        (argv[index + 1], argv[index + 2])
        for index, value in enumerate(argv)
        if value == "--bind"
    }
    assert (str(codex_home.resolve()), "/codex-home") in {
        (argv[index + 1], argv[index + 2])
        for index, value in enumerate(argv)
        if value == "--bind"
    }
    for name, value in (
        ("PATH", f"{bindings['node']}/bin:/workspace/.venv/bin:/usr/bin:/bin"),
        ("HOME", "/codex-home"),
        ("CODEX_HOME", "/codex-home"),
        ("LANG", "C.UTF-8"),
        ("TERM", "dumb"),
    ):
        index = argv.index(name)
        assert argv[index - 1] == "--setenv"
        assert argv[index + 1] == value
    assert "/workspace/codex-home" not in argv


def test_bm25_mounts_are_optional_and_sorted(tmp_path: Path):
    bindings = _bindings(tmp_path)
    common = {
        "workspace": tmp_path / "workspace",
        "codex_home": tmp_path / "codex-home",
        "bindings": bindings,
        "engine_repo": tmp_path / "engine",
        "engine_venv": tmp_path / "engine-venv",
    }
    without = agent_bwrap_argv(**common)
    with_bm25 = agent_bwrap_argv(
        **common,
        bm25_tool=tmp_path / "tools" / "bm25",
        bm25_index=tmp_path / "bm25.index",
    )
    assert "/usr/local/bin/bm25" not in without
    assert "/bm25.index" not in without
    assert str(common["engine_repo"]) not in without
    assert (str((tmp_path / "tools" / "bm25").resolve()), "/usr/local/bin/bm25") in _bind_targets(with_bm25)
    assert (str((tmp_path / "bm25.index").resolve()), "/bm25.index") in _bind_targets(with_bm25)
    assert (str((tmp_path / "engine").resolve()), str((tmp_path / "engine").resolve())) in _bind_targets(with_bm25)
    assert (str((tmp_path / "engine-venv").resolve()), str((tmp_path / "engine-venv").resolve())) in _bind_targets(with_bm25)
    assert with_bm25 == agent_bwrap_argv(**common, bm25_index=tmp_path / "bm25.index", bm25_tool=tmp_path / "tools" / "bm25")


def test_missing_host_bindings_guides_to_example():
    with pytest.raises(ValueError, match="host_bindings\\.example\\.yaml"):
        load_host_bindings(Path("/definitely/missing/host_bindings.yaml"))
