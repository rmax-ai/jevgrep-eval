"""argv-list Codex harness with process-group timeout handling."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..util import canonical_json, digest
from .base import HarnessResult


class CodexHarnessError(RuntimeError):
    """A Codex invocation could not be constructed or completed."""


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    sanitized_env: dict[str, str]
    config_digest: str
    requested_model: str
    requested_effort: str
    invocation_digest: str

    @property
    def bytes(self) -> bytes:
        return canonical_json(
            {
                "argv": self.argv,
                "sanitized_env": self.sanitized_env,
                "config_digest": self.config_digest,
                "requested_model": self.requested_model,
                "requested_effort": self.requested_effort,
            }
        )


@dataclass(frozen=True)
class CodexResult(HarnessResult):
    """Codex-specific result retaining the exact invocation evidence."""

    argv: tuple[str, ...] = ()
    invocation_bytes: bytes = b""


def _sanitize_env(env: dict[str, str]) -> dict[str, str]:
    hidden = ("TOKEN", "KEY", "SECRET", "PASSWORD", "COOKIE", "AUTH")
    return {
        key: "<REDACTED>" if any(part in key.upper() for part in hidden) else value
        for key, value in sorted(env.items())
    }


def _effective_env(
    supplied: dict[str, str] | None,
    configured_allowlist: tuple[str, ...],
) -> dict[str, str]:
    source = dict(supplied) if supplied is not None else dict(os.environ)
    allowlist = configured_allowlist or (
        "PATH",
        "LANG",
        "LC_ALL",
        "TZ",
        "HOME",
        "CODEX_HOME",
    )
    return {key: source[key] for key in allowlist if key in source}


def load_harness_config(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CodexHarnessError(f"cannot load harness config: {exc}") from exc
    if not isinstance(payload, dict):
        raise CodexHarnessError("harness config must be a mapping")
    return payload


class CodexHarness:
    def __init__(
        self,
        executable: str = "codex",
        *,
        config: dict[str, Any] | None = None,
        env_allowlist: tuple[str, ...] = (),
    ) -> None:
        self.executable = executable
        self.config = config or {}
        self.env_allowlist = env_allowlist

    def assemble_invocation(
        self,
        prompt: str,
        *,
        model: str,
        effort: str,
        env: dict[str, str] | None = None,
    ) -> Invocation:
        command = self.config.get("command", [self.executable, "exec"])
        if isinstance(command, str):
            command = [command]
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise CodexHarnessError("harness command must be an argv list")
        sandbox = self.config.get("sandbox", "workspace-write")
        argv = [
            *command,
            "--json",
            "--skip-git-repo-check",
            "-s",
            sandbox,
            "--model",
            model,
            "-c",
            f"model_reasoning_effort={effort}",
            prompt,
        ]
        allowlist = self.env_allowlist or tuple(self.config.get("env_allowlist", ()))
        source_env = _effective_env(env, allowlist)
        sanitized = _sanitize_env(source_env)
        config_digest = digest(self.config, component="harness-config")
        invocation = Invocation(
            tuple(argv),
            sanitized,
            config_digest,
            model,
            effort,
            "",
        )
        return Invocation(
            invocation.argv,
            invocation.sanitized_env,
            invocation.config_digest,
            invocation.requested_model,
            invocation.requested_effort,
            digest(invocation.bytes, component="invocation"),
        )

    def run(
        self,
        prompt: str,
        cwd: Path,
        *,
        model: str,
        effort: str,
        timeout_s: float | None = None,
        env: dict[str, str] | None = None,
        session_path: Path | None = None,
    ) -> CodexResult:
        invocation = self.assemble_invocation(prompt, model=model, effort=effort, env=env)
        allowlist = self.env_allowlist or tuple(self.config.get("env_allowlist", ()))
        process_env = _effective_env(env, allowlist)
        timeout = timeout_s or float(self.config.get("timeout_seconds", 600))
        try:
            process = subprocess.Popen(
                list(invocation.argv),
                cwd=cwd,
                env=process_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise CodexHarnessError(str(exc)) from exc
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            stdout, stderr = process.communicate()
            raise TimeoutError(f"Codex timed out after {timeout}s") from exc
        path = session_path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(stdout)
            path.with_suffix(f"{path.suffix}.stderr").write_bytes(stderr)
        records = _token_records(stdout)
        return CodexResult(
            process.returncode,
            stdout,
            stderr,
            path,
            records,
            False,
            invocation.argv,
            invocation.bytes,
        )


def _token_records(stdout: bytes) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(value, dict) and (
            value.get("type") == "token_count" or "token_count" in value
        ):
            records.append(value)
    return tuple(records)
