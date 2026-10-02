"""Evaluator-side corpus loading and safe task selection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .models import AdmissionEvidence, AdmissionRecord, RepoFixture, TaskCase
from .util import digest


class CorpusError(ValueError):
    """A corpus artifact is missing or violates the corpus contract."""


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CorpusError(f"cannot load {path}: {exc}") from exc


def _items(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return payload[key]
    raise CorpusError(f"expected a list of {key}")


def _admission_record(path: Path, task_id: str) -> AdmissionRecord:
    """Convert the rich per-task evidence record to the public model."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"cannot load admission evidence {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("task_id") != task_id:
        raise CorpusError(f"admission evidence has the wrong task id: {path}")
    try:
        evidence = AdmissionEvidence.model_validate(payload)
    except ValueError as exc:
        raise CorpusError(f"invalid admission evidence {path}: {exc}") from exc
    base = evidence.base_hidden
    gold = evidence.gold_hidden
    base_runs = base.get("repetitions", []) if isinstance(base, dict) else []
    gold_runs = gold.get("repetitions", []) if isinstance(gold, dict) else []
    rejection_reasons = payload.get("rejection_reasons") or []
    if not isinstance(rejection_reasons, list):
        rejection_reasons = [str(rejection_reasons)]
    return AdmissionRecord(
        task_id=evidence.task_id,
        base_runs=len(base_runs) if isinstance(base_runs, list) else 0,
        base_failures=(
            sum(1 for row in base_runs if isinstance(row, dict) and row.get("returncode", 0) != 0)
            if isinstance(base_runs, list)
            else 0
        ),
        gold_runs=len(gold_runs) if isinstance(gold_runs, list) else 0,
        gold_passes=(
            sum(1 for row in gold_runs if isinstance(row, dict) and row.get("returncode") == 0)
            if isinstance(gold_runs, list)
            else 0
        ),
        reviewer_count=2,
        admitted=evidence.admitted,
        rejection_reason="; ".join(str(item) for item in rejection_reasons) or None,
        flake_log=[
            str(item)
            for item in payload.get("threat_notes", [])
            if isinstance(item, str)
        ],
    )


class Corpus:
    def __init__(
        self,
        repos: list[RepoFixture],
        tasks: list[TaskCase],
        admissions: list[AdmissionRecord] | None = None,
    ) -> None:
        self.repos = repos
        self.tasks = tasks
        self.admissions = admissions or []
        self._repo_ids = {repo.repo_id for repo in repos}
        if any(task.repo_id not in self._repo_ids for task in tasks):
            raise CorpusError("task references an unknown repository")

    @classmethod
    def load(cls, root: Path) -> Corpus:
        repos_path = root / "repos.lock.yaml"
        repo_records = _items(_load_yaml(repos_path), "repos") if repos_path.exists() else []
        repos = sorted(
            (RepoFixture.model_validate(item) for item in repo_records),
            key=lambda repo: repo.repo_id,
        )
        tasks: list[TaskCase] = []
        task_dir = root / "tasks"
        task_paths = sorted(task_dir.glob("*.yaml"))
        task_paths.extend(sorted(task_dir.glob("*/task.yaml")))
        for path in task_paths:
            payload = _load_yaml(path)
            if path.name == "task.yaml" and isinstance(payload, dict) and "task_id" in payload:
                tasks.append(TaskCase.model_validate(payload))
            else:
                tasks.extend(TaskCase.model_validate(item) for item in _items(payload, "tasks"))
        admissions: list[AdmissionRecord] = []
        admission_dir = root / "admission"
        for path in sorted(admission_dir.glob("*.yaml")):
            admissions.extend(
                AdmissionRecord.model_validate(item)
                for item in _items(_load_yaml(path), "admissions")
            )
        for task_path in sorted(task_dir.glob("*/task.yaml")):
            evidence_path = task_path.parent / "admission.json"
            if evidence_path.is_file():
                task_id = str(_load_yaml(task_path).get("task_id", ""))
                admissions.append(_admission_record(evidence_path, task_id))
        deduped: dict[str, AdmissionRecord] = {
            record.task_id: record for record in admissions
        }
        return cls(
            repos,
            sorted(tasks, key=lambda task: task.task_id),
            sorted(deduped.values(), key=lambda record: record.task_id),
        )

    def task(self, task_id: str) -> TaskCase:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        raise CorpusError(f"unknown task: {task_id}")

    def digest(self) -> str:
        return digest(
            {
                "repos": [repo.model_dump(mode="json") for repo in self.repos],
                "tasks": [task.model_dump(mode="json") for task in self.tasks],
                "admissions": [record.model_dump(mode="json") for record in self.admissions],
            }
        )

    def validate_admission(self, task_id: str) -> bool:
        records = [record for record in self.admissions if record.task_id == task_id]
        return bool(records and all(record.admitted for record in records))

    def eligible_tasks(self, split: str | None = None) -> list[TaskCase]:
        tasks = [
            task
            for task in self.tasks
            if split is None or task.split is None or task.split == split
        ]
        return sorted(tasks, key=lambda task: task.task_id)

    def admitted_tasks(self, split: str | None = None) -> list[TaskCase]:
        """Return only tasks with a passing, recorded admission gate."""
        return [
            task
            for task in self.eligible_tasks(split)
            if self.validate_admission(task.task_id)
        ]


def validate_manifest(root: Path) -> None:
    """Validate every frozen task digest and evaluator artifact hash."""
    path = root / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"cannot load corpus manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise CorpusError("corpus manifest must be an object")
    expected_manifest_digest = digest(
        {key: value for key, value in manifest.items() if key != "manifest_digest"},
        component="corpus-manifest",
    )
    if manifest.get("manifest_digest") != expected_manifest_digest:
        raise CorpusError("corpus manifest digest mismatch")
    corpus = Corpus.load(root)
    rows = manifest.get("tasks")
    if not isinstance(rows, list) or len(rows) != len(corpus.tasks):
        raise CorpusError("corpus manifest task count mismatch")
    by_id = {str(row.get("task_id")): row for row in rows if isinstance(row, dict)}
    if set(by_id) != {task.task_id for task in corpus.tasks}:
        raise CorpusError("corpus manifest task ids mismatch")
    if manifest.get("task_count") != len(corpus.tasks):
        raise CorpusError("corpus manifest declared task count mismatch")
    admitted_count = sum(task.admission_status == "admitted" for task in corpus.tasks)
    if manifest.get("admitted_task_count") != admitted_count:
        raise CorpusError("corpus manifest admitted count mismatch")
    for task in corpus.tasks:
        row = by_id[task.task_id]
        expected_task_digest = digest(
            task.model_dump(mode="json", exclude={"manifest"}),
            component="task",
        )
        if row.get("task_digest") != expected_task_digest:
            raise CorpusError(f"task digest mismatch: {task.task_id}")
        if row.get("admission_status") != task.admission_status:
            raise CorpusError(f"task admission status mismatch: {task.task_id}")
        if task.admission_status == "admitted" and not corpus.validate_admission(task.task_id):
            raise CorpusError(f"admitted task has no passing evidence: {task.task_id}")
        if task.admission_status != "admitted" and corpus.validate_admission(task.task_id):
            raise CorpusError(f"rejected task has passing evidence: {task.task_id}")
        files = row.get("files")
        if not isinstance(files, list):
            raise CorpusError(f"manifest files are missing: {task.task_id}")
        seen: set[str] = set()
        for entry in files:
            if not isinstance(entry, dict):
                raise CorpusError(f"invalid manifest entry: {task.task_id}")
            relative = entry.get("path")
            if not isinstance(relative, str) or relative in seen:
                raise CorpusError(f"duplicate or invalid manifest path: {task.task_id}")
            seen.add(relative)
            artifact = root / relative
            if not artifact.is_file():
                raise CorpusError(f"missing manifest artifact: {relative}")
            actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if entry.get("sha256") != actual:
                raise CorpusError(f"manifest artifact digest mismatch: {relative}")
        task_entries = [
            entry
            for entry in files
            if isinstance(entry, dict) and entry.get("role") != "task-definition"
        ]
        if task_entries != [entry.model_dump(mode="json") for entry in task.manifest]:
            raise CorpusError(f"task manifest mismatch: {task.task_id}")


validate_corpus_manifest = validate_manifest


def manifest_digest(entries: list[dict[str, Any]]) -> str:
    return digest(sorted(entries, key=lambda entry: str(entry.get("path", ""))))


CorpusLoader = Corpus


def load_corpus(root: Path) -> Corpus:
    return Corpus.load(root)
