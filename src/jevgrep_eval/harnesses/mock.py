"""Deterministic mock harness for mechanics and protocol demonstrations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .base import HarnessResult


@dataclass(frozen=True)
class MockResult(HarnessResult):
    simulated: bool = True
    patch_applied: bool = False
    events: tuple[dict[str, object], ...] = ()
    output: str = "protocol demonstration: simulated-fixture"


class MockHarness:
    simulated_marker = "simulated-fixture"

    def __init__(self, events: Iterable[dict[str, object]] = ()) -> None:
        self.fixture_events = tuple(events)

    def run(
        self,
        prompt: str,
        cwd: Path,
        *,
        apply_patch: bool = False,
        **_: object,
    ) -> MockResult:
        del cwd
        event_rows = list(self.fixture_events)
        if not event_rows:
            event_rows = [
                {
                    "seq": 0,
                    "command": "pwd",
                    "ts_offset_ms": 0,
                    "files_touched": [],
                    "result": {},
                }
            ]
        if apply_patch:
            marker = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
            event_rows.append(
                {
                    "seq": len(event_rows),
                    "command": f"echo simulated-{marker}",
                    "ts_offset_ms": len(event_rows),
                    "files_touched": [],
                    "result": {},
                }
            )
        stdout = ("\n".join(json.dumps(row, sort_keys=True) for row in event_rows) + "\n").encode()
        return MockResult(
            returncode=0,
            stdout=stdout,
            stderr=b"",
            session_path=None,
            token_count_records=(),
            simulated=True,
            patch_applied=apply_patch,
            events=tuple(event_rows),
        )
