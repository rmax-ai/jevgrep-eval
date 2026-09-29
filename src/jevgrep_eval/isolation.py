"""Bubblewrap argv recipes and probe artifacts.

The exact recipes require Stage 0.5 V5 validation on the target host,
including a Python test runner inside Tier A.  This module generates recipes
and records probe scripts; it does not claim that a recipe was validated.
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
