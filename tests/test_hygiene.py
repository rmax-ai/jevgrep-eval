from pathlib import Path

from jevgrep_eval.harnesses.mock import MockHarness


def test_mock_path_has_no_network_dependency(tmp_path: Path):
    result = MockHarness().run("protocol demonstration", tmp_path)
    assert result.simulated


def test_public_artifacts_do_not_contain_private_markers():
    root = Path(__file__).parents[1]
    for path in [root / "README.md", root / "docs", root / "configs"]:
        paths = [path] if path.is_file() else sorted(path.rglob("*"))
        for candidate in paths:
            if candidate.is_file():
                # Host-local files (*.local.yaml) are gitignored operator state, not
                # public artifacts; they may legitimately carry host paths.
                if candidate.name.endswith(".local.yaml"):
                    continue
                text = candidate.read_text(encoding="utf-8")
                assert "bebb7" not in text
                assert "/home/" not in text
