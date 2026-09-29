"""Strict Pydantic v2 contracts for benchmark inputs and evidence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)


class StrictModel(BaseModel):
    """Base for every persisted boundary model."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=False,
        populate_by_name=True,
        validate_assignment=True,
    )


class RunState(StrEnum):
    PREPARED = "PREPARED"
    RUNNING = "RUNNING"
    SNAPSHOT = "SNAPSHOT"
    EVALUATED = "EVALUATED"
    RECORDED = "RECORDED"


class TerminalStatus(StrEnum):
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ENV_FAILURE = "env_failure"
    MALFORMED_PATCH = "malformed_patch"


class FailureClass(StrEnum):
    LOCALIZATION = "localization"
    INCORRECT_IMPLEMENTATION = "incorrect_implementation"
    TESTS_NOT_RUN = "tests_not_run"
    TIMEOUT = "timeout"
    MALFORMED_PATCH = "malformed_patch"
    ENV_FAILURE = "env_failure"
    REGRESSION = "regression"


class EventKind(StrEnum):
    READ = "read"
    SEARCH_NATIVE = "search_native"
    SEARCH_JG = "search_jg"
    SEARCH_BM25 = "search_bm25"
    EDIT = "edit"
    TEST = "test"
    OTHER_SHELL = "other_shell"


class ComponentName(StrEnum):
    TASK = "task_digest"
    FIXTURE = "fixture_manifest_digest"
    STATEMENT = "statement_digest"
    PROMPT_COMMON = "prompt_common_digest"
    PROMPT_FRAGMENT = "prompt_fragment_digest"
    SKILLS = "skill_bytes_digest"
    INVOCATION = "invocation_digest"
    PRE_WORKSPACE = "pre_workspace_digest"
    POST_WORKSPACE = "post_workspace_digest"
    PATCH = "patch_digest"
    EVALUATOR_INPUT = "evaluator_input_digest"
    EVALUATION_RESULT = "evaluation_result_digest"


class RepoFixture(StrictModel):
    repo_id: StrictStr
    url: StrictStr
    license_spdx: StrictStr
    language: StrictStr
    base_commit: StrictStr = ""
    base_commit_candidates: list[StrictStr] = Field(default_factory=list)
    fixture_manifest_sha256: StrictStr = ""
    source: StrictStr = ""
    dependency_cache: StrictStr = ""
    cache_injection: StrictStr = ""
    notes: StrictStr = ""
    admission_record: StrictStr | dict[str, Any] | None = None


class ManifestEntry(StrictModel):
    path: StrictStr
    sha256: StrictStr
    role: StrictStr


class TaskCase(StrictModel):
    task_id: StrictStr
    repo_id: StrictStr
    base_sha: StrictStr
    gold_sha: StrictStr
    fix_ref: StrictStr = ""
    task_class: StrictStr
    statement: StrictStr
    changed_files: list[StrictStr] = Field(default_factory=list)
    gold_evidence_files: list[StrictStr] = Field(default_factory=list)
    hidden_test_patch: StrictStr
    test_runner: StrictStr
    test_command: list[StrictStr] = Field(default_factory=list)
    hidden_test_command: list[StrictStr] = Field(default_factory=list)
    setup_commands: list[StrictStr] = Field(default_factory=list)
    expected_test_seconds: StrictFloat = Field(default=0.0, ge=0)
    stratum: StrictStr = "unclassified"
    manifest: list[ManifestEntry] = Field(default_factory=list)
    secondary_tags: list[StrictStr] = Field(default_factory=list)
    admission_status: StrictStr = "candidate"
    split: StrictStr | None = None


class GoldEvidence(StrictModel):
    task_id: StrictStr
    files: list[StrictStr] = Field(default_factory=list)
    symbols: list[StrictStr] = Field(default_factory=list)
    rationale: StrictStr = ""


class ConditionConfig(StrictModel):
    id: StrictStr = Field(validation_alias=AliasChoices("id", "condition_id"))
    label: StrictStr
    retrieval_tools: list[Literal["jg", "bm25"]] = Field(default_factory=list)
    forced_first: Literal["none", "jg", "bm25"] = "none"
    oracle_hint: StrictBool = False
    notes: StrictStr = ""

    @property
    def condition_id(self) -> str:
        return self.id

    @property
    def retriever(self) -> str:
        if self.id == "a0":
            return "native"
        if self.retrieval_tools:
            return self.retrieval_tools[0]
        return "oracle" if self.oracle_hint else "native"


class ToolResult(StrictModel):
    files_returned: list[StrictStr] = Field(default_factory=list)
    chunk_ids: list[StrictStr] = Field(default_factory=list)
    tokens_returned: StrictInt | None = None
    matched: StrictBool | None = None
    summary: StrictStr = ""
    excerpts: list[StrictStr] = Field(default_factory=list)
    successful: StrictBool | None = None


class ToolEvent(StrictModel):
    seq: StrictInt = Field(ge=0)
    kind: EventKind
    cmd_digest: StrictStr
    cmd_scrubbed: StrictStr
    ts_offset_ms: StrictInt = Field(default=0, ge=0, validation_alias=AliasChoices("ts_offset_ms", "timestamp_offset_ms"))
    files_touched: list[StrictStr] = Field(default_factory=list)
    result: ToolResult = Field(default_factory=ToolResult)
    started: StrictBool = True
    completed: StrictBool = True
    redaction_version: StrictStr = "jevgrep-eval-redaction-v1"
    root: StrictStr = ""
    exit_code: StrictInt | None = None
    truncated: StrictBool = False


class UsageCost(StrictModel):
    jev_cash_usd: Decimal | Literal["unknown"] | None = Field(default=None)
    codex_quota_tokens: StrictInt | None = Field(default=None, ge=0)
    codex_listprice_modeled_usd: Decimal | Literal["unknown"] | None = Field(default=None)
    local_compute_wall_s: float | Literal["unknown"] | None = Field(default=None)
    combined_variable_modeled_usd: Decimal | Literal["unknown"] | None = Field(default=None)
    receipt_id: StrictStr | None = None
    unknown_reason: StrictStr | None = None

    @field_validator(
        "jev_cash_usd",
        "codex_listprice_modeled_usd",
        "combined_variable_modeled_usd",
        mode="before",
    )
    @classmethod
    def validate_money(cls, value: Any) -> Any:
        if value is None or value == "unknown":
            return value
        if isinstance(value, (bool, float, int)):
            raise ValueError("money must be a decimal string or Decimal")  # noqa: TRY004
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        if not decimal.is_finite() or decimal < 0:
            raise ValueError("money must be finite and non-negative")
        return decimal

    @field_validator("local_compute_wall_s", mode="before")
    @classmethod
    def validate_wall_time(cls, value: Any) -> Any:
        if value is None or value == "unknown":
            return value
        if isinstance(value, bool):
            raise TypeError("wall time must be numeric")
        number = float(value)
        if number < 0:
            raise ValueError("wall time must be non-negative")
        return number


class RunRecord(StrictModel):
    run_id: StrictStr
    task_id: StrictStr
    condition_id: StrictStr
    repetition: StrictInt = Field(ge=0)
    state: RunState
    terminal_status: TerminalStatus | None = None
    error: FailureClass | None = None
    task_success: StrictBool | None = None
    trace_coverage: Literal["full", "partial"] = "full"
    trace_missing: list[StrictStr] = Field(default_factory=list)
    trace_errors: list[StrictStr] = Field(default_factory=list)
    protocol_id: StrictStr = "v1"
    tree_hash: StrictStr = ""
    envelope_digest: StrictStr = ""
    pre_workspace_digest: StrictStr = ""
    post_workspace_digest: StrictStr = ""
    workspace_digest: StrictStr = ""
    patch_digest: StrictStr = ""
    events: list[ToolEvent] = Field(default_factory=list)
    stage_records: list[StageRecord] = Field(default_factory=list)
    metrics_refs: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    usage_refs: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    usage_cost: UsageCost = Field(default_factory=UsageCost)
    flags: list[StrictStr] = Field(default_factory=list)
    created_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def arm(self) -> str:
        return self.condition_id


class EvaluationRecord(StrictModel):
    run_id: StrictStr
    task_success: StrictBool
    failure_class: FailureClass | None = None
    hidden_passed: StrictBool
    upstream_passed: StrictBool
    replay_equal: StrictBool
    patch_digest: StrictStr
    evaluator_input_digest: StrictStr
    tested_at: datetime | None = None
    patch_similarity_diagnostic: float | None = Field(default=None, ge=0, le=1)
    stdout_digest: StrictStr | None = None


class RetrievalQuery(StrictModel):
    task_id: StrictStr
    statement: StrictStr
    root: StrictStr
    k: StrictInt = Field(default=10, gt=0)
    query_digest: StrictStr = ""
    max_context_tokens: StrictInt = Field(default=400, gt=0)
    backend: Literal["jevgrep", "bm25"] | None = None


class RetrievalHit(StrictModel):
    path: StrictStr
    score: StrictFloat = 0.0
    rank: StrictInt = Field(ge=1)
    chunk_id: StrictStr | None = None
    line_start: StrictInt | None = Field(default=None, ge=1)
    line_end: StrictInt | None = Field(default=None, ge=1)
    preview: StrictStr = ""


class RetrievalResult(StrictModel):
    task_id: StrictStr
    backend: Literal["jevgrep", "bm25"]
    hits: list[RetrievalHit] = Field(default_factory=list)
    latency_ms: StrictFloat = Field(default=0.0, ge=0)
    returned_context_bytes: StrictInt = Field(default=0, ge=0)
    malformed_output: StrictBool = False
    malformed_count: StrictInt = Field(default=0, ge=0)
    no_cache: StrictBool = False
    coverage: Literal["full", "partial"] = "full"
    token_estimate: StrictInt | None = Field(default=None, ge=0)
    context_tokens: StrictInt | None = Field(default=None, ge=0)
    token_estimator: StrictStr = "word-regex-v1"
    error: StrictStr | None = None
    summary: StrictStr = ""
    ranked_files: list[StrictStr] = Field(default_factory=list)
    excerpts: list[StrictStr] = Field(default_factory=list)
    rank_semantics: Literal["verified", "unordered"] = "unordered"


class WorkspaceFile(StrictModel):
    path: StrictStr
    file_type: Literal["file", "directory", "symlink"] = Field(
        validation_alias=AliasChoices("file_type", "type")
    )
    mode: StrictInt
    size: StrictInt = Field(ge=0)
    sha256: StrictStr

    @property
    def type(self) -> str:
        return self.file_type


class WorkspaceManifest(StrictModel):
    root: StrictStr = ""
    files: list[WorkspaceFile] = Field(default_factory=list)
    workspace_digest: StrictStr = ""
    metadata_free: StrictBool = True

    @property
    def entries(self) -> list[WorkspaceFile]:
        return self.files


class AdmissionRecord(StrictModel):
    task_id: StrictStr
    base_runs: StrictInt = Field(ge=0)
    base_failures: StrictInt = Field(ge=0)
    gold_runs: StrictInt = Field(ge=0)
    gold_passes: StrictInt = Field(ge=0)
    reviewer_count: StrictInt = Field(default=2, ge=0)
    admitted: StrictBool = False
    rejection_reason: StrictStr | None = None
    flake_log: list[StrictStr] = Field(default_factory=list)


class AdmissionEvidence(StrictModel):
    """Rich, evaluator-side admission evidence retained per candidate."""

    schema_version: StrictInt
    task_id: StrictStr
    base_sha: StrictStr
    gold_sha: StrictStr
    admitted: StrictBool
    base_hidden: dict[str, Any]
    gold_hidden: dict[str, Any]
    upstream_slice: dict[str, Any]
    commands: dict[str, Any] = Field(default_factory=dict)
    cache_injection: StrictStr
    network: dict[str, Any]
    runtime_seconds_after_prep: StrictFloat | None = None
    rejection_reasons: list[StrictStr] = Field(default_factory=list)
    flake_notes: list[StrictStr] = Field(default_factory=list)
    threat_notes: list[StrictStr] = Field(default_factory=list)
    tool_versions: dict[str, Any] = Field(default_factory=dict)
    reused_previous_artifacts: StrictBool


class StageRecord(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=False,
        populate_by_name=True,
        frozen=True,
    )
    run_id: StrictStr
    from_state: RunState | None
    to_state: RunState
    at: datetime
    parent_digest: StrictStr
    record_digest: StrictStr
    terminal_status: TerminalStatus | None = None

    @property
    def stage(self) -> str:
        return self.to_state.value

    @property
    def timestamp(self) -> datetime:
        return self.at


class PricingEntry(StrictModel):
    component: StrictStr
    effective_date: StrictStr
    source: StrictStr
    retrieved_at: StrictStr
    model: StrictStr = ""
    service_tier: StrictStr = ""
    notes: StrictStr = ""
    input_rate_usd_per_million: Decimal | None = None
    output_rate_usd_per_million: Decimal | None = None

    @field_validator("input_rate_usd_per_million", "output_rate_usd_per_million", mode="before")
    @classmethod
    def parse_rate(cls, value: Any) -> Any:
        if value is None:
            return None
        try:
            decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        except (ArithmeticError, ValueError) as exc:
            raise ValueError("rate must be a decimal") from exc
        if not decimal.is_finite() or decimal < 0:
            raise ValueError("rate must be finite and non-negative")
        return decimal


class PricingConfig(StrictModel):
    entries: list[PricingEntry] = Field(default_factory=list)
    currency: Literal["USD"] = "USD"
    cap_usd: Decimal = Decimal(50)

    @field_validator("cap_usd", mode="before")
    @classmethod
    def validate_cap(cls, value: Any) -> Any:
        try:
            decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        except (ArithmeticError, ValueError) as exc:
            raise ValueError("cap must be a decimal") from exc
        if not decimal.is_finite() or decimal < 0:
            raise ValueError("cap must be finite and non-negative")
        return decimal

    @property
    def rates(self) -> list[PricingEntry]:
        return self.entries


class RunEnvelope(StrictModel):
    envelope_version: StrictStr = Field(
        default="v1",
        validation_alias=AliasChoices("envelope_version", "version"),
    )
    run_id: StrictStr
    task_id: StrictStr = ""
    condition_id: StrictStr = ""
    arm: StrictStr = ""
    task_digest: StrictStr
    fixture_manifest_digest: StrictStr
    statement_digest: StrictStr
    prompt_common_digest: StrictStr = Field(
        validation_alias=AliasChoices("prompt_common_digest", "common_template_digest")
    )
    prompt_fragment_digest: StrictStr = Field(
        validation_alias=AliasChoices("prompt_fragment_digest", "condition_fragment_digest")
    )
    skill_bytes_digest: StrictStr = Field(
        validation_alias=AliasChoices("skill_bytes_digest", "skills_digest")
    )
    invocation_digest: StrictStr
    pre_workspace_digest: StrictStr
    post_workspace_digest: StrictStr = ""
    patch_digest: StrictStr = ""
    evaluator_input_digest: StrictStr = ""
    evaluation_result_digest: StrictStr = ""
    transitions: list[StageRecord] = Field(default_factory=list)
    chain: list[DigestLink] = Field(default_factory=list)
    retained_bytes: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    requested_model: StrictStr = ""
    resolved_model: StrictStr = ""
    effort: StrictStr = ""
    prompt_digest: StrictStr = ""
    invocation_argv_digest: StrictStr = ""
    sanitized_env_digest: StrictStr = ""
    config_digest: StrictStr = ""

    @property
    def version(self) -> str:
        return self.envelope_version

    @property
    def skills_digest(self) -> str:
        """Compatibility spelling used by early draft fixtures."""
        return self.skill_bytes_digest

    @property
    def common_template_digest(self) -> str:
        return self.prompt_common_digest

    @property
    def condition_fragment_digest(self) -> str:
        return self.prompt_fragment_digest

    def model_post_init(self, __context: Any, /) -> None:
        if not self.prompt_digest:
            from .util import digest

            object.__setattr__(
                self,
                "prompt_digest",
                digest(
                    {
                        "common_template_digest": self.prompt_common_digest,
                        "condition_fragment_digest": self.prompt_fragment_digest,
                        "skill_bytes_digest": self.skill_bytes_digest,
                    },
                    component="prompt",
                ),
            )


class DigestLink(StrictModel):
    component: StrictStr
    digest: StrictStr
    parent_digest: StrictStr | None = None


class SpendEntry(StrictModel):
    call_id: StrictStr
    component: Literal["jev", "codex", "bm25", "evaluator"]
    tokens: StrictInt | None = Field(default=None, ge=0)
    rate_source: StrictStr
    estimate_usd: Decimal | Literal["unknown"] | None = Field(default=None)
    cumulative_usd: Decimal = Field(default=Decimal(0), ge=Decimal(0))
    reserved_usd: Decimal = Field(default=Decimal(0), ge=Decimal(0))
    status: Literal["reserved", "reconciled", "stopped"] = "reserved"
    receipt_id: StrictStr | None = None

    @field_validator("estimate_usd", mode="before")
    @classmethod
    def validate_estimate(cls, value: Any) -> Any:
        if value is None or value == "unknown":
            return value
        if isinstance(value, (bool, float, int)):
            raise ValueError("estimate must be a decimal string or Decimal")  # noqa: TRY004
        result = value if isinstance(value, Decimal) else Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError("estimate must be finite and non-negative")
        return result


class LedgerSnapshot(StrictModel):
    cap_usd: Decimal
    committed_cash_usd: Decimal
    reserved_cash_usd: Decimal
    available_cash_usd: Decimal
    entries: list[SpendEntry] = Field(default_factory=list)
