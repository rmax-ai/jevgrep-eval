from datetime import UTC, datetime

from jevgrep_eval.envelope import (
    add_component,
    create_envelope,
    verify_envelope,
)
from jevgrep_eval.models import RunEnvelope, RunState


def test_envelope_retains_chain_and_rejects_mutation():
    envelope = create_envelope(
        run_id="run",
        task_id="task",
        condition_id="a0",
        task={"id": "task"},
        fixture_manifest={"files": []},
        statement="statement",
        prompt_common="common",
        prompt_fragment="fragment",
        skill_bytes=b"skill",
        invocation={"argv": ["mock"]},
        pre_workspace={"files": []},
    )
    envelope = add_component(envelope, "post_workspace_digest", {"files": ["a"]})
    assert verify_envelope(envelope).valid
    mutated = envelope.model_copy(update={"task_digest": "other"})
    assert not verify_envelope(mutated).valid


def test_legacy_stage_chain_is_ordered():
    envelope = RunEnvelope(
        run_id="run",
        task_digest="task",
        fixture_manifest_digest="fixture",
        statement_digest="statement",
        prompt_common_digest="common",
        prompt_fragment_digest="fragment",
        skills_digest="skills",
        invocation_digest="invocation",
        pre_workspace_digest="before",
    )
    from jevgrep_eval.envelope import append_transition

    envelope = append_transition(envelope, RunState.PREPARED, datetime.now(UTC))
    verification = verify_envelope(envelope)
    assert not verification.valid
    assert "missing retained bytes: task_digest" in verification.errors


def test_envelope_fails_closed_for_missing_identity_evidence():
    envelope = create_envelope(
        run_id="run",
        task_id="task",
        condition_id="a0",
        task={"id": "task"},
        fixture_manifest={"files": []},
        statement="statement",
        prompt_common="common",
        prompt_fragment="fragment",
        skill_bytes=b"skill",
        invocation={"argv": ["mock"]},
        pre_workspace={"files": []},
    )
    retained = dict(envelope.retained_bytes)
    retained.pop("task_digest")
    malformed = envelope.model_copy(update={"retained_bytes": retained})
    verification = verify_envelope(malformed)
    assert not verification.valid
    assert "missing retained bytes: task_digest" in verification.errors


def test_empty_patch_component_verifies():
    envelope = create_envelope(
        run_id="run",
        task_id="task",
        condition_id="a0",
        task={"id": "task"},
        fixture_manifest={"files": []},
        statement="statement",
        prompt_common="common",
        prompt_fragment="fragment",
        skill_bytes=b"skill",
        invocation={"argv": ["mock"]},
        pre_workspace={"files": []},
    )
    envelope = add_component(envelope, "post_workspace_digest", {"files": []})
    envelope = add_component(envelope, "patch_digest", b"")
    verification = verify_envelope(envelope)
    assert verification.valid, verification.errors


def test_nonempty_patch_digest_with_empty_retained_bytes_fails():
    envelope = create_envelope(
        run_id="run",
        task_id="task",
        condition_id="a0",
        task={"id": "task"},
        fixture_manifest={"files": []},
        statement="statement",
        prompt_common="common",
        prompt_fragment="fragment",
        skill_bytes=b"skill",
        invocation={"argv": ["mock"]},
        pre_workspace={"files": []},
    )
    envelope = add_component(envelope, "post_workspace_digest", {"files": []})
    envelope = add_component(envelope, "patch_digest", b"diff --git a/x b/x\n")
    retained = dict(envelope.retained_bytes)
    retained["patch_digest"] = ""
    tampered = envelope.model_copy(update={"retained_bytes": retained})
    verification = verify_envelope(tampered)
    assert not verification.valid
    assert "empty retained bytes: patch_digest" in verification.errors


def test_envelope_fails_closed_for_malformed_identity_evidence():
    envelope = create_envelope(
        run_id="run",
        task_id="task",
        condition_id="a0",
        task={"id": "task"},
        fixture_manifest={"files": []},
        statement="statement",
        prompt_common="common",
        prompt_fragment="fragment",
        skill_bytes=b"skill",
        invocation={"argv": ["mock"]},
        pre_workspace={"files": []},
    )
    retained = dict(envelope.retained_bytes)
    retained["task_digest"] = "bm90LWpzb24="
    malformed = envelope.model_copy(update={"retained_bytes": retained})
    verification = verify_envelope(malformed)
    assert not verification.valid
    assert "identity binding is not JSON: task_digest" in verification.errors
