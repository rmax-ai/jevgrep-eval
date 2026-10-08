"""Common harness result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class HarnessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    session_path: Path | None
    token_count_records: tuple[dict[str, object], ...]
    simulated: bool = False


class Harness(Protocol):
    def run(self, prompt: str, cwd: Path, **kwargs: object) -> HarnessResult:
        """Run one non-interactive harness invocation."""
