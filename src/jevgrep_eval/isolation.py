"""Bubblewrap argv recipes and probe artifacts.

The recipes are validated live on the run host as of Stage-0.5 V4 (2026-09-29):
connectivity-fail, deny-read, Python test execution inside Tier A, group-kill
quiescence, and Tier-B provider reachability all pass (evidence: ops records +
`configs/isolation/tier_*.yaml` validation lines). This module generates
recipes and records probe scripts; it does not execute them at runtime.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ProbeArtifact:
    name: str
    script: str
    tier: str


@dataclass(frozen=True)
class ProbeResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class IsolationProfile:
    tier: str
    unshare_net: bool
    unshare_user: bool
    binaries: tuple[str, ...]
    readonly_binds: tuple[str, ...]


def load_profile(path: Path) -> IsolationProfile:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load isolation profile: {exc}") from exc
    tier = str(payload.get("tier", path.stem.rsplit("_", 1)[-1])).upper()
    if tier not in {"A", "B"}:
        raise ValueError(f"unknown isolation tier: {tier}")
    return IsolationProfile(
        tier=tier,
        unshare_net=bool(payload.get("unshare_net", tier == "A")),
        unshare_user=bool(payload.get("unshare_user", True)),
        binaries=tuple(str(value) for value in payload.get("binaries", [])),
        readonly_binds=tuple(str(value) for value in payload.get("readonly_binds", [])),
    )


_HOST_BINDING_KEYS = (
    "home",
    "tools",
    "uv",
    "node",
    "codex_home_source",
    "provider_credentials",
)
_HOST_BINDING_EXAMPLE = "configs/isolation/host_bindings.example.yaml"


def _expand_binding(value: str, replacements: dict[str, str]) -> str:
    result = value
    for key, replacement in replacements.items():
        result = result.replace(f"<{key}>", replacement)
    if "<" in result or ">" in result:
        raise ValueError(f"unresolved host binding placeholder: {value}")
    path = Path(result).expanduser()
    if not path.is_absolute():
        raise ValueError(f"host binding must be absolute: {value}")
    return str(path.resolve())


def load_host_bindings(path: Path) -> dict[str, str]:
    """Load the operator's absolute host paths without touching those paths."""
    if not path.is_file():
        raise ValueError(
            f"host bindings file is missing: {path}; copy "
            f"{_HOST_BINDING_EXAMPLE} to configs/isolation/host_bindings.local.yaml "
            "and fill the host-specific paths"
        )
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load host bindings: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError("host bindings must be a mapping")
    missing = [key for key in _HOST_BINDING_KEYS if key not in payload]
    if missing:
        raise ValueError(f"host bindings missing required keys: {', '.join(missing)}")
    if any(not isinstance(payload[key], str) for key in _HOST_BINDING_KEYS):
        raise ValueError("host binding values must be strings")

    home = str(Path.home().expanduser().resolve())
    replacements = {"home": home}
    result: dict[str, str] = {}
    for key in _HOST_BINDING_KEYS:
        result[key] = _expand_binding(str(payload[key]), {**replacements, **result})
    # Preserve additional string entries for forward-compatible local files,
    # while keeping the public return type strict.
    for key, value in payload.items():
        if key in result:
            continue
        if not isinstance(value, str):
            raise TypeError(f"host binding {key} must be a string")
        result[str(key)] = _expand_binding(value, {**replacements, **result})
    return result


def _absolute_path(value: Path | str, label: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute: {value}")
    return str(path.resolve())


def _ro_bind(argv: list[str], source: str, target: str) -> None:
    argv.extend(["--ro-bind", source, target])


def agent_bwrap_argv(
    *,
    workspace: Path,
    codex_home: Path,
    bindings: dict[str, str],
    engine_repo: Path,
    engine_venv: Path,
    bm25_tool: Path | None = None,
    bm25_index: Path | None = None,
) -> list[str]:
    """Assemble the validated Tier-B agent command without executing it."""
    workspace_path = _absolute_path(workspace, "workspace")
    codex_home_path = _absolute_path(codex_home, "codex_home")
    engine_repo_path = _absolute_path(engine_repo, "engine_repo")
    engine_venv_path = _absolute_path(engine_venv, "engine_venv")
    required = set(_HOST_BINDING_KEYS)
    missing = sorted(required - bindings.keys())
    if missing:
        raise ValueError(f"host bindings missing required keys: {', '.join(missing)}")
    resolved = {
        key: _absolute_path(bindings[key], f"bindings[{key!r}]")
        for key in _HOST_BINDING_KEYS
    }
    if (bm25_tool is None) != (bm25_index is None):
        raise ValueError("bm25_tool and bm25_index must be provided together")

    node = resolved["node"]
    tools = resolved["tools"]
    uv = resolved["uv"]
    argv = [
        "bwrap",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup",
        "--die-with-parent",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]

    # Keep host mounts sorted by their target path.  The fixed system mounts
    # are part of the validated recipe, while host mounts are read-only.
    tool_binaries = (
        "awk",
        "bash",
        "cat",
        "env",
        "find",
        "grep",
        "head",
        "id",
        "ls",
        "mawk",
        "python3",
        "python3.13",
        "sed",
        "tail",
        "wc",
    )
    mounts = [
        ("/etc/hosts", "/etc/hosts"),
        ("/etc/nsswitch.conf", "/etc/nsswitch.conf"),
        ("/etc/resolv.conf", "/etc/resolv.conf"),
        ("/etc/ssl", "/etc/ssl"),
        ("/usr/lib", "/usr/lib"),
        *(
            (f"/usr/bin/{name}", f"/usr/bin/{name}")
            for name in tool_binaries
        ),
        (f"{tools}/rg", f"{tools}/rg"),
        (f"{uv}/python/cpython-3.12-linux-aarch64-gnu", f"{uv}/python/cpython-3.12-linux-aarch64-gnu"),
        (f"{uv}/python/cpython-3.12.13-linux-aarch64-gnu", f"{uv}/python/cpython-3.12.13-linux-aarch64-gnu"),
        (node, node),
    ]
    for source, target in sorted(mounts, key=lambda pair: pair[1]):
        _ro_bind(argv, source, target)

    argv.extend(
        [
            "--bind",
            workspace_path,
            "/workspace",
            "--bind",
            codex_home_path,
            "/codex-home",
            "--chdir",
            "/workspace",
            "--setenv",
            "PATH",
            # /usr/local/bin carries the optional bm25 shim bind; keep the env
            # uniform across arms (a missing dir on PATH is harmless).
            f"{node}/bin:/usr/local/bin:/workspace/.venv/bin:/usr/bin:/bin",
            "--setenv",
            "HOME",
            "/codex-home",
            "--setenv",
            "CODEX_HOME",
            "/codex-home",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--setenv",
            "TERM",
            "dumb",
        ]
    )
    _ro_bind(argv, resolved["provider_credentials"], "/codex-home/.config/jevgrep")
    if bm25_tool is not None and bm25_index is not None:
        bm25_tool_path = _absolute_path(bm25_tool, "bm25_tool")
        bm25_index_path = _absolute_path(bm25_index, "bm25_index")
        _ro_bind(argv, bm25_tool_path, "/usr/local/bin/bm25")
        _ro_bind(argv, bm25_index_path, "/bm25.index")
        _ro_bind(argv, engine_repo_path, engine_repo_path)
        _ro_bind(argv, engine_venv_path, engine_venv_path)
    return argv


def bwrap_argv(
    workspace: Path,
    *,
    tier: str = "A",
    binaries: Iterable[Path | str] = (),
    readonly_binds: Iterable[Path | str] = (),
    unshare_net: bool | None = None,
    unshare_user: bool | None = None,
) -> list[str]:
    """Generate a deterministic argv list without invoking bubblewrap."""
    normalized_tier = tier.upper()
    if normalized_tier not in {"A", "B"}:
        raise ValueError("tier must be A or B")
    if not workspace.is_absolute():
        raise ValueError("workspace must be absolute")
    network = normalized_tier == "A" if unshare_net is None else unshare_net
    user = True if unshare_user is None else unshare_user
    argv = ["bwrap"]
    if normalized_tier == "A" and network and user:
        argv.append("--unshare-all")
    else:
        if user:
            argv.append("--unshare-user")
        if network:
            argv.append("--unshare-net")
        argv.extend(["--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-cgroup"])
    argv.extend(
        [
            "--die-with-parent",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
        ]
    )
    for bind in sorted({str(Path(item)) for item in readonly_binds}):
        argv.extend(["--ro-bind", bind, bind])
    for binary in sorted({str(Path(item)) for item in binaries}):
        path = Path(binary)
        argv.extend(["--ro-bind", str(path), str(path)])
    argv.extend(["--bind", str(workspace), "/workspace", "--chdir", "/workspace"])
    return argv


def argv_from_profile(workspace: Path, profile: IsolationProfile) -> list[str]:
    return bwrap_argv(
        workspace,
        tier=profile.tier,
        binaries=profile.binaries,
        readonly_binds=profile.readonly_binds,
        unshare_net=profile.unshare_net,
        unshare_user=profile.unshare_user,
    )


def negative_connectivity_probe_script() -> str:
    return (
        "# protocol probe artifact; result is recorded, not executed by the engine\n"
        "python3 -c 'import socket; socket.create_connection((\"198.51.100.1\", 9), 1)'\n"
        "getent hosts example.invalid\n"
    )


def deny_read_probe_script() -> str:
    return (
        "# protocol probe artifact; result is recorded, not executed by the engine\n"
        "test ! -r /benchmark/corpus/gold\n"
        "test ! -r /benchmark/hidden-tests\n"
    )


def probe_artifacts(tier: str) -> tuple[ProbeArtifact, ...]:
    normalized_tier = tier.upper()
    if normalized_tier not in {"A", "B"}:
        raise ValueError("tier must be A or B")
    artifacts = [
        ProbeArtifact("deny-read", deny_read_probe_script(), normalized_tier),
    ]
    if normalized_tier == "A":
        artifacts.append(
            ProbeArtifact("negative-connectivity", negative_connectivity_probe_script(), normalized_tier)
        )
    return tuple(artifacts)


def deny_read_probe(path: Path) -> ProbeResult:
    """Record a caller-provided probe result without executing a probe."""
    return ProbeResult("deny-read", False, f"not executed: {path}")


def network_denial_probe() -> ProbeResult:
    """Return an explicit not-executed result for the generated artifact."""
    return ProbeResult("network-denial", False, "not executed; Stage 0.5 probe required")


generate_bwrap_argv = bwrap_argv
generate_probe_artifacts = probe_artifacts
