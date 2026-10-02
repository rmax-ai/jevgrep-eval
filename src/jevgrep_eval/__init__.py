"""Offline, reproducible engine for the jevgrep retrieval evaluation."""

__version__ = "0.1.0"

from .models import (
    AdmissionEvidence,
    AdmissionRecord,
    ConditionConfig,
    EvaluationRecord,
    GoldEvidence,
    RepoFixture,
    RetrievalQuery,
    RetrievalResult,
    RunRecord,
    TaskCase,
    ToolEvent,
    UsageCost,
    WorkspaceManifest,
)

__all__ = [
    "AdmissionEvidence",
    "AdmissionRecord",
    "ConditionConfig",
    "EvaluationRecord",
    "GoldEvidence",
    "RepoFixture",
    "RetrievalQuery",
    "RetrievalResult",
    "RunRecord",
    "TaskCase",
    "ToolEvent",
    "UsageCost",
    "WorkspaceManifest",
]
