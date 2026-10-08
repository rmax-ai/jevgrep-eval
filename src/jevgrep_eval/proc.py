"""Bounded process teardown: a stuck pipe writer must not wedge the orchestrator."""

from __future__ import annotations

import io
import os
import signal
import subprocess
import time


def bounded_terminate(
    process: subprocess.Popen,
    *,
    grace_s: float = 5.0,
    drain_s: float = 5.0,
) -> tuple[bytes | str, bytes | str]:
    """Terminate ``process``'s group and drain its pipes within fixed bounds.

    Never blocks longer than roughly ``0.5 + grace_s + drain_s`` after entry,
    even when pipe writers escaped the process group (setsid descendants) or
    stall in uninterruptible sleep. The drain reads at the fd level with a hard
    deadline (non-blocking + short sleeps); it never waits for EOF from writers
    it cannot reach and never blocks on a stream lock. Whatever was captured
    (possibly empty) is returned.
    """

    if process.poll() is None:
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
            try:
                process.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                pass  # a descendant outside our kill reach keeps running; proceed

    deadline = time.monotonic() + drain_s
    return (
        _drain_fd(process.stdout, deadline),
        _drain_fd(process.stderr, deadline),
    )


def _drain_fd(stream: io.IOBase | None, deadline: float) -> bytes | str:
    if stream is None:
        return b""
    text = isinstance(stream, io.TextIOBase)
    chunks: list[bytes] = []
    try:
        fd = stream.fileno()
    except (OSError, ValueError):
        return "" if text else b""
    try:
        was_blocking = os.get_blocking(fd)
    except (OSError, ValueError):
        was_blocking = True
    try:
        os.set_blocking(fd, False)
    except (OSError, ValueError):
        pass
    try:
        while time.monotonic() < deadline:
            try:
                piece = os.read(fd, 65536)
            except BlockingIOError:
                time.sleep(0.02)
                continue
            except (OSError, ValueError):
                break
            if not piece:
                break
            chunks.append(piece)
    finally:
        try:
            os.set_blocking(fd, was_blocking)
        except (OSError, ValueError):
            pass
    raw = b"".join(chunks)
    return raw.decode("utf-8", "replace") if text else raw
