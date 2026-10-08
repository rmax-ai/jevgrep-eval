"""Deterministic, private-by-default helpers for the benchmark engine."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

CANONICALIZATION_VERSION = "jevgrep-eval-canonical-v1"
REDACTION_VERSION = "jevgrep-eval-redaction-v1"

# Volatile fields are scrubbed only for decision digests.  Observation
# digests, retained bytes, and audit records never use this registry.
VOLATILE_FIELDS: dict[str, frozenset[str]] = {
    "RunRecord": frozenset({"created_at", "finished_at", "latency_ms"}),
    "UsageCost": frozenset({"local_compute_wall_s"}),
    "RetrievalResult": frozenset({"latency_ms"}),
}


def now() -> datetime:
    """Return the fixed test clock or the current UTC instant."""
    value = os.environ.get("JEVGREP_EVAL_NOW")
    if value:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
    return datetime.now(UTC)


def normalize_path(value: str) -> str:
    """Normalize a relative path using NFC and POSIX separators."""
    normalized = unicodedata.normalize("NFC", str(value)).replace("\\", "/")
    if normalized in {"", "."}:
        return ""
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"path is not safely relative: {value!r}")
    return str(path)


def _canonical(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite decimal cannot be canonicalized")
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda item: str(item[0]))
        return {
            unicodedata.normalize("NFC", str(key)): _canonical(item)
            for key, item in items
        }
    if isinstance(value, (set, frozenset)):
        normalized = [_canonical(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float cannot be canonicalized")
        return value
    if isinstance(value, bytes):
        return {"encoding": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    return value


def canonical_obj(value: Any) -> Any:
    """Return a JSON-compatible canonical object.

    Mapping keys and set members are sorted.  Sequence order is deliberately
    preserved because event, rank, and stage-record order is evidence.
    """
    return _canonical(value)


def canonical_json(value: Any) -> bytes:
    """Serialize canonical JSON as UTF-8 with exactly one trailing newline."""
    encoded = json.dumps(
        canonical_obj(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (encoded + "\n").encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: Any, *, component: str | None = None) -> str:
    """Hash canonical bytes with a schema and optional component namespace."""
    payload: dict[str, Any] = {"canonicalization": CANONICALIZATION_VERSION, "value": value}
    if component is not None:
        payload["component"] = component
    return digest_bytes(canonical_json(payload))


def decision_digest(value: Any, *, model_name: str | None = None) -> str:
    """Digest semantic fields while excluding only registered volatile fields."""
    dumped = canonical_obj(value)
    if model_name and isinstance(dumped, dict):
        scrubbed = dict(dumped)
        for field in VOLATILE_FIELDS.get(model_name, frozenset()):
            scrubbed.pop(field, None)
        dumped = scrubbed
    return digest(dumped, component="decision")


def observation_digest(value: Any) -> str:
    return digest(value, component="observation")


def sha256_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def write_canonical_json(path: Path, value: Any) -> bytes:
    """Atomically write canonical JSON and return the retained bytes."""
    content = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return content


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)
