"""Deterministic report builder with strict simulated/live separation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import canonical_json, digest


class ReportRefusal(PermissionError):
    """A report cannot be built under the publication honesty rules."""


def _load_run(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid run artifact {path}: {exc}") from exc


def build_demo_report(
    runs_dir: Path,
    destination: Path,
    *,
    run_ids: list[str] | None = None,
) -> bytes:
    """Build a byte-stable protocol demonstration report.

    Every selected run must carry a simulated marker.  This function never
    converts live evidence into a demo artifact.
    """
    destination_resolved = destination.resolve()
    run_paths = [
        path
        for path in sorted(runs_dir.glob("**/*.json"))
        if path.resolve() != destination_resolved
    ]
    if run_ids is not None:
        wanted = set(run_ids)
        run_paths = [path for path in run_paths if path.stem in wanted or path.parent.name in wanted]
    rows: list[dict[str, Any]] = []
    for path in run_paths:
        row = _load_run(path)
        run_id = str(row.get("run_id", path.stem))
        marker = str(row.get("simulated", row.get("label", "")))
        if "mock" not in run_id.lower() and "simulated-fixture" not in marker:
            raise ReportRefusal(f"demo builder refuses non-mock run: {run_id}")
        rows.append(row)
    payload = {
        "title": "jevgrep-eval protocol demonstration",
        "label": "simulated-fixture",
        "honesty": "Mock outputs are mechanics drivers, never retriever or model quality evidence.",
        "runs": rows,
        "report_digest": "",
    }
    payload["report_digest"] = digest(payload, component="demo-report")
    content = canonical_json(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return content


def build_report(runs_dir: Path, destination: Path, *, demo: bool = False) -> bytes:
    if not demo:
        raise ReportRefusal("live report construction is deferred until W1b")
    return build_demo_report(runs_dir, destination)
