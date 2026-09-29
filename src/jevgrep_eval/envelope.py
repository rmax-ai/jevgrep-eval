"""Versioned evidence chain for one task × arm × repetition.

Every decision-relevant component has a digest, a parent digest, and retained
canonical bytes.  Verification is fail-closed and never trusts an external
run directory name as an identity.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DigestLink, RunEnvelope, RunState, StageRecord, TerminalStatus
from .util import (
    b64decode,
    b64encode,
    canonical_json,
    digest,
    digest_bytes,
    now,
    write_canonical_json,
)

CHAIN_ORDER = (
    "task_digest",
    "fixture_manifest_digest",
    "statement_digest",
    "prompt_common_digest",
    "prompt_fragment_digest",
    "skill_bytes_digest",
    "invocation_digest",
    "pre_workspace_digest",
    "post_workspace_digest",
    "patch_digest",
    "evaluator_input_digest",
    "evaluation_result_digest",
)
REQUIRED_CHAIN_COMPONENTS = frozenset(CHAIN_ORDER[:8])
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class RunVerificationError(ValueError):
    """A run's retained evidence cannot be verified."""

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class Verification:
    valid: bool
    errors: tuple[str, ...] = ()

    def raise_for_error(self) -> None:
        if not self.valid:
            raise RunVerificationError(self.errors)


def component_bytes(value: Any) -> bytes:
    """Return the exact canonical bytes retained for a chain component."""
    if isinstance(value, bytes):
        return value
    return canonical_json(value)


def component_digest(value: Any) -> str:
    return digest_bytes(component_bytes(value))


def _field_name(component: str) -> str:
    if component == "skills_digest":
        return "skill_bytes_digest"
    if component == "common_template_digest":
        return "prompt_common_digest"
    if component == "condition_fragment_digest":
        return "prompt_fragment_digest"
    return component if component.endswith("_digest") else f"{component}_digest"


def create_envelope(
    *,
    run_id: str,
    task_id: str,
    condition_id: str,
    task: Any,
    fixture_manifest: Any,
    statement: Any,
    prompt_common: Any,
    prompt_fragment: Any,
    skill_bytes: Any,
    invocation: Any,
    pre_workspace: Any,
    requested_model: str = "",
    resolved_model: str = "",
    effort: str = "",
) -> RunEnvelope:
    """Create a complete pre-run envelope with retained canonical bytes."""
    # The task and condition identity must be inside retained evidence, not
    # inferred from a mutable directory name or from the mutable envelope
    # fields.  Binding these two values makes a bare verify-run invocation
    # reject cross-task and cross-arm substitutions.
    bound_task = {"task_id": task_id, "value": task}
    bound_fragment = {"condition_id": condition_id, "value": prompt_fragment}
    values = {
        "task_digest": bound_task,
        "fixture_manifest_digest": fixture_manifest,
        "statement_digest": statement,
        "prompt_common_digest": prompt_common,
        "prompt_fragment_digest": bound_fragment,
        "skill_bytes_digest": skill_bytes,
        "invocation_digest": invocation,
        "pre_workspace_digest": pre_workspace,
    }
    envelope = RunEnvelope(
        run_id=run_id,
        task_id=task_id,
        condition_id=condition_id,
        arm=condition_id,
        task_digest=component_digest(bound_task),
        fixture_manifest_digest=component_digest(fixture_manifest),
        statement_digest=component_digest(statement),
        prompt_common_digest=component_digest(prompt_common),
        prompt_fragment_digest=component_digest(bound_fragment),
        skill_bytes_digest=component_digest(skill_bytes),
        invocation_digest=component_digest(invocation),
        pre_workspace_digest=component_digest(pre_workspace),
        requested_model=requested_model,
        resolved_model=resolved_model,
        effort=effort,
        retained_bytes={
            name: b64encode(component_bytes(value)) for name, value in values.items()
        },
    )
    if isinstance(invocation, dict):
        envelope = envelope.model_copy(
            update={
                "invocation_argv_digest": component_digest(invocation.get("argv", [])),
                "sanitized_env_digest": component_digest(invocation.get("sanitized_env", {})),
                "config_digest": component_digest(invocation.get("config", {})),
            }
        )
    return _rebuild_chain(envelope)


def _rebuild_chain(envelope: RunEnvelope) -> RunEnvelope:
    parent: str | None = None
    links: list[DigestLink] = []
    for name in CHAIN_ORDER:
        value = getattr(envelope, name)
        if not value:
            continue
        links.append(DigestLink(component=name, digest=value, parent_digest=parent))
        parent = value
    return envelope.model_copy(update={"chain": links})


def add_component(envelope: RunEnvelope, name: str, value: Any) -> RunEnvelope:
    """Add a post-run component, retaining its exact canonical bytes."""
    field = _field_name(name)
    if field not in CHAIN_ORDER:
        raise ValueError(f"unknown envelope component: {name}")
    bytes_value = component_bytes(value)
    updated = envelope.model_copy(
        update={
            field: component_digest(bytes_value),
            "retained_bytes": {
                **envelope.retained_bytes,
                field: b64encode(bytes_value),
            },
        }
    )
    return _rebuild_chain(updated)


def write_bytes(path: Path, content: bytes) -> str:
    """Retain bytes atomically and return their raw SHA-256 digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return digest_bytes(content)


def envelope_digest(envelope: RunEnvelope) -> str:
    return digest(envelope.model_dump(mode="json"), component="run-envelope")


def save_envelope(envelope: RunEnvelope, path: Path) -> None:
    write_canonical_json(path, envelope.model_dump(mode="json"))


def load_envelope(path: Path) -> RunEnvelope:
    return RunEnvelope.model_validate_json(path.read_bytes())


def append_transition(
    envelope: RunEnvelope,
    to_state: RunState,
    at: Any | None = None,
    *,
    parent_digest: str | None = None,
    terminal_status: TerminalStatus | None = None,
) -> RunEnvelope:
    """Append one immutable sorted-key stage record to an envelope."""
    previous = envelope.transitions[-1].to_state if envelope.transitions else None
    if previous is not None and list(RunState).index(to_state) != list(RunState).index(previous) + 1:
        raise RunVerificationError((f"invalid transition {previous} -> {to_state}",))
    parent = parent_digest or (
        envelope.transitions[-1].record_digest
        if envelope.transitions
        else envelope_digest(envelope.model_copy(update={"transitions": []}))
    )
    unsigned = StageRecord(
        run_id=envelope.run_id,
        from_state=previous,
        to_state=to_state,
        at=at or now(),
        parent_digest=parent,
        record_digest="pending",
        terminal_status=terminal_status,
    )
    record = unsigned.model_copy(
        update={"record_digest": digest(unsigned.model_dump(mode="json"), component="stage-record")}
    )
    return envelope.model_copy(update={"transitions": [*envelope.transitions, record]})


def _retained(envelope: RunEnvelope, external: dict[str, bytes] | None) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for name, value in envelope.retained_bytes.items():
        try:
            result[name] = b64decode(value)
        except (TypeError, UnicodeError, ValueError) as exc:
            raise RunVerificationError((f"invalid retained bytes encoding: {name}",)) from exc
    if external:
        for name, value in external.items():
            if not isinstance(value, bytes):
                raise RunVerificationError((f"invalid external retained bytes: {name}",))
            if name in result and result[name] != value:
                raise RunVerificationError((f"conflicting retained bytes: {name}",))
            result[name] = value
    return result


def verify_envelope(
    envelope: RunEnvelope,
    retained: dict[str, bytes] | None = None,
    *,
    expected_task_digest: str | None = None,
    expected_condition_id: str | None = None,
) -> Verification:
    """Recompute every retained digest and every parent link.

    A v1 envelope is only verifiable when all pre-run chain components have
    both retained bytes and an ordered chain link.  Digest fields by
    themselves are not evidence: accepting them would let a caller replace
    the underlying task, identity, or invocation without detection.
    """
    errors: list[str] = []
    if envelope.envelope_version != "v1":
        errors.append(f"unsupported envelope version: {envelope.envelope_version}")
    if not envelope.task_id:
        errors.append("envelope has no task identity")
    if not envelope.condition_id or envelope.condition_id != envelope.arm:
        errors.append("envelope has no consistent arm identity")
    if expected_task_digest and envelope.task_digest != expected_task_digest:
        errors.append("task digest mismatch")
    if expected_condition_id and envelope.condition_id != expected_condition_id:
        errors.append("condition/arm mismatch")
    if envelope.condition_id and envelope.arm and envelope.condition_id != envelope.arm:
        errors.append("condition/arm fields disagree")
    expected_prompt = digest(
        {
            "common_template_digest": envelope.prompt_common_digest,
            "condition_fragment_digest": envelope.prompt_fragment_digest,
            "skill_bytes_digest": envelope.skill_bytes_digest,
        },
        component="prompt",
    )
    if envelope.prompt_digest != expected_prompt:
        errors.append("prompt digest mismatch")
    try:
        retained_values = _retained(envelope, retained)
    except RunVerificationError as exc:
        errors.extend(exc.errors)
        retained_values = {}
    retained_names = set(retained_values)
    known_names = set(CHAIN_ORDER)
    unexpected_retained = retained_names - known_names
    if unexpected_retained:
        errors.append(f"unexpected retained components: {sorted(unexpected_retained)}")
    expected_components = {
        name for name in CHAIN_ORDER if bool(getattr(envelope, name))
    }
    for name in expected_components:
        if not _DIGEST_RE.fullmatch(getattr(envelope, name)):
            errors.append(f"invalid digest: {name}")
    missing_components = REQUIRED_CHAIN_COMPONENTS - expected_components
    errors.extend(
        f"missing required chain component: {name}"
        for name in sorted(missing_components)
    )
    missing_retained = expected_components - retained_names
    errors.extend(
        f"missing retained bytes: {name}" for name in sorted(missing_retained)
    )
    # An empty skill bundle is a valid, explicit no-skills condition.  All
    # other retained components must carry non-empty canonical evidence.
    empty_retained = {
        name
        for name, value in retained_values.items()
        if not value and name != "skill_bytes_digest"
    }
    errors.extend(f"empty retained bytes: {name}" for name in sorted(empty_retained))
    for name, identity_key, expected_identity in (
        ("task_digest", "task_id", envelope.task_id),
        ("prompt_fragment_digest", "condition_id", envelope.condition_id),
    ):
        raw = retained_values.get(name)
        if raw is None:
            continue
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append(f"identity binding is not JSON: {name}")
            continue
        if (
            not isinstance(decoded, dict)
            or identity_key not in decoded
            or decoded.get(identity_key) != expected_identity
            or "value" not in decoded
        ):
            errors.append(f"identity binding mismatch: {name}")
    for name in CHAIN_ORDER:
        expected = getattr(envelope, name)
        if not expected:
            if name in retained_values:
                errors.append(f"retained bytes supplied for empty component: {name}")
            continue
        bytes_value = retained_values.get(name)
        if bytes_value is not None and digest_bytes(bytes_value) != expected:
            errors.append(f"retained bytes mismatch: {name}")
    previous: str | None = None
    expected_chain = [name for name in CHAIN_ORDER if getattr(envelope, name)]
    if [link.component for link in envelope.chain] != expected_chain:
        errors.append("chain component order mismatch")
    for link in envelope.chain:
        if link.component not in known_names:
            errors.append(f"unknown chain component: {link.component}")
            continue
        if not _DIGEST_RE.fullmatch(link.digest):
            errors.append(f"invalid chain link digest: {link.component}")
        if not getattr(envelope, link.component, ""):
            errors.append(f"chain contains empty component: {link.component}")
        if link.digest != getattr(envelope, link.component, ""):
            errors.append(f"chain digest mismatch: {link.component}")
        if link.parent_digest != previous:
            errors.append(f"chain parent mismatch: {link.component}")
        previous = link.digest
    for record in envelope.transitions:
        unsigned = record.model_copy(update={"record_digest": "pending"})
        expected_record = digest(unsigned.model_dump(mode="json"), component="stage-record")
        if record.record_digest != expected_record:
            errors.append(f"invalid transition digest at {record.to_state}")
    for left, right in zip(envelope.transitions, envelope.transitions[1:]):
        if right.parent_digest != left.record_digest:
            errors.append(f"broken stage parent link at {right.to_state}")
    return Verification(not errors, tuple(errors))


def verify_run(
    path: Path,
    retained_dir: Path | None = None,
    *,
    expected_task_digest: str | None = None,
    expected_condition_id: str | None = None,
) -> Verification:
    """Verify a run directory or a direct envelope path."""
    envelope_path = path
    if path.is_dir():
        candidates = (path / "run-envelope.json", path / "envelope.json")
        envelope_path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        retained_dir = retained_dir or path / "evidence"
    if not envelope_path.is_file():
        return Verification(False, ("missing run envelope",))
    try:
        envelope = load_envelope(envelope_path)
    except (OSError, ValueError) as exc:
        return Verification(False, (f"invalid run envelope: {exc}",))
    external: dict[str, bytes] = {}
    if path.is_dir():
        record_path = path / "run-record.json"
        if record_path.is_file():
            try:
                from .models import RunRecord

                record = RunRecord.model_validate_json(record_path.read_bytes())
            except (OSError, ValueError) as exc:
                return Verification(False, (f"invalid run record: {exc}",))
            if record.run_id != envelope.run_id:
                return Verification(False, ("run id mismatch between record and envelope",))
            if record.task_id != envelope.task_id:
                return Verification(False, ("task id mismatch between record and envelope",))
            if record.condition_id != envelope.condition_id:
                return Verification(False, ("condition id mismatch between record and envelope",))
    if not envelope.task_id:
        return Verification(False, ("envelope has no task identity",))
    if not envelope.condition_id or envelope.condition_id != envelope.arm:
        return Verification(False, ("envelope has no consistent arm identity",))
    if retained_dir and retained_dir.is_dir():
        for name in CHAIN_ORDER:
            candidates = (retained_dir / name, retained_dir / f"{name}.bytes")
            candidate = next((item for item in candidates if item.is_file()), None)
            if candidate is not None:
                external[name] = candidate.read_bytes()
    return verify_envelope(
        envelope,
        external,
        expected_task_digest=expected_task_digest,
        expected_condition_id=expected_condition_id,
    )
