"""argv-guarded adapter for the pinned Jevgrep CLI.

Live provider calls are deliberately opt-in.  The mock adapter is a protocol
demonstration and never represents retriever or model quality.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import RetrievalHit, RetrievalResult
from ..util import normalize_path
from .chunking import tokenize


class JevgrepError(RuntimeError):
    """Jevgrep is unavailable, timed out, or returned invalid output."""


class JevgrepTimeout(JevgrepError):
    """The Jevgrep process group exceeded its wall-clock budget."""


@dataclass(frozen=True)
class ParsedJevgrep:
    result: RetrievalResult
    summary: str
    ranked_files: tuple[str, ...]
    excerpts: tuple[str, ...]
    malformed_count: int
    rank_semantics: str = "unordered"


def _parse_row(
    row: Any,
    root: Path,
) -> tuple[RetrievalHit | None, str | None, bool, bool]:
    if isinstance(row, str):
        row = {"path": row}
    if not isinstance(row, dict):
        return None, "result is not an object", False, False
    raw_path = row.get("path", row.get("file", row.get("file_path", "")))
    if not isinstance(raw_path, str) or not raw_path:
        return None, "result has no path", False, False
    try:
        raw_path_obj = Path(raw_path)
        root = root.resolve()
        relative = (
            normalize_path(raw_path_obj.resolve(strict=False).relative_to(root).as_posix())
            if raw_path_obj.is_absolute()
            else normalize_path(raw_path)
        )
    except ValueError:
        return None, "result path is not safely relative to root", False, False
    if relative == "":
        return None, "empty result path", False, False
    try:
        score = float(row.get("score", 0.0))
    except (TypeError, ValueError):
        return None, "invalid score", False, False
    rank_present = "rank" in row
    raw_rank = row.get("rank", 0)
    rank_malformed = False
    if not rank_present:
        rank = 0
    elif isinstance(raw_rank, bool):
        return None, "invalid rank", True, True
    elif isinstance(raw_rank, int):
        rank = raw_rank
    elif isinstance(raw_rank, str) and raw_rank.strip().isdigit():
        rank = int(raw_rank.strip())
    else:
        return None, "invalid rank", True, True
    if rank_present and rank < 1:
        return None, "rank must be positive", True, True
    return (
        RetrievalHit(
            path=relative,
            score=score,
            rank=rank or 1,
            chunk_id=str(row["chunk_id"]) if row.get("chunk_id") is not None else None,
            line_start=int(row["line_start"]) if row.get("line_start") is not None else None,
            line_end=int(row["line_end"]) if row.get("line_end") is not None else None,
            preview=str(row.get("preview", row.get("excerpt", ""))),
        ),
        None,
        rank_present,
        rank_malformed,
    )


def parse_output(
    stdout: bytes | str,
    *,
    root: Path,
    task_id: str = "",
    k: int = 10,
    max_context_tokens: int = 400,
    no_cache: bool = True,
    truncated: bool = False,
) -> ParsedJevgrep:
    """Parse common JSON and JSONL response shapes without dropping failures."""
    if isinstance(stdout, bytes):
        text = stdout.decode("utf-8", errors="replace")
    else:
        text = stdout
    malformed = 0
    summary = ""
    excerpts: list[str] = []
    rows: list[Any] = []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        for line in text.splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1
        payload = None
    if isinstance(payload, dict):
        summary = str(payload.get("summary", payload.get("message", "")))
        raw_excerpts = payload.get("excerpts", [])
        if isinstance(raw_excerpts, list):
            excerpts = [str(item) for item in raw_excerpts]
        rows = payload.get("results", payload.get("ranked_files", payload.get("files", [])))
        if not isinstance(rows, list):
            rows = []
            malformed += 1
    elif isinstance(payload, list):
        rows = payload
    elif payload is not None:
        malformed += 1
    parsed_rows: list[tuple[RetrievalHit, bool]] = []
    rank_data_malformed = False
    seen: set[str] = set()
    for row in rows:
        hit, error, rank_present, row_rank_malformed = _parse_row(row, root)
        if error:
            malformed += 1
            rank_data_malformed |= row_rank_malformed
            continue
        assert hit is not None
        if hit.path in seen:
            continue
        seen.add(hit.path)
        parsed_rows.append((hit, rank_present))
    has_explicit_ranks = bool(parsed_rows) and all(
        rank_present for _, rank_present in parsed_rows
    )
    has_any_explicit_ranks = any(rank_present for _, rank_present in parsed_rows)
    has_scores = any(hit.score != 0.0 for hit, _ in parsed_rows)
    if has_any_explicit_ranks and not has_explicit_ranks:
        # A partial rank column is not enough to justify a score-based
        # reorder; retain the provider's sequence and mark it unverified.
        rank_data_malformed = True
        malformed += 1
    if has_explicit_ranks and len({hit.rank for hit, _ in parsed_rows}) != len(parsed_rows):
        # Duplicate ranks are not a trustworthy ordering signal.  Retain the
        # provider's sequence rather than silently inventing one.
        rank_data_malformed = True
        malformed += 1
    if has_explicit_ranks and not rank_data_malformed:
        parsed_rows.sort(key=lambda row: (row[0].rank, -row[0].score, row[0].path))
        rank_semantics = "verified"
    elif has_scores and not rank_data_malformed:
        parsed_rows.sort(key=lambda row: (-row[0].score, row[0].path))
        rank_semantics = "verified"
    else:
        rank_semantics = "unordered"
    hits = [
        hit if has_explicit_ranks else hit.model_copy(update={"rank": index + 1})
        for index, (hit, _) in enumerate(parsed_rows[:k])
    ]
    context = min(
        max_context_tokens,
        sum(len(tokenize(hit.preview)) for hit in hits),
    )
    result = RetrievalResult(
        task_id=task_id,
        backend="jevgrep",
        hits=hits,
        returned_context_bytes=len(text.encode("utf-8")),
        malformed_output=malformed > 0 or truncated,
        malformed_count=malformed,
        no_cache=no_cache,
        coverage="partial" if malformed or truncated else "full",
        token_estimator="utf8-bytes-per-four",
        token_estimate=context,
        context_tokens=context,
        error=(
            f"{malformed} malformed output item(s)"
            if malformed
            else "output truncated at configured byte bound"
            if truncated
            else None
        ),
        ranked_files=[hit.path for hit in hits],
        excerpts=[hit.preview for hit in hits],
        summary=summary,
        rank_semantics=rank_semantics,
    )
    return ParsedJevgrep(
        result,
        summary,
        tuple(hit.path for hit in hits),
        tuple(excerpts),
        malformed,
        rank_semantics,
    )


def _run_process(
    argv: list[str],
    cwd: Path,
    *,
    timeout_s: float,
    env: dict[str, str] | None = None,
    max_output_bytes: int = 1_000_000,
) -> tuple[bytes, bytes, int, bool]:
    if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
        raise JevgrepError("argv contains an invalid argument")
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        # communicate again reaps pipe readers after descendants exit.
        stdout, stderr = process.communicate()
        raise JevgrepTimeout(f"Jevgrep timed out after {timeout_s}s") from exc
    truncated = len(stdout) > max_output_bytes or len(stderr) > max_output_bytes
    return stdout[:max_output_bytes], stderr[:max_output_bytes], process.returncode, truncated


class JevgrepAdapter:
    def __init__(
        self,
        executable: str = "jg",
        *,
        version: str = "0.4.3",
        max_output_bytes: int = 1_000_000,
    ) -> None:
        if not executable or "\x00" in executable:
            raise ValueError("executable must be one argv item")
        self.executable = executable
        self.version = version
        self.max_output_bytes = max_output_bytes

    def argv(self, statement: str, *, k: int = 10, no_cache: bool = True) -> list[str]:
        if k <= 0:
            raise ValueError("k must be positive")
        argv = [self.executable, "search"]
        if no_cache:
            argv.append("--no-cache")
        argv.extend(["--json", "--limit", str(k), statement])
        return argv

    def query(
        self,
        statement: str,
        root: Path,
        *,
        k: int = 10,
        task_id: str = "",
        timeout_s: float = 120,
        no_cache: bool = True,
        env: dict[str, str] | None = None,
    ) -> RetrievalResult:
        if not root.is_dir():
            raise JevgrepError(f"retrieval root is not a directory: {root}")
        started = time.perf_counter()
        argv = self.argv(statement, k=k, no_cache=no_cache)
        try:
            stdout, stderr, returncode, truncated = _run_process(
                argv,
                root,
                timeout_s=timeout_s,
                env=env,
                max_output_bytes=self.max_output_bytes,
            )
        except OSError as exc:
            raise JevgrepError(str(exc)) from exc
        if returncode:
            raise JevgrepError(stderr.decode("utf-8", errors="replace").strip() or f"exit {returncode}")
        parsed = parse_output(
            stdout,
            root=root,
            task_id=task_id,
            k=k,
            no_cache=no_cache,
            truncated=truncated,
        )
        return parsed.result.model_copy(
            update={"latency_ms": (time.perf_counter() - started) * 1000}
        )


class MockJevgrepAdapter(JevgrepAdapter):
    """Deterministic fixture-driven mock; output is not efficacy evidence."""

    def __init__(self, responses: dict[str, bytes | str] | None = None) -> None:
        super().__init__(executable="mock-jg")
        self.responses = responses or {}

    def query(
        self,
        statement: str,
        root: Path,
        *,
        k: int = 10,
        task_id: str = "",
        timeout_s: float = 120,
        no_cache: bool = True,
        env: dict[str, str] | None = None,
    ) -> RetrievalResult:
        del timeout_s, env
        response = self.responses.get(statement, b'{"results":[]}')
        parsed = parse_output(
            response,
            root=root,
            task_id=task_id,
            k=k,
            no_cache=no_cache,
        )
        return parsed.result.model_copy(
            update={
                "error": "protocol demonstration: simulated-fixture",
                "latency_ms": 0.0,
            }
        )


parse_jg_output = parse_output
MockJevgrep = MockJevgrepAdapter
